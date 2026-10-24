"""Assistant-side RAG boundary tests, without altering the RAG team's adapter."""
import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from app.assistant_knowledge import query_business_knowledge
from app.assistant_readiness import ASSISTANT_PROTOCOL
from app.assistant_service import _rag_search, run_agent_events


class AssistantKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch('app.assistant_knowledge.settings.RAG_BASE_URL', 'http://rag-service'),
                        patch('app.assistant_knowledge.settings.RAG_SERVICE_TOKEN', 'service-test-token'),
                        patch('app.assistant_knowledge.settings.ASSISTANT_RAG_REQUEST_TIMEOUT', 300)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def payload(self, **updates):
        return {'scope': 'business_rules', 'evidence_status': 'sufficient', 'retrieval_rounds': 1,
                'stop_reason': 'coverage_sufficient', 'sources': [{
            'content': '核对提款币种', 'document_id': 'document-1', 'chunk_id': 'chunk-1',
            'document_name': '业务规则', 'page': 2, 'score': 0.91, 'citation': 1,
            'metadata': {'scope': 'business_rules'},
        }], 'warnings': [], 'missing': [], 'source_status': {'knowledge_base': 'ready'}, **updates}

    def invoke(self, payload, *, status=200, top_k=6, query='currency question', version='1.2.0'):
        def handler(request):
            self.request = request
            headers = {'X-RAG-Contract-Version': version} if version is not None else {}
            return httpx.Response(status, json=payload, headers=headers)
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            with patch('app.assistant_knowledge.httpx.post', side_effect=http.post):
                return query_business_knowledge(query, top_k=top_k)

    def test_uses_enhanced_retrieval_for_business_rules_without_task_or_user_identity(self):
        result = self.invoke(self.payload())
        self.assertEqual(str(self.request.url), 'http://rag-service/api/v1/retrievals')
        self.assertEqual(json.loads(self.request.content), {
            'query': 'currency question', 'scope': 'business_rules', 'top_k': 6,
            'sources': ['knowledge_base'], 'purpose': 'reference',
        })
        self.assertEqual(self.request.headers['Authorization'], 'Bearer service-test-token')
        self.assertEqual(self.request.extensions['timeout']['read'], 300)
        self.assertEqual(result['evidence'][0]['chunk_id'], 'chunk-1')
        self.assertEqual(result['evidence'][0]['metadata']['scope'], 'business_rules')
        self.assertEqual(result['evidence'][0]['score'], 0.91)

    def test_carries_retrieval_insufficiency_and_clarification_to_the_assistant(self):
        result = self.invoke(self.payload(
            evidence_status='clarification',
            clarification_question='请说明付款所用币种？',
            missing=['付款币种'],
        ))
        self.assertTrue(any('请说明付款所用币种' in item for item in result['warnings']))
        self.assertTrue(any('付款币种' in item for item in result['warnings']))

    def test_limits_requested_top_k_to_the_enhanced_contract(self):
        result = self.invoke(self.payload(sources=[self.payload()['sources'][0]] * 9), top_k=20)
        self.assertEqual(json.loads(self.request.content)['top_k'], 8)
        self.assertEqual(len(result['evidence']), 8)
        self.assertTrue(any('限制数量' in item for item in result['warnings']))

    def test_does_not_truncate_queries_over_the_rag_contract_limit(self):
        context = {'task': {'task_code': 'TASK-1'}, 'documents': [], 'results': []}
        notices = []
        with patch('app.assistant_knowledge.httpx.post') as network:
            hits = _rag_search(context, '授信材料' * 1001, notices)
        network.assert_not_called()
        self.assertEqual([item['type'] for item in hits], ['task'])
        self.assertTrue(any('4,000 字符上限' in item for item in notices))

    def test_query_at_the_rag_contract_limit_is_sent_in_full(self):
        query = '授' * 4000
        self.invoke(self.payload(), query=query)
        self.assertEqual(json.loads(self.request.content)['query'], query)

    def test_trims_surrounding_whitespace_before_retrieval(self):
        result = self.invoke(self.payload(), query='  汇款币种核对  ')
        self.assertEqual(json.loads(self.request.content)['query'], '汇款币种核对')
        self.assertTrue(result['evidence'])

    def test_rejects_missing_older_and_new_major_rag_contracts(self):
        for version in (None, 'unknown', '1.1.9', '2.0.0'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.invoke(self.payload(), version=version)

    def test_accepts_compatible_future_minor_and_patch_contracts(self):
        for version in ('1.2.0', '1.2.7', '1.3.0', '1.3.2', '1.3.3'):
            with self.subTest(version=version):
                self.assertTrue(self.invoke(self.payload(), version=version)['evidence'])

    def test_preserves_source_coverage_and_reranker_limitations(self):
        result = self.invoke(self.payload(
            source_status={'knowledge_base': 'unavailable'},
            rerank_status='unavailable',
            context_coverage={'input_complete': False},
            legal_applicability={'requires_review': True},
        ))
        self.assertTrue(any('知识来源未能完整提供' in item for item in result['warnings']))
        self.assertTrue(any('排序能力不可用' in item for item in result['warnings']))
        self.assertTrue(any('上下文完整' in item for item in result['warnings']))
        self.assertTrue(any('法规适用性' in item for item in result['warnings']))

    def test_rejects_unapproved_scope_and_malformed_evidence(self):
        for payload in (self.payload(scope='all'), self.payload(scope='project_design'),
                        self.payload(scope='law'), self.payload(scope=None),
                        {'sources': [], 'warnings': []}, self.payload(sources=[{'content': None}]),
                        self.payload(sources=[{'content': '无可追溯来源'}]),
                        self.payload(sources=[{'content': '设计资料', 'metadata': {'scope': 'project_design'}}])):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.invoke(payload)

    def test_missing_token_never_sends_request(self):
        with patch('app.assistant_knowledge.settings.RAG_SERVICE_TOKEN', ''), patch(
            'app.assistant_knowledge.httpx.post'
        ) as network:
            with self.assertRaises(RuntimeError):
                query_business_knowledge('test')
            network.assert_not_called()

    def test_budget_retains_chunk_ids_and_discloses_truncation(self):
        row = self.payload()['sources'][0]
        result = self.invoke(self.payload(sources=[{**row, 'chunk_id': f'chunk-{i}'} for i in range(9)]))
        self.assertEqual(len(result['evidence']), 6)
        self.assertEqual(result['evidence'][-1]['chunk_id'], 'chunk-5')
        self.assertTrue(result['warnings'])

    def test_http_failure_preserves_authorized_context_and_hides_upstream_body(self):
        context = {'task': {'task_code': 'TASK-1'}, 'documents': [], 'results': []}
        responses = (
            (403, {'detail': 'PRIVATE_UPSTREAM_INFORMATION'}),
            (422, {'detail': [{'loc': ['body', '<unknown_field>'], 'category': 'unknown_field'}]}),
        )
        for status, body in responses:
            with self.subTest(status=status):
                notices = []
                def handler(request):
                    return httpx.Response(status, json=body)
                with httpx.Client(transport=httpx.MockTransport(handler)) as http, patch(
                    'app.assistant_knowledge.httpx.post', side_effect=http.post
                ):
                    hits = _rag_search(context, '核对业务', notices)
                self.assertEqual([hit['type'] for hit in hits], ['task'])
                self.assertEqual(notices, ['知识库暂不可用；本次回复仅基于当前任务已加载的本地证据。'])
                self.assertNotIn('PRIVATE_UPSTREAM_INFORMATION', str(notices))
                self.assertNotIn('<unknown_field>', str(notices))

    def test_wrong_scope_is_not_sent_to_model_as_review_evidence(self):
        context = {'task': {'task_code': 'TASK-1'}, 'documents': [], 'results': []}
        notices = []
        with httpx.Client(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=self.payload(scope='project_design'),
                                     headers={'X-RAG-Contract-Version': '1.2.0'})
        )) as http, patch('app.assistant_knowledge.httpx.post', side_effect=http.post):
            hits = _rag_search(context, '核对业务', notices)
        self.assertEqual([row['type'] for row in hits], ['task'])
        self.assertTrue(notices)

    def test_business_retrieval_reaches_runtime_and_returns_resolved_citations(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.host == 'rag-service':
                self.assertEqual(request.headers['Authorization'], 'Bearer service-test-token')
                self.assertEqual(json.loads(request.content)['scope'], 'business_rules')
                return httpx.Response(200, json=self.payload(),
                                      headers={'X-RAG-Contract-Version': '1.3.3'})
            self.assertEqual(request.headers['Authorization'], 'Bearer runtime-test-token')
            if request.url.path == '/readyz':
                return httpx.Response(200, json={'status': 'ready', 'configured': True,
                                                'assistant_protocol': ASSISTANT_PROTOCOL})
            submitted = json.loads(request.content)
            self.assertEqual([row['id'] for row in submitted['evidence']], ['TASK-1', 'chunk-1'])
            self.assertEqual(submitted['evidence'][1]['reference_id'], 'E2')
            events = [{'event': 'tool', 'tool': {'status': 'completed'}},
                      {'event': 'assistant_result', 'answer': '请核对提款币种 [E2]。'}]
            return httpx.Response(200, text=''.join('data: ' + json.dumps(row) + '\n\n' for row in events))

        async def collect():
            transport = httpx.MockTransport(handler)
            runtime = httpx.AsyncClient(transport=transport)
            try:
                with httpx.Client(transport=transport) as rag, patch(
                    'app.assistant_service.httpx.AsyncClient', return_value=runtime
                ), patch('app.assistant_knowledge.httpx.post', side_effect=rag.post), patch(
                    'app.assistant_service.settings.ASSISTANT_RUNTIME_URL', 'http://runtime'
                ), patch('app.assistant_service.settings.ASSISTANT_RUNTIME_TOKEN', 'runtime-test-token'):
                    return [event async for event in run_agent_events('提款币种核对',
                            {'task': {'task_code': 'TASK-1'}, 'documents': [], 'results': []})]
            finally:
                await runtime.aclose()

        result = asyncio.run(collect())[-1]
        self.assertEqual(len(requests), 3)  # readiness, real retrieval adapter, runtime
        self.assertEqual(result['answer'], '请核对提款币种 [E2]。')
        self.assertEqual(result['citations'][0]['source_id'], 'chunk-1')
        self.assertEqual(result['citations'][0]['page'], 2)
