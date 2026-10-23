import unittest
from app.parsing.contracts import Block,Page
from app.parsing.normalization import normalize,normalize_source
from app.parsing.pipeline import validate_candidate
from app.parsing.registry import QTY,QUNIT


class MeasurementTests(unittest.TestCase):
    def test_registered_unit_is_separated_without_converting_the_quantity(self):
        self.assertEqual(normalize_source('89860千克',QTY),'89860')
        self.assertEqual(normalize('千克','unit'),'kg')
        self.assertEqual(normalize('元/公吨','unit'),'MT')
        self.assertEqual(normalize('(CNY/MT)','unit'),'MT')

    def test_ambiguous_ton_is_not_silently_metric(self):
        with self.assertRaises(ValueError):normalize('ton','unit')
        with self.assertRaises(ValueError):normalize_source('89860未知单位',QTY)

    def test_thousand_fold_model_rewrite_is_rejected(self):
        p=Page(1,1000,1000,b'',[Block('p1b0','89860千克',[.1,.1,.8,.2],.99,'paddle_http')])
        candidate=dict(value='89.86',raw_value='89860千克',block_ids=['p1b0'],visual_state='clear')
        result=validate_candidate(candidate,QTY,[p],'vision')
        self.assertIn('VALUE_SOURCE_MISMATCH',result['issues'])

    def test_unit_must_appear_in_cited_source(self):
        p=Page(1,1000,1000,b'',[Block('p1b0','千克',[.1,.1,.8,.2],.99,'paddle_http')])
        result=validate_candidate(dict(value='MT',raw_value='千克',block_ids=['p1b0'],visual_state='clear'),QUNIT,[p],'vision')
        self.assertIn('VALUE_SOURCE_MISMATCH',result['issues'])


if __name__=='__main__':unittest.main()
