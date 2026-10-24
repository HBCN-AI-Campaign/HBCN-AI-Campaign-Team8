import unittest
from app.parsing.contracts import Block,Page
from app.parsing.normalization import normalize,normalize_source
from app.parsing.pipeline import validate_candidate,resolve
from app.parsing.registry import FIELDS


SPEC=next(s for s in FIELDS['DRAWDOWN_INSTRUCTION'] if s['key']=='facility_letter_date')


class DateLinesTests(unittest.TestCase):
    def test_filled_chinese_form_lines_are_layout_not_missing_digits(self):
        for raw in ('_2019_年_12_月_19_日','2019___年 12__月 19_日','２０１９＿年１２＿月１９＿日'):
            with self.subTest(raw=raw):self.assertEqual(normalize(raw,'date'),'2019-12-19')
        raw='于_2019_年_12_月_19_日订立的银行授信函'
        self.assertEqual(normalize_source(raw,SPEC),'2019-12-19')
        page=Page(2,100,100,b'',[Block('p2b0','我司谨提及'+raw,[.1,.2,.9,.3],.99,'paddle_http')])
        candidate=validate_candidate(dict(key=SPEC['key'],value='2019-12-19',raw_value=raw,
            block_ids=['p2b0'],visual_state='clear'),SPEC,[page],'vision')
        self.assertEqual(candidate['issues'],[])
        self.assertEqual(resolve(SPEC,[candidate])['value'],'2019-12-19')

    def test_missing_split_invalid_and_ambiguous_dates_stay_unresolved(self):
        for raw in ('20_19年12月19日','2019年__月19日','____年12月19日',
                    '2019年12月1_9日','2019年02月29日','12/10/2026'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):normalize(raw,'date')
                with self.assertRaises(ValueError):normalize_source(raw,SPEC)
        with self.assertRaises(ValueError):normalize_source('于_2019_年_12_月_19_日至2020年1月1日',SPEC)


if __name__=='__main__':unittest.main()
