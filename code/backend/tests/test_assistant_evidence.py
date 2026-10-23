import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from app.assistant_evidence import cited_sources, prepare_evidence
from app.assistant_readiness import ASSISTANT_PROTOCOL
from app.assistant_service import (_attach_task_document_locations, _safe_task_pdf_file,
                                   _task_pdf_is_available, run_agent_events, search_evidence)


class AssistantEvidenceTests(unittest.TestCase):
    def test_task_document_location_is_attached_only_to_matching_local_evidence(self):
        citations = [
            {'id': 'E1', 'reference_id': 'E1', 'source_id': 'F1', 'label': 'F1', 'source': 'F1', 'page': None},
            {'id': 'E2', 'reference_id': 'E2', 'source_id': 'F1', 'label': '知识库', 'source': '知识库', 'page': 8},
            {'id': 'E3', 'reference_id': 'E3', 'source_id': 'F2', 'label': 'F2', 'source': 'F2', 'page': None},
        ]
        evidence = [
            {'type': 'document', 'id': 'F1', 'reference_id': 'E1'},
            {'type': 'knowledge', 'id': 'F1', 'reference_id': 'E2'},
            {'type': 'document', 'id': 'F2', 'reference_id': 'E3'},
        ]
        context = {'documents': [
            {'doc_code': 'F1', 'pdf_file': 'facility_letter.pdf',
             'field_sources': {'borrower': {'page': 3, 'bbox': [0, 0, 1, 1]}}},
            {'doc_code': 'F2', 'pdf_file': '../../private.pdf', 'field_sources': {}},
        ]}

        located = _attach_task_document_locations(citations, evidence, context)

        self.assertEqual(located[0]['pdf_file'], 'facility_letter.pdf')
        self.assertEqual(located[0]['doc_code'], 'F1')
        self.assertEqual(located[0]['page'], 3)
        self.assertNotIn('pdf_file', located[1])
        self.assertNotIn('pdf_file', located[2])
        self.assertNotIn('pdf_file', citations[0])

    def test_pdf_paths_allow_only_sample_file_or_upload_batch_shape(self):
        self.assertEqual(_safe_task_pdf_file('facility_letter.pdf'), 'facility_letter.pdf')
        self.assertTrue(_task_pdf_is_available('facility_letter.pdf'))
        self.assertEqual(_safe_task_pdf_file('uploads/batch-123/invoice.pdf'), 'uploads/batch-123/invoice.pdf')
        self.assertFalse(_task_pdf_is_available('uploads/batch-123/invoice.pdf'))
        for path in ('../private.pdf', 'uploads/../private.pdf', '/etc/private.pdf',
                     'uploads/batch/file.pdf?download=1', 'uploads\\batch\\file.pdf', 'readme.txt'):
            with self.subTest(path=path):
                self.assertIsNone(_safe_task_pdf_file(path))

    def test_chinese_question_keeps_task_fields_and_rule_status_without_keyword_match(self):
        context = {'task': {'task_code': 'SYNTHETIC', 'currency': 'USD', 'amount': 100},
                   'documents': [{'doc_code': 'F1', 'fields': {'currency': 'CNY'}}],
                   'results': [{'rule_id': 'R01', 'rule_name': '币种一致性', 'why': '不一致', 'status': 'fail', 'suggestion': '人工核对'}]}
        hits = search_evidence(context, '请帮我梳理这笔业务的关注点')
        self.assertEqual({row['type'] for row in hits}, {'task', 'rule', 'document'})
        self.assertEqual(json.loads(hits[0]['text'])['amount'], 100)
        self.assertIn('fail', next(row['text'] for row in hits if row['type'] == 'rule'))

    def test_source_numbers_are_scoped_to_the_exact_bounded_payload_and_experts_are_not_evidence(self):
        sources = [{'id': f'doc-{i}', 'source': 'same-document', 'text': 'x' * 5000, 'page': i} for i in range(25)]
        experts = [{'type': 'expert', 'id': 'expert:1', 'source': 'directory', 'text': 'colleague bio'}]
        prepared = prepare_evidence(sources, experts)
        self.assertEqual(len(prepared), 20)
        self.assertEqual(len(prepared[0]['text']), 4000)
        self.assertEqual(prepared[-2]['reference_id'], 'E19')
        self.assertIsNone(prepared[-1]['reference_id'])
        selected, valid = cited_sources('见 [E2] 与 [E1]，再见 [E2]。', prepared, tool_used=True)
        self.assertTrue(valid)
        self.assertEqual([row['id'] for row in selected], ['E2', 'E1'])
        self.assertEqual([row['page'] for row in selected], [1, 0])
        self.assertEqual(selected[0]['source_id'], 'doc-1')

    def test_unread_out_of_budget_and_expert_ids_cannot_be_accepted(self):
        prepared = prepare_evidence([{'id': 'a', 'source': 's', 'text': 't'}], [{'type': 'expert', 'id': 'expert:1'}])
        for answer, used in [('结论 [E1]', False), ('结论 [E2]', True), ('结论 [E999]', True), ('结论 [E0]', True), ('结论 [E01]', True)]:
            with self.subTest(answer=answer, tool_used=used):
                self.assertEqual(cited_sources(answer, prepared, tool_used=used), ([], False))
        self.assertEqual(cited_sources('普通建议', prepared, tool_used=True), ([], True))

    async def collect(self, answer, *, tool=True, sources=None, warnings=None, context=None):
        async def handler(request):
            if request.url.path == '/readyz':
                return httpx.Response(200, json={'status': 'ready', 'configured': True, 'assistant_protocol': ASSISTANT_PROTOCOL})
            self.submitted = json.loads(request.content)
            events = ([{'event': 'tool', 'tool': {'status': 'completed'}}] if tool else []) + [
                {'event': 'assistant_result', 'answer': answer}]
            return httpx.Response(200, text=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))
        def retrieve(context, message, notices):
            notices.extend(warnings or [])
            return sources or [{'id': 'chunk-one', 'type': 'knowledge', 'text': '授权依据', 'source': '合成资料', 'page': 3},
                               {'id': 'chunk-two', 'type': 'knowledge', 'text': '候选材料', 'source': '另一资料', 'page': 4}]
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch('app.assistant_service.httpx.AsyncClient', return_value=client), patch(
            'app.assistant_service._rag_search', side_effect=retrieve
        ), patch('app.assistant_service.sdk_configured', return_value=True), patch(
            'app.assistant_service.settings.ASSISTANT_RUNTIME_URL', 'http://runtime'
        ), patch('app.assistant_service.settings.ASSISTANT_RUNTIME_TOKEN', 'test-runtime-token'
        ):
            return [event async for event in run_agent_events('核对合成资料', context or {})]

    def test_only_referenced_sources_are_returned_and_warning_remains_public(self):
        events = asyncio.run(self.collect('核对结果 [E1]。', warnings=['知识库暂不可用；请人工复核。']))
        self.assertEqual(self.submitted['evidence'][0]['reference_id'], 'E1')
        self.assertEqual([row['id'] for row in events[-1]['citations']], ['E1'])
        self.assertEqual(events[0]['step']['key'], 'retrieval-warning-0')
        self.assertEqual(events[0]['step']['status'], 'error')

    def test_task_pdf_location_is_added_after_model_payload_and_reference_are_validated(self):
        events = asyncio.run(self.collect(
            '查看任务材料 [E1]。',
            sources=[{'id': 'F1', 'type': 'document', 'text': '授权字段', 'source': 'F1'}],
            context={'documents': [{'doc_code': 'F1', 'pdf_file': 'facility_letter.pdf',
                                    'field_sources': {'borrower': {'page': 2}}}]},
        ))

        self.assertEqual(events[-1]['citations'][0]['pdf_file'], 'facility_letter.pdf')
        self.assertEqual(events[-1]['citations'][0]['page'], 2)
        self.assertNotIn('pdf_file', json.dumps(self.submitted))

    def test_unknown_reference_is_blocked_before_any_body_delta(self):
        for used in (False, True):
            with self.subTest(tool=used):
                events = asyncio.run(self.collect('编造的结论 [E999]', tool=used))
                self.assertFalse(any(event['event'] == 'delta' for event in events))
                self.assertIsNone(events[-1]['answer'])
                self.assertEqual(events[-1]['citations'], [])
                self.assertTrue(any(event.get('step', {}).get('key') == 'citation-warning-invalid' for event in events))

    def test_reading_tool_does_not_imply_all_candidates_were_cited(self):
        events = asyncio.run(self.collect('建议人工核对。'))
        self.assertEqual(events[-1]['citations'], [])
        self.assertEqual(events[-1]['answer'], '建议人工核对。')
        self.assertTrue(any(event.get('step', {}).get('key') == 'citation-warning-missing' for event in events))

    def test_greeting_can_answer_without_forced_sources_or_missing_reference_warning(self):
        events = asyncio.run(self.collect('您好，可以协助整理审核材料。', tool=False))
        self.assertEqual(events[-1]['citations'], [])
        self.assertTrue(any(event['event'] == 'delta' for event in events))
        self.assertFalse(any(event.get('step', {}).get('key') == 'citation-warning-missing' for event in events))

    def test_experts_are_not_counted_as_evidence_and_truncation_is_disclosed(self):
        events = asyncio.run(self.collect('结论 [E1]', sources=[
            {'id': 'long-chunk', 'type': 'knowledge', 'text': 'x' * 4001, 'source': '合成资料'}],
            context={'expert_candidates': [{'type': 'expert', 'id': 'expert:1', 'text': '个人介绍'}]}))
        self.assertEqual(next(event['tool']['result_count'] for event in events if event['event'] == 'tool'), 1)
        self.assertTrue(any('部分授权材料片段' in event.get('step', {}).get('detail', '') for event in events))

    def test_incompatible_runtime_is_blocked_before_posting_a_model_run(self):
        for code in ('protocol_mismatch', 'token_rejected', 'contract_missing'):
            with self.subTest(code=code):
                requests = []
                async def handler(request):
                    requests.append(request.method)
                    raise AssertionError('No run should be sent to an incompatible runtime')
                async def collect():
                    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
                    with patch('app.assistant_service.httpx.AsyncClient', return_value=client), patch(
                        'app.assistant_service.sdk_configured', return_value=True
                    ), patch('app.assistant_service._rag_search', return_value=[]) as retrieval, patch(
                        'app.assistant_service.runtime_readiness', return_value={'ready': False, 'code': code}
                    ):
                        events = [event async for event in run_agent_events('test', {})]
                        retrieval.assert_not_called()
                        return events
                events = asyncio.run(collect())
                self.assertEqual(requests, [])
                self.assertEqual(events[0]['event'], 'warning')
                self.assertIsNone(events[-1]['answer'])
