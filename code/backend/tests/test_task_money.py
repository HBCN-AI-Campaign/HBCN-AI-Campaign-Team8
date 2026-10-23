"""Money boundaries through real HTTP, database reload, rules and assistant facts."""
from decimal import Decimal
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.assistant_service import task_context
from app.database import Base, get_db
from app.routers.tasks import router
from app.security import create_access_token
from app.schemas import TaskCreate
from app.parsing.facility import analyze_facility
from app.rule_engine.base import DocBundle, Status
from app.rule_engine.rules import R_DrawdownAmountWithinFacility
from tests.test_parsing_facility import documents, at


class TaskMoneyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add(models.User(username='money-operator', display_name='Money', hashed_password='unused', role=models.Role.OPERATOR))
            db.commit()
        app = FastAPI()
        app.include_router(router)
        def dependency():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = dependency
        self.client = TestClient(app)
        self.headers = {'Authorization': 'Bearer ' + create_access_token('money-operator', 'operator')}

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def create(self, amount):
        return self.client.post('/api/tasks', headers=self.headers, json={
            'borrower': 'Synthetic Money', 'drawdown_currency': 'CNY', 'drawdown_amount': amount,
            'documents': [{'doc_code': 'DD', 'type_code': 'DRAWDOWN_INSTRUCTION', 'fields': {'amount': '12000000.01', 'currency': 'CNY'}}],
        })

    def test_exact_cents_survive_create_detail_list_database_and_assistant(self):
        for amount in ['0.01', '12000000.01', 100, 100.0]:
            with self.subTest(amount=amount):
                expected = format(Decimal(str(amount)), '.2f')
                response = self.create(amount)
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(response.json()['drawdown_amount'], expected)
                code = response.json()['task_code']
                detail = self.client.get('/api/tasks/' + code, headers=self.headers)
                self.assertEqual(detail.json()['drawdown_amount'], expected)
                listing = self.client.get('/api/tasks', headers=self.headers).json()
                self.assertEqual(next(t for t in listing if t['task_code'] == code)['drawdown_amount'], expected)
                with self.sessions() as db:
                    task = db.query(models.ReviewTask).filter_by(task_code=code).one()
                    self.assertEqual(task.drawdown_amount, Decimal(expected))
                    self.assertEqual(task_context(task)['task']['amount'], expected)

    def test_sqlite_loss_rolls_back_entire_task_and_documents_before_rules(self):
        with patch('app.routers.tasks._run_and_persist') as run:
            response = self.create('90071992547409.93')
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()['detail']['code'], 'TASK_AMOUNT_STORAGE_PRECISION')
        run.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.query(models.ReviewTask).count(), 0)
            self.assertEqual(db.query(models.Document).count(), 0)
            self.assertEqual(db.query(models.CheckResult).count(), 0)
        # A rejected write does not poison the connection or consume the task code.
        retry = self.create('12000000.01')
        self.assertEqual(retry.status_code, 201, retry.text)
        self.assertTrue(retry.json()['task_code'].endswith('-0001'))

    def test_invalid_or_already_floating_amount_is_not_rounded_into_a_task(self):
        for amount in ['-0.01', '100.001', '99999999999999999.99', 'NaN', 'Infinity', True, 0.01, 90071992547409.93, 9007199254740992]:
            with self.subTest(amount=amount):
                self.assertEqual(self.create(amount).status_code, 422)
        with self.sessions() as db:
            self.assertEqual(db.query(models.ReviewTask).count(), 0)

    def test_large_cent_difference_is_preserved_in_schema_association_and_rule(self):
        amount = '90071992547409.93'
        header = TaskCreate(borrower='甲公司', drawdown_currency='USD', drawdown_amount=amount)
        self.assertEqual(header.model_dump(mode='json')['drawdown_amount'], amount)
        docs = documents()
        at(docs, 'DD-01', 'amount')['value'] = amount
        at(docs, 'FOL-01', 'borrower_allocations')['value'][0]['amount'] = '90071992547409.94'
        at(docs, 'FOL-01', 'facility_limits')['value'][0]['amount'] = '90071992547409.94'
        # Update the synthetic row value too; this is no real OCR accuracy claim.
        for key in ['borrower_allocations', 'facility_limits']:
            field = at(docs, 'FOL-01', key)
            field['row_results'][0]['value']['amount'] = field['value'][0]['amount']
        context = analyze_facility(docs, task_request=header.model_dump(mode='json'))
        self.assertEqual(context['status'], 'ready')
        self.assertEqual(context['comparison'], 'within_nominal_limit')
        header.drawdown_amount += Decimal('0.01')
        mismatched = analyze_facility(docs, task_request=header.model_dump(mode='json'))
        self.assertIn('TASK_AMOUNT_MISMATCH', [i['code'] for i in mismatched['issues']])
        # Exercise the actual rule comparator independently of SQLite storage.
        dd = models.Document(doc_code='DD', type_code=models.DocumentType.DRAWDOWN_INSTRUCTION,
            fields={'amount': '90071992547409.95', 'currency': 'USD'})
        fol = models.Document(doc_code='FOL', type_code=models.DocumentType.FACILITY_LETTER,
            fields={'facility_amount': '90071992547409.94', 'facility_currency': 'USD'})
        result = R_DrawdownAmountWithinFacility().evaluate(DocBundle({
            'DRAWDOWN_INSTRUCTION': [dd.fields], 'FACILITY_LETTER': [fol.fields],
        }))
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn('90,071,992,547,409.95', result.why)
        self.assertIn('90,071,992,547,409.94', result.why)


if __name__ == '__main__':
    unittest.main()
