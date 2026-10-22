"""Exercise main's business changes alongside lfc's assistant in the real app."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.main import app
from app.security import create_access_token


class MainLfcIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as db:
            db.add_all([
                models.User(username="merge-operator", display_name="Operator",
                            hashed_password="unused", role=models.Role.OPERATOR),
                models.User(username="merge-reviewer", display_name="Reviewer",
                            hashed_password="unused", role=models.Role.REVIEWER),
                models.Customer(customer_no="C0001", name="Integration Customer"),
            ])
            db.commit()

        def isolated_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        self.engine_patch = patch("app.main.engine", self.engine)
        self.engine_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.operator = {"Authorization": "Bearer " + create_access_token("merge-operator", "operator")}
        self.reviewer = {"Authorization": "Bearer " + create_access_token("merge-reviewer", "reviewer")}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.engine_patch.stop()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def create_task(self):
        response = self.client.post("/api/tasks", headers=self.operator, json={
            "customer_no": "C0001", "borrower": "Integration Customer",
            "drawdown_currency": "USD", "drawdown_amount": 100,
            "documents": [{"doc_code": "F1", "type_code": "FACILITY_LETTER",
                           "fields": {"currency": "USD"}}],
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["customer_no"], "C0001")
        self.assertEqual(response.json()["status"], "pending")
        return response.json()["task_code"]

    def test_customer_task_review_and_assistant_share_the_app(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/docs").status_code, 200)
        customers = self.client.get("/api/customers?q=C0001", headers=self.operator)
        self.assertEqual(customers.status_code, 200)
        self.assertEqual(customers.json()[0]["name"], "Integration Customer")
        task_code = self.create_task()
        started = self.client.post(f"/api/tasks/{task_code}/ai/start", headers=self.reviewer)
        self.assertEqual(started.status_code, 200, started.text)
        detail = self.client.get(f"/api/tasks/{task_code}", headers=self.reviewer)
        self.assertEqual(detail.json()["status"], "ai_reviewing")
        finished = self.client.post(f"/api/tasks/{task_code}/ai/complete", headers=self.reviewer)
        self.assertEqual(finished.status_code, 200, finished.text)
        self.assertEqual(finished.json()["status"], "to_recheck")
        session = self.client.post("/api/assistant/sessions", headers=self.reviewer,
                                   json={"title": "Merged review", "task_code": task_code})
        self.assertEqual(session.status_code, 201, session.text)
        self.assertEqual(session.json()["task_code"], task_code)
        dashboard = self.client.get("/api/tasks/dashboard", headers=self.reviewer)
        self.assertEqual(dashboard.json()["to_recheck"], 1)
        self.assertEqual(self.client.get("/api/assistant/sessions", headers=self.operator).status_code, 403)

    def test_field_edit_rechecks_without_losing_customer_or_status(self):
        task_code = self.create_task()
        detail = self.client.get(f"/api/tasks/{task_code}", headers=self.reviewer).json()
        doc_id = detail["documents"][0]["id"]
        changed = self.client.patch(f"/api/tasks/{task_code}/documents/{doc_id}/fields",
                                    headers=self.operator,
                                    json={"updates": [{"field_key": "currency", "value": "EUR"}]})
        self.assertEqual(changed.status_code, 200, changed.text)
        data = changed.json()
        self.assertEqual(data["documents"][0]["fields"]["currency"], "EUR")
        self.assertEqual(data["customer_no"], "C0001")
        self.assertEqual(data["status"], "pending")
        self.assertFalse(data["needs_recheck"])
