import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.assistant_service import _rag_search, _safe_final_answer, _strip_tool_echo, run_agent_events
from app.assistant_readiness import ASSISTANT_PROTOCOL
from app.database import Base, get_db
from app.routers.assistant import router
from app.security import create_access_token, hash_password


async def _collect_events(stream):
    return [event async for event in stream]


class AssistantApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as db:
            self.reviewer = models.User(
                username="reviewer-test",
                display_name="Reviewer",
                hashed_password=hash_password("reviewer-test"),
                role=models.Role.REVIEWER,
            )
            self.operator = models.User(
                username="operator-test",
                display_name="Operator",
                hashed_password=hash_password("operator-test"),
                role=models.Role.OPERATOR,
            )
            db.add_all([self.reviewer, self.operator])
            db.commit()
            db.refresh(self.reviewer)
            db.refresh(self.operator)
            self.reviewer_id = self.reviewer.id
            self.operator_id = self.operator.id
            db.add(models.ReviewTask(
                task_code="REVIEWER-ONLY",
                borrower="Example Borrower",
                drawdown_currency="USD",
                drawdown_amount=100,
                submitted_by=self.reviewer_id,
            ))
            db.commit()

        app = FastAPI()
        app.include_router(router)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.reviewer_headers = {
            "Authorization": f"Bearer {create_access_token('reviewer-test', 'reviewer')}"
        }
        self.operator_headers = {
            "Authorization": f"Bearer {create_access_token('operator-test', 'operator')}"
        }

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_session_is_private_to_owner(self):
        created = self.client.post(
            "/api/assistant/sessions",
            headers=self.reviewer_headers,
            json={"title": "private"},
        )
        self.assertEqual(created.status_code, 201)
        session_id = created.json()["id"]
        response = self.client.get(
            f"/api/assistant/sessions/{session_id}",
            headers=self.operator_headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_operator_cannot_access_reviewer_assistant_capabilities_sessions_or_skills(self):
        requests = [
            self.client.get("/api/assistant/capabilities", headers=self.operator_headers),
            self.client.get("/api/assistant/sessions", headers=self.operator_headers),
            self.client.get("/api/assistant/skills", headers=self.operator_headers),
            self.client.post("/api/assistant/sessions", headers=self.operator_headers, json={"title": "forbidden"}),
        ]
        self.assertEqual([response.status_code for response in requests], [403, 403, 403, 403])

    def test_strip_tool_echo_removes_model_tool_echo(self):
        # 网关模型会在调用工具前把参数 JSON 当文本回显，需从正文剔除。
        self.assertEqual(_strip_tool_echo('{"query":"abc"}这是答案'), "这是答案")
        self.assertEqual(_strip_tool_echo('{"question":"q"}\n回答'), "回答")
        self.assertEqual(_strip_tool_echo("[1,2,3] 后面"), "后面")
        # 非工具回显或纯 JSON 回答应保留。
        self.assertEqual(_strip_tool_echo("正常回答"), "正常回答")
        self.assertEqual(_strip_tool_echo('{"foo":1}保留'), '{"foo":1}保留')
        self.assertEqual(_strip_tool_echo('{"query":"只有json"}'), '{"query":"只有json"}')

    def test_internal_reasoning_is_rejected_as_final_answer(self):
        self.assertIsNone(_safe_final_answer("我们需要回答用户：先检索一下。最终答案是 OK。"))
        leaked = (
            "用户只是问能力说明，没有具体单据审核证据。我们可以基于知识库："
            "先调用 search_knowledge_base。最终只输出两句话。慧眼助手可协助梳理材料。"
        )
        self.assertIsNone(_safe_final_answer(leaked))
        self.assertEqual(_safe_final_answer("慧眼助手可整理材料并提示风险。"), "慧眼助手可整理材料并提示风险。")

    def test_legacy_reasoning_is_redacted_from_session_api(self):
        created = self.client.post(
            "/api/assistant/sessions", headers=self.reviewer_headers, json={"title": "legacy"}
        )
        with self.session_factory() as db:
            db.add(models.AssistantMessage(
                session_id=created.json()["id"],
                role="assistant",
                content="我们需要回答用户：内部分析内容。最终答复。",
                status="completed",
            ))
            db.commit()
        detail = self.client.get(
            f"/api/assistant/sessions/{created.json()['id']}", headers=self.reviewer_headers
        )
        self.assertIn("已隐藏", detail.json()["messages"][0]["content"])
        self.assertNotIn("内部分析内容", detail.json()["messages"][0]["content"])

    def test_agent_stream_never_exposes_raw_reasoning_delta(self):
        import httpx

        payloads = [
            {"event": "tool", "tool": {"name": "read_authorized_evidence", "status": "running"}},
            {"event": "tool", "tool": {"name": "read_authorized_evidence", "status": "completed", "result_count": 0}},
            {"event": "assistant_result", "answer": "安全的审核辅助答复", "citations": []},
        ]

        async def response_handler(request):
            if request.url.path == '/readyz':
                return httpx.Response(200, json={'status': 'ready', 'configured': True, 'assistant_protocol': ASSISTANT_PROTOCOL})
            body = "".join(f"data: {json.dumps(item)}\n\n" for item in payloads)
            return httpx.Response(200, content=body.encode())

        async def collect_with_runtime():
            client = httpx.AsyncClient(transport=httpx.MockTransport(response_handler))
            with patch("app.assistant_service.httpx.AsyncClient", return_value=client), patch(
                "app.assistant_service.sdk_configured", return_value=True
            ), patch("app.assistant_service.settings.ASSISTANT_RUNTIME_URL", "http://runtime"), patch(
                "app.assistant_service.settings.ASSISTANT_RUNTIME_TOKEN", "test-token"
            ):
                return await _collect_events(run_agent_events("test", {}))

        events = asyncio.run(collect_with_runtime())

        deltas = [event["delta"] for event in events if event["event"] == "delta"]
        self.assertEqual("".join(deltas), "安全的审核辅助答复")
        self.assertNotIn("内部推理", "".join(deltas))

    def test_task_chat_queries_shared_knowledge_base(self):
        context = {"task": {"task_code": "TASK-1"}, "documents": [], "results": []}
        response = {
            "evidence": [{
                "document_id": "doc-1",
                "document_name": "审核规则",
                "content": "提款币种需与合同一致",
                "page": 3,
            }],
            "warnings": [],
        }
        with patch("app.assistant_service.settings.RAG_BASE_URL", "http://rag-service"), patch(
            "app.assistant_service.query_business_knowledge", return_value=response
        ) as query:
            hits = _rag_search(context, "提款币种")

        query.assert_called_once_with(
            "提款币种",
            top_k=6,
        )
        self.assertEqual(hits[0]["type"], "task")
        self.assertEqual(hits[-1]["type"], "knowledge")
        self.assertEqual(hits[-1]["source"], "审核规则")

    def test_rag_failure_is_reported_while_local_evidence_remains(self):
        context = {
            "task": {"task_code": "TASK-1"},
            "documents": [{"doc_code": "DOC-1", "fields": {"currency": "USD"}}],
            "results": [],
        }
        warnings = []
        with patch("app.assistant_service.settings.RAG_BASE_URL", "http://rag-service"), patch(
            "app.assistant_service.query_business_knowledge", side_effect=RuntimeError("private connection detail")
        ):
            hits = _rag_search(context, "currency", warnings)

        self.assertEqual([hit["type"] for hit in hits], ["task", "document"])
        self.assertEqual(len(warnings), 1)
        self.assertNotIn("private connection detail", warnings[0])

    def test_capabilities_reports_configured_rag_and_model(self):
        import httpx

        async def response_handler(request):
            if request.url.path == "/readyz":
                self.assertEqual(request.headers.get("Authorization"), "Bearer runtime-token")
                return httpx.Response(
                    200,
                    json={"status": "ready", "configured": True, "model": "qwen3.8-flash", "assistant_protocol": ASSISTANT_PROTOCOL},
                )
            if request.url.path == "/api/v1/ready":
                self.assertEqual(request.headers.get("Authorization"), "Bearer rag-token")
                return httpx.Response(200, json={"status": "ready", "service": "hbcn-rag-service"})
            return httpx.Response(404)

        real_async_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return real_async_client(transport=httpx.MockTransport(response_handler), *args, **kwargs)

        with patch("app.routers.assistant.httpx.AsyncClient", side_effect=client_factory), patch(
            "app.routers.assistant.sdk_configured", return_value=True
        ), patch("app.routers.assistant.settings.RAG_BASE_URL", "http://rag-service"), patch(
            "app.routers.assistant.settings.ASSISTANT_RUNTIME_URL", "http://assistant-runtime"
        ), patch("app.routers.assistant.settings.ASSISTANT_RUNTIME_TOKEN", "runtime-token"), patch(
            "app.routers.assistant.settings.RAG_SERVICE_TOKEN", "rag-token"
        ):
            response = self.client.get("/api/assistant/capabilities", headers=self.reviewer_headers)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["configured"])
        self.assertTrue(response.json()["rag_available"])
        self.assertEqual(response.json()["model"], "qwen3.8-flash")

    def test_capabilities_rejects_mismatched_runtime_token_even_when_process_is_alive(self):
        import httpx
        real_client = httpx.AsyncClient
        requests = []
        def handler(request):
            requests.append(request.url.path)
            if request.url.path == '/healthz':
                return httpx.Response(200, json={"configured": True})
            return httpx.Response(401, json={"detail": "private upstream content"})
        with patch('app.routers.assistant.httpx.AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)), patch(
            'app.routers.assistant.settings.ASSISTANT_RUNTIME_URL', 'http://runtime'
        ), patch('app.routers.assistant.settings.ASSISTANT_RUNTIME_TOKEN', 'wrong-token'), patch(
            'app.routers.assistant.settings.RAG_BASE_URL', ''
        ):
            response = self.client.get('/api/assistant/capabilities', headers=self.reviewer_headers)
        self.assertFalse(response.json()['configured'])
        self.assertIn('鉴权失败', response.json()['message'])
        self.assertNotIn('private upstream content', response.text)
        self.assertEqual(requests, ['/readyz'])

    def test_capabilities_does_not_confuse_rag_liveness_with_authenticated_readiness(self):
        import httpx
        real_client = httpx.AsyncClient
        def handler(request):
            if request.url.path == '/readyz':
                return httpx.Response(200, json={'status': 'ready', 'configured': True, 'model': 'test-model', 'assistant_protocol': ASSISTANT_PROTOCOL})
            if request.url.path == '/health':
                return httpx.Response(200, json={'status': 'ok'})
            return httpx.Response(401, json={'detail': 'private RAG error'})
        with patch('app.routers.assistant.httpx.AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)), patch(
            'app.routers.assistant.settings.ASSISTANT_RUNTIME_URL', 'http://runtime'
        ), patch('app.routers.assistant.settings.ASSISTANT_RUNTIME_TOKEN', 'runtime-token'), patch(
            'app.routers.assistant.settings.RAG_BASE_URL', 'http://rag'
        ), patch('app.routers.assistant.settings.RAG_SERVICE_TOKEN', 'wrong-token'):
            response = self.client.get('/api/assistant/capabilities', headers=self.reviewer_headers)
        self.assertTrue(response.json()['configured'])
        self.assertFalse(response.json()['rag_available'])
        self.assertNotIn('private RAG error', response.text)

    def test_stale_runtime_is_not_ready_and_send_error_keeps_actionable_diagnosis(self):
        import httpx
        real_client = httpx.AsyncClient
        paths = []
        def handler(request):
            paths.append((request.method, request.url.path))
            return httpx.Response(200, json={'status': 'ready', 'configured': True, 'model': 'old-model'})
        with patch('app.routers.assistant.httpx.AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)), patch(
            'app.routers.assistant.settings.ASSISTANT_RUNTIME_URL', 'http://runtime'
        ), patch('app.routers.assistant.settings.ASSISTANT_RUNTIME_TOKEN', 'runtime-token'), patch(
            'app.routers.assistant.settings.RAG_BASE_URL', ''
        ):
            capabilities = self.client.get('/api/assistant/capabilities', headers=self.reviewer_headers).json()
            self.assertFalse(capabilities['configured'])
            self.assertIn('协议版本不一致', capabilities['message'])
            room = self.client.post('/api/assistant/sessions', headers=self.reviewer_headers, json={}).json()
            response = self.client.post(f"/api/assistant/sessions/{room['id']}/messages/stream",
                                        headers=self.reviewer_headers, json={'content': '你好'})
        self.assertEqual(paths, [('GET', '/readyz'), ('GET', '/readyz')])
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        self.assertIn('协议版本不一致', next(event['message'] for event in events if event['event'] == 'error'))
        self.assertFalse(any(event['event'] == 'delta' for event in events))

    def test_skill_catalog_exposes_only_reviewed_metadata(self):
        response = self.client.get("/api/assistant/skills", headers=self.reviewer_headers)

        self.assertEqual(response.status_code, 200)
        skills = response.json()
        self.assertEqual(len(skills), 6)
        sanctions = next(item for item in skills if item["id"] == "sanctions-screening-review")
        self.assertEqual(sanctions["name"], "制裁名单筛查")
        self.assertEqual(sanctions["permissions"], ["read_authorized_evidence"])
        self.assertNotIn("instructions", sanctions)

    def test_unknown_skill_is_rejected_before_streaming(self):
        created = self.client.post(
            "/api/assistant/sessions", headers=self.reviewer_headers, json={"title": "skill"}
        )
        response = self.client.post(
            f"/api/assistant/sessions/{created.json()['id']}/messages/stream",
            headers=self.reviewer_headers,
            json={"content": "run", "skill_id": "unreviewed-skill"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "审核技能不存在或未发布")

    def test_selected_skill_is_recorded_as_a_public_execution_step(self):
        created = self.client.post(
            "/api/assistant/sessions", headers=self.reviewer_headers, json={"title": "skill"}
        )
        async def fake_agent_events(*args, **kwargs):
            yield {"event": "assistant_result", "answer": "需人工复核", "citations": []}

        with patch("app.assistant_service.sdk_configured", return_value=True), patch(
            "app.assistant_service.run_agent_events", fake_agent_events
        ):
            response = self.client.post(
                f"/api/assistant/sessions/{created.json()['id']}/messages/stream",
                headers=self.reviewer_headers,
                json={"content": "请检查主体", "skill_id": "sanctions-screening-review"},
            )

        self.assertEqual(response.status_code, 200)
        history = self.client.get(
            f"/api/assistant/sessions/{created.json()['id']}", headers=self.reviewer_headers
        ).json()
        steps = history["messages"][-1]["steps"]
        self.assertIn("skill:sanctions-screening-review", [step["key"] for step in steps])

    def test_stream_error_hides_internal_exception_text(self):
        async def failed_stream(*args, **kwargs):
            raise RuntimeError("private endpoint detail")
            yield

        created = self.client.post(
            "/api/assistant/sessions", headers=self.reviewer_headers, json={"title": "error"}
        )
        with patch("app.routers.assistant.stream_assistant", failed_stream):
            response = self.client.post(
                f"/api/assistant/sessions/{created.json()['id']}/messages/stream",
                headers=self.reviewer_headers,
                json={"content": "test"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("助手请求失败，请稍后重试", response.text)
        self.assertNotIn("private endpoint detail", response.text)

    def test_tool_trace_is_persisted_in_session_history(self):
        async def fake_agent_events(*args, **kwargs):
            yield {"event": "tool", "tool": {"name": "read_authorized_evidence", "status": "running"}}
            yield {"event": "step", "step": {
                "key": "retrieval-warning-0",
                "label": "知识库检索提示",
                "detail": "知识库暂不可用",
                "status": "error",
            }}
            yield {"event": "tool", "tool": {
                "name": "read_authorized_evidence", "status": "completed", "result_count": 0,
            }}
            yield {"event": "assistant_result", "answer": "需人工复核", "citations": []}

        created = self.client.post(
            "/api/assistant/sessions", headers=self.reviewer_headers, json={"title": "trace"}
        )
        session_id = created.json()["id"]
        with patch("app.assistant_service.run_agent_events", fake_agent_events):
            response = self.client.post(
                f"/api/assistant/sessions/{session_id}/messages/stream",
                headers=self.reviewer_headers,
                json={"content": "查找对应审核规则"},
            )
        self.assertEqual(response.status_code, 200)
        history = self.client.get(
            f"/api/assistant/sessions/{session_id}", headers=self.reviewer_headers
        ).json()
        saved_steps = history["messages"][-1]["steps"]
        self.assertIn("tool:read_authorized_evidence", [item["key"] for item in saved_steps])
        self.assertIn("retrieval-warning-0", [item["key"] for item in saved_steps])

    def test_stream_returns_steps_answer_and_persisted_history(self):
        created = self.client.post(
            "/api/assistant/sessions",
            headers=self.reviewer_headers,
            json={"title": "new"},
        )
        session_id = created.json()["id"]
        async def fake_agent_events(*args, **kwargs):
            # Execution steps now come from the runtime, not a fixed UI checklist.
            yield {"event": "step", "step": {
                "key": "runtime-answer", "label": "生成审核辅助答复", "status": "running",
            }}
            yield {"event": "step", "step": {
                "key": "runtime-answer", "label": "生成审核辅助答复", "status": "completed",
            }}
            yield {"event": "delta", "delta": "我不能直接决定贷款审核结论。"}
            yield {"event": "assistant_result", "answer": "我不能直接决定贷款审核结论。", "citations": []}

        with patch("app.assistant_service.sdk_configured", return_value=True), patch(
            "app.assistant_service.run_agent_events", fake_agent_events
        ):
            response = self.client.post(
                f"/api/assistant/sessions/{session_id}/messages/stream",
                headers=self.reviewer_headers,
                json={"content": "Can you approve this loan?"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        for event in ("message_start", "step", "delta", "message_end"):
            self.assertIn(f"event: {event}", response.text)
        self.assertIn("有权限的审核人员复核", response.text)

        detail = self.client.get(
            f"/api/assistant/sessions/{session_id}",
            headers=self.reviewer_headers,
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual([item["role"] for item in detail.json()["messages"]], ["user", "assistant"])
        self.assertEqual(detail.json()["messages"][-1]["steps"][0]["key"], "runtime-answer")
        self.assertEqual(len(detail.json()["messages"][-1]["steps"]), 1)
        self.assertEqual(detail.json()["messages"][-1]["steps"][0]["status"], "completed")

    def test_explicit_authority_reminder_is_not_duplicated(self):
        answer = "慧眼助手可梳理授权材料并提示审核风险。最终审核结论必须由**具备相应权限的审核人员确认**。"

        async def fake_agent_events(*args, **kwargs):
            yield {"event": "delta", "delta": answer}
            yield {"event": "assistant_result", "answer": answer, "citations": []}

        created = self.client.post(
            "/api/assistant/sessions", headers=self.reviewer_headers, json={"title": "两句话"}
        ).json()
        with patch("app.assistant_service.run_agent_events", fake_agent_events):
            self.client.post(
                f"/api/assistant/sessions/{created['id']}/messages/stream",
                headers=self.reviewer_headers, json={"content": "用两句话介绍助手"},
            )
        history = self.client.get(
            f"/api/assistant/sessions/{created['id']}", headers=self.reviewer_headers,
        ).json()
        self.assertEqual(history['messages'][-1]['content'], answer)

    def test_unconfigured_model_does_not_fabricate_a_local_answer(self):
        created = self.client.post(
            "/api/assistant/sessions", headers=self.reviewer_headers, json={"title": "no runtime"}
        )
        with patch("app.assistant_service.sdk_configured", return_value=False):
            response = self.client.post(
                f"/api/assistant/sessions/{created.json()['id']}/messages/stream",
                headers=self.reviewer_headers,
                json={"content": "请审核"},
            )

        self.assertIn("event: error", response.text)
        self.assertIn("汇丰模型 API", response.text)
        self.assertNotIn("event: delta", response.text)


if __name__ == "__main__":
    unittest.main()
