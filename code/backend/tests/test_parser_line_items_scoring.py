from copy import deepcopy
import unittest

from scripts.score_parser_line_items import score


class InvoiceScoringTests(unittest.TestCase):
    def setUp(self):
        expected=dict(style='W-DR-02',quantity='1200',unit_price='24.50',amount='29400.00',
                      unit='PCS',currency='USD',pages=[1,2])
        self.gold=dict(filename='invoice.pdf',pages=2,sha256='frozen',line_items=[expected],
                       printed_total_amount='30000.00',printed_total_quantity='1500')
        row={k:v for k,v in expected.items() if k not in ('style','pages')}
        row.update(description='Kleid (Stil: W-DR-02)',block_ids=['p1b1','p2b1'])
        candidate=dict(normalized_value=[row],method='vision',issues=[],evidence=[
            dict(block_id='p1b1',page=1,bbox=[.1,.2,.8,.3]),dict(block_id='p2b1',page=2,bbox=[.1,.1,.8,.2])])
        self.result=dict(source_filename='invoice.pdf',page_count=2,source_sha256='frozen',issues=[],status='ready',fields=[
            dict(key='line_items',status='accepted',value=[row],candidates=[candidate])])

    def test_usable_rows_and_printed_totals_are_scored_separately(self):
        report=score(self.gold,self.result)
        self.assertEqual(report['counts']['correct_rows'],1)
        self.assertEqual(report['counts']['correct_cells'],5)
        self.assertEqual(report['counts']['correct_rows_with_page_and_boxes'],1)
        self.assertEqual(report['row_sums']['amount'],'29400.00')
        self.assertEqual(report['printed_totals']['printed_total_amount'],'30000.00')

    def test_candidate_coverage_is_never_usable_coverage(self):
        self.result['fields'][0].update(status='needs_review',value=None)
        report=score(self.gold,self.result)
        self.assertEqual(report['counts']['correct_rows'],0)
        self.assertEqual(report['candidate_diagnostics'][0]['counts']['correct_rows'],1)

    def test_duplicates_extras_wrong_cells_and_float_money_fail(self):
        for change in ('duplicate','extra','wrong','float'):
            with self.subTest(change=change):
                result=deepcopy(self.result);field=result['fields'][0]
                if change=='duplicate':field['value'].append(deepcopy(field['value'][0]))
                if change=='extra':
                    row=deepcopy(field['value'][0]);row['description']='Kleid (Stil: W-DR-03)';field['value'].append(row)
                if change=='wrong':field['value'][0]['amount']='30000.00'
                if change=='float':field['value'][0]['amount']=29400.0
                report=score(self.gold,result)
                self.assertEqual(report['counts']['complete_correct_collection'],0)
                self.assertGreater(report['counts']['wrong_or_duplicate_rows'],0)

    def test_missing_continuation_page_does_not_pass_location(self):
        self.result['fields'][0]['candidates'][0]['evidence'].pop()
        report=score(self.gold,self.result)
        self.assertEqual(report['counts']['correct_rows'],1)
        self.assertEqual(report['counts']['correct_rows_with_page_and_boxes'],0)

    def test_failed_document_and_wrong_original_cannot_pass(self):
        self.result['issues']=['OCR_FAILED']
        self.assertEqual(score(self.gold,self.result)['counts']['correct_rows'],0)
        self.result['source_sha256']='other'
        with self.assertRaisesRegex(ValueError,'RESULT_SOURCE_HASH_MISMATCH'):score(self.gold,self.result)


if __name__=='__main__':unittest.main()
