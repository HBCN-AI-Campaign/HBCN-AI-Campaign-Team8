import asyncio
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.assistant_service import _rag_search, _safe_final_answer, _strip_tool_echo, run_agent_events
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
        self.assertEqual(response.status_code, 404)

    def test_operator_cannot_attach_another_users_task(self):
        response = self.client.post(
            "/api/assistant/sessions",
            headers=self.operator_headers,
            json={"title": "forbidden", "task_code": "REVIEWER-ONLY"},
        )
        self.assertEqual(response.status_code, 404)

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
        class FakeAgent:
            def __init__(self, **kwargs):
                pass

        class FakeRun:
            final_output = "安全的审核辅助答复"

            async def stream_events(self):
                yield SimpleNamespace(
                    type="raw_response_event",
                    data=SimpleNamespace(delta="内部推理：不应发送给前端"),
                )

        class FakeRunner:
            @staticmethod
            def run_streamed(*args, **kwargs):
                return FakeRun()

        agents_module = types.ModuleType("agents")
        agents_module.Agent = FakeAgent
        agents_module.Runner = FakeRunner
        agents_module.function_tool = lambda function: function
        models_module = types.ModuleType("agents.models")
        models_module.__path__ = []
        chat_module = types.ModuleType("agents.models.openai_chatcompletions")
        chat_module.OpenAIChatCompletionsModel = lambda **kwargs: object()
        openai_module = types.ModuleType("openai")
        openai_module.AsyncOpenAI = lambda **kwargs: object()
        with patch("app.assistant_service.sdk_configured", return_value=True), patch(
            "app.assistant_service.settings.AI_BASE_URL", "https://model.example/v1"
        ), patch("app.assistant_service.settings.AI_API_KEY", "test-key"), patch(
            "app.assistant_service.settings.AI_MODEL", "test-model"
        ), patch.dict(sys.modules, {
            "agents": agents_module,
            "agents.models": models_module,
            "agents.models.openai_chatcompletions": chat_module,
            "openai": openai_module,
        }):
            events = asyncio.run(_collect_events(run_agent_events("test", {})))

        deltas = [event["delta"] for event in events if event["event"] == "delta"]
        self.assertEqual("".join(deltas), "安全的审核辅助答复")
        self.assertNotIn("内部推理", "".join(deltas))

    def test_task_chat_queries_shared_knowledge_base(self):
        from app.rag_service import RAGClient

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
        with patch("app.assistant_service.settings.RAG_BASE_URL", "http://rag-service"), patch.object(
            RAGClient, "query", return_value=response
        ) as query:
            hits = _rag_search(context, "提款币种")

        query.assert_called_once_with(
            query="提款币种",
            scope="knowledge_base",
            task_code="TASK-1",
            top_k=6,
            agentic=True,
            include_external_law=False,
        )
        self.assertEqual(hits[0]["type"], "knowledge")
        self.assertEqual(hits[0]["source"], "审核规则")

    def test_rag_failure_is_reported_while_local_evidence_remains(self):
        from app.rag_service import RAGClient

        context = {
            "task": {"task_code": "TASK-1"},
            "documents": [{"doc_code": "DOC-1", "fields": {"currency": "USD"}}],
            "results": [],
        }
        warnings = []
        with patch("app.assistant_service.settings.RAG_BASE_URL", "http://rag-service"), patch.object(
            RAGClient, "query", side_effect=RuntimeError("private connection detail")
        ):
            hits = _rag_search(context, "currency", warnings)

        self.assertEqual([hit["type"] for hit in hits], ["document"])
        self.assertEqual(len(warnings), 1)
        self.assertNotIn("private connection detail", warnings[0])

    def test_capabilities_reports_configured_rag_and_model(self):
        with patch("app.routers.assistant.sdk_configured", return_value=True), patch(
            "app.routers.assistant.settings.AI_MODEL", "qwen3.8-flash"
        ), patch("app.routers.assistant.settings.RAG_BASE_URL", "http://rag-service"):
            response = self.client.get("/api/assistant/capabilities", headers=self.reviewer_headers)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["configured"])
        self.assertTrue(response.json()["rag_available"])
        self.assertEqual(response.json()["model"], "qwen3.8-flash")

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
            yield {"event": "tool", "tool": {"name": "search_knowledge_base", "status": "running"}}
            yield {"event": "step", "step": {
                "key": "retrieval-warning-0",
                "label": "知识库检索提示",
                "detail": "知识库暂不可用",
                "status": "error",
            }}
            yield {"event": "tool", "tool": {
                "name": "search_knowledge_base", "status": "completed", "result_count": 0,
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
        self.assertIn("tool:search_knowledge_base", [item["key"] for item in saved_steps])
        self.assertIn("retrieval-warning-0", [item["key"] for item in saved_steps])

    def test_stream_returns_steps_answer_and_persisted_history(self):
        created = self.client.post(
            "/api/assistant/sessions",
            headers=self.reviewer_headers,
            json={"title": "new"},
        )
        session_id = created.json()["id"]
        with patch("app.assistant_service.sdk_configured", return_value=False):
            response = self.client.post(
                f"/api/assistant/sessions/{session_id}/messages/stream",
                headers=self.reviewer_headers,
                json={"content": "Can you approve this loan?"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        for event in ("message_start", "step", "delta", "message_end"):
            self.assertIn(f"event: {event}", response.text)
        self.assertIn("不会直接决定贷款审核结论", response.text)

        detail = self.client.get(
            f"/api/assistant/sessions/{session_id}",
            headers=self.reviewer_headers,
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual([item["role"] for item in detail.json()["messages"]], ["user", "assistant"])


if __name__ == "__main__":
    unittest.main()
