"""Assistant-side RAG boundary tests, without altering the RAG team's adapter."""
import json
import unittest
from unittest.mock import patch

import httpx

from app.assistant_knowledge import query_business_knowledge
from app.assistant_service import _rag_search


class AssistantKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch('app.assistant_knowledge.settings.RAG_BASE_URL', 'http://rag-service'),
                        patch('app.assistant_knowledge.settings.RAG_SERVICE_TOKEN', 'service-test-token')]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def payload(self, **updates):
        return {'scope': 'business_rules', 'evidence': [{
            'content': '核对提款币种', 'document_id': 'document-1', 'chunk_id': 'chunk-1',
            'document_name': '业务规则', 'page': 2, 'metadata': {'scope': 'business_rules'},
        }], 'warnings': [], **updates}

    def invoke(self, payload, *, status=200, top_k=6):
        def handler(request):
            self.request = request
            return httpx.Response(status, json=payload)
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            with patch('app.assistant_knowledge.httpx.post', side_effect=http.post):
                return query_business_knowledge('currency question', top_k=top_k)

    def test_requests_only_business_rules_without_task_or_user_identity(self):
        result = self.invoke(self.payload())
        self.assertEqual(str(self.request.url), 'http://rag-service/api/v1/query')
        self.assertEqual(json.loads(self.request.content), {
            'query': 'currency question', 'scope': 'business_rules', 'top_k': 6,
        })
        self.assertEqual(self.request.headers['Authorization'], 'Bearer service-test-token')
        self.assertEqual(result['evidence'][0]['chunk_id'], 'chunk-1')

    def test_rejects_unapproved_scope_and_malformed_evidence(self):
        for payload in (self.payload(scope='all'), self.payload(scope='project_design'),
                        self.payload(scope='law'), self.payload(scope=None),
                        {'evidence': [], 'warnings': []}, self.payload(evidence=[{'content': None}]),
                        self.payload(evidence=[{'content': '设计资料', 'metadata': {'scope': 'project_design'}}])):
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
        row = self.payload()['evidence'][0]
        result = self.invoke(self.payload(evidence=[{**row, 'chunk_id': f'chunk-{i}'} for i in range(9)]))
        self.assertEqual(len(result['evidence']), 6)
        self.assertEqual(result['evidence'][-1]['chunk_id'], 'chunk-5')
        self.assertTrue(result['warnings'])

    def test_http_failure_preserves_authorized_context_and_hides_upstream_body(self):
        context = {'task': {'task_code': 'TASK-1'}, 'documents': [], 'results': []}
        notices = []
        def handler(request):
            return httpx.Response(403, json={'detail': 'PRIVATE_UPSTREAM_INFORMATION'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as http, patch(
            'app.assistant_knowledge.httpx.post', side_effect=http.post
        ):
            hits = _rag_search(context, '核对业务', notices)
        self.assertEqual(hits[0]['type'], 'task')
        self.assertEqual(len(hits), 1)
        self.assertTrue(notices)
        self.assertNotIn('PRIVATE_UPSTREAM_INFORMATION', str(notices))

    def test_wrong_scope_is_not_sent_to_model_as_review_evidence(self):
        context = {'task': {'task_code': 'TASK-1'}, 'documents': [], 'results': []}
        notices = []
        with httpx.Client(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=self.payload(scope='project_design'))
        )) as http, patch('app.assistant_knowledge.httpx.post', side_effect=http.post):
            hits = _rag_search(context, '核对业务', notices)
        self.assertEqual([row['type'] for row in hits], ['task'])
        self.assertTrue(notices)
