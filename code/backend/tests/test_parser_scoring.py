"""Evaluation must not turn absent or unrelated output into a passing guard."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec=importlib.util.spec_from_file_location('parser_scoring',Path(__file__).resolve().parents[1]/'scripts'/'score_parser.py')
scoring=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scoring)


class ParserScoringTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.gold={'scope':'synthetic evaluation boundary','documents':[{
            'filename':'fixture.pdf','pages':1,'sha256':'abc','fields':[],
            'must_remain_unresolved':['payment_date']}]}
        self.result={'source_filename':'fixture.pdf','page_count':1,'source_sha256':'abc',
            'status':'needs_review','issues':[],
            'fields':[{'key':'payment_date','value':None,'status':'needs_review'}]}

    def score(self,result):
        (self.root/'fixture.result.json').write_text(json.dumps(result),encoding='utf-8')
        return scoring.score(self.gold,self.root)

    def test_guard_requires_explicit_unresolved_field_and_healthy_document(self):
        for status in ('missing','needs_review','conflict'):
            candidate=deepcopy(self.result);candidate['fields'][0]['status']=status
            self.assertEqual(self.score(candidate)['counts']['ambiguity_safe'],1)
        for change in ({'fields':[]},{'status':'failed'},{'issues':['OCR_FAILED']},
                       {'fields':[{'key':'payment_date','value':None,'status':'accepted'}]},
                       {'fields':[{'key':'payment_date','value':'2026-10-12','status':'needs_review'}]}):
            with self.subTest(change=change):
                candidate=deepcopy(self.result);candidate.update(change)
                self.assertEqual(self.score(candidate)['counts']['ambiguity_safe'],0)

    def test_absent_document_does_not_pass_guard(self):
        scored=scoring.score(self.gold,self.root)
        self.assertEqual(scored['counts']['ambiguity_safe'],0)
        self.assertIsNone(scored['automatic_coverage'])

    def test_output_must_belong_to_frozen_original(self):
        for key,value in (('source_sha256','different'),('source_filename','other.pdf'),('page_count',2)):
            with self.subTest(key=key):
                candidate=deepcopy(self.result);candidate[key]=value
                with self.assertRaisesRegex(ValueError,'RESULT_SOURCE_'):
                    self.score(candidate)


if __name__=='__main__':unittest.main()
