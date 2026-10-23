"""Business review snapshot, audit, and completion gate regressions."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.business_review.service import (
    create_review_run,
    input_fingerprint,
    record_advisory,
    record_resolution,
)
from app.database import Base, get_db
from app.main import app
from app.rule_engine.base import RuleResult, Status
from app.schemas import ParsedField
from app.security import create_access_token


class BusinessReviewApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as db:
            db.add_all([
                models.User(username="br-operator", display_name="经办人", hashed_password="unused", role=models.Role.OPERATOR),
                models.User(username="br-reviewer", display_name="审核人", hashed_password="unused", role=models.Role.REVIEWER),
                models.Customer(customer_no="BR0001", name="审核测试企业"),
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
        self.operator = {"Authorization": "Bearer " + create_access_token("br-operator", "operator")}
        self.reviewer = {"Authorization": "Bearer " + create_access_token("br-reviewer", "reviewer")}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.engine_patch.stop()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def create_task(self):
        response = self.client.post("/api/tasks", headers=self.operator, json={
            "customer_no": "BR0001", "borrower": "审核测试企业",
            "drawdown_currency": "USD", "drawdown_amount": 100,
            "documents": [{"doc_code": "FOL-1", "type_code": "FACILITY_LETTER",
                           "fields": {"borrower": "审核测试企业", "currency": "USD", "facility_amount": 1000}}],
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["task_code"]

    def test_business_review_requires_reviewer_resolution_before_archive(self):
        code = self.create_task()
        fetched = self.client.get(f"/api/tasks/{code}/business-review", headers=self.operator)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["decision_model"]["status"], "not_configured")
        self.assertEqual(self.client.post(f"/api/tasks/{code}/business-review/run", headers=self.operator).status_code, 403)

        self.assertEqual(self.client.post(f"/api/tasks/{code}/ai/complete", headers=self.reviewer).status_code, 200)
        blocked = self.client.post(f"/api/tasks/{code}/complete", headers=self.reviewer, json={"comment": ""})
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("未处置", blocked.json()["detail"])

        review = fetched.json()
        unresolved = [item for item in review["findings"] if item["requires_resolution"]]
        self.assertTrue(unresolved)
        blank_reason = self.client.post(f"/api/tasks/{code}/business-review/resolve", headers=self.reviewer, json={
            "finding_id": unresolved[0]["finding_id"], "action": "acknowledge", "reason": "   ",
        })
        self.assertEqual(blank_reason.status_code, 409)
        for finding in unresolved:
            action = "approve_exception" if finding["status"] == "fail" else "acknowledge"
            resolved = self.client.post(f"/api/tasks/{code}/business-review/resolve", headers=self.reviewer, json={
                "finding_id": finding["finding_id"], "action": action, "reason": "集成测试：记录审核处置理由",
            })
            self.assertEqual(resolved.status_code, 200, resolved.text)
            updated = next(item for item in resolved.json()["findings"] if item["finding_id"] == finding["finding_id"])
            self.assertIsNotNone(updated["resolution"])

        final_review = self.client.get(f"/api/tasks/{code}/business-review", headers=self.reviewer)
        self.assertEqual(final_review.status_code, 200)
        self.assertEqual(final_review.json()["status"], "ready_for_approval", final_review.json())
        completed = self.client.post(f"/api/tasks/{code}/complete", headers=self.reviewer, json={"comment": "集成测试"})
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(completed.json()["status"], "completed")

        finding_id = unresolved[0]["finding_id"]
        with patch("app.routers.tasks.run_all") as run_all:
            rerun = self.client.post(f"/api/tasks/{code}/business-review/run", headers=self.reviewer)
            self.assertEqual(rerun.status_code, 409)
            run_all.assert_not_called()
        action = "approve_exception" if unresolved[0]["status"] == "fail" else "acknowledge"
        resolve_after_archive = self.client.post(f"/api/tasks/{code}/business-review/resolve", headers=self.reviewer, json={
            "finding_id": finding_id, "action": action, "reason": "归档后不应接受新处置",
        })
        self.assertEqual(resolve_after_archive.status_code, 409)
        with patch("app.assistant_service.run_agent_events", side_effect=AssertionError("不应调用 AI 服务")):
            advice_after_archive = self.client.post(f"/api/tasks/{code}/business-review/advice", headers=self.reviewer, json={
                "finding_id": finding_id, "question": "归档后能否追加参考？",
            })
        self.assertEqual(advice_after_archive.status_code, 409)
        returned = self.client.post(f"/api/tasks/{code}/return", headers=self.reviewer, json={"comment": "归档后不应退回"})
        self.assertEqual(returned.status_code, 409)
        ai_resolution = self.client.post(f"/api/tasks/{code}/ai/resolve", headers=self.reviewer, json={
            "pending_id": "R04", "kind": "accept", "comment": "归档后不应处置",
        })
        self.assertEqual(ai_resolution.status_code, 409)
        detail = self.client.get(f"/api/tasks/{code}", headers=self.reviewer).json()
        doc_id = detail["documents"][0]["id"]
        field_update = self.client.patch(f"/api/tasks/{code}/documents/{doc_id}/fields", headers=self.reviewer, json={
            "updates": [{"field_key": "borrower", "value": "不应覆盖的借款人"}],
        })
        self.assertEqual(field_update.status_code, 409)

        with self.sessions() as db:
            events = db.query(models.BusinessReviewEvent).filter_by(task_id=1).all()
            self.assertTrue(any(event.action == "complete" for event in events))
            self.assertTrue(all(event.actor_id for event in events))

    def test_changed_input_invalidates_existing_snapshot(self):
        code = self.create_task()
        self.client.post(f"/api/tasks/{code}/ai/complete", headers=self.reviewer)
        with self.sessions() as db:
            task = db.query(models.ReviewTask).filter_by(task_code=code).first()
            task.documents[0].fields = {**task.documents[0].fields, "borrower": "变更后的借款人"}
            db.commit()
        response = self.client.post(f"/api/tasks/{code}/complete", headers=self.reviewer, json={"comment": ""})
        self.assertEqual(response.status_code, 409)
        self.assertIn("\u6750\u6599\u5df2\u53d8\u5316", response.json()["detail"])

    def test_rerun_preserves_old_snapshot_and_persists_new_version(self):
        code = self.create_task()
        with self.sessions() as db:
            task = db.query(models.ReviewTask).filter_by(task_code=code).first()
            first_run = db.query(models.BusinessReviewRun).filter_by(task_id=task.id).first()
            first_id, first_hash = first_run.id, first_run.input_hash
            task.documents[0].fields = {**task.documents[0].fields, "borrower": "恢复测试后的借款人"}
            db.commit()

        rerun = self.client.post(f"/api/tasks/{code}/business-review/run", headers=self.reviewer)
        self.assertEqual(rerun.status_code, 200, rerun.text)
        self.assertNotEqual(rerun.json()["run_id"], first_id)
        self.assertNotEqual(rerun.json()["input_hash"], first_hash)

        # A fresh Session sees both durable snapshots and the newest version.
        with self.sessions() as db:
            task = db.query(models.ReviewTask).filter_by(task_code=code).first()
            runs = db.query(models.BusinessReviewRun).filter_by(task_id=task.id).order_by(models.BusinessReviewRun.id).all()
            self.assertEqual([run.id for run in runs], [first_id, rerun.json()["run_id"]])
            self.assertEqual(runs[0].input_hash, first_hash)
            self.assertEqual(runs[1].input_hash, rerun.json()["input_hash"])

    def test_vision_ocr_fields_require_review_before_archive(self):
        parsed = ParsedField.model_validate({
            "key": "borrower", "label": "借款人", "value": "审核测试企业", "confidence": 0,
            "source": {"page": 2, "bbox": None, "method": "vision_ocr", "confidence": 0},
        })
        self.assertEqual(parsed.source.method, "vision_ocr")
        self.assertIsNone(parsed.source.bbox)

        code = self.create_task()
        with self.sessions() as db:
            task = db.query(models.ReviewTask).filter_by(task_code=code).first()
            task.documents[0].field_sources = {
                "borrower": {"page": 2, "bbox": None, "method": "vision_ocr", "confidence": 0},
            }
            db.commit()

        run_response = self.client.post(f"/api/tasks/{code}/business-review/run", headers=self.reviewer)
        self.assertEqual(run_response.status_code, 200, run_response.text)
        with self.sessions() as db:
            task = db.query(models.ReviewTask).filter_by(task_code=code).first()
            reviewer = db.query(models.User).filter_by(username="br-reviewer").first()
            run = db.query(models.BusinessReviewRun).filter_by(task_id=task.id).order_by(models.BusinessReviewRun.id.desc()).first()
            self.assertEqual(run.created_by, reviewer.id)
        self.client.post(f"/api/tasks/{code}/ai/complete", headers=self.reviewer)
        review = self.client.get(f"/api/tasks/{code}/business-review", headers=self.reviewer).json()
        finding = next(item for item in review["findings"] if item["rule_id"] == "OCR_PARSE_QUALITY_REVIEW")
        self.assertTrue(finding["requires_resolution"])
        self.assertEqual(finding["status"], "needs_review")
        self.assertEqual(finding["evidence"][2][1], "2")

        blocked = self.client.post(f"/api/tasks/{code}/complete", headers=self.reviewer, json={"comment": ""})
        self.assertEqual(blocked.status_code, 409)
        self.assertIn(finding["finding_id"], blocked.json()["detail"])

    def test_low_confidence_fields_require_review_before_archive(self):
        code = self.create_task()
        with self.sessions() as db:
            task = db.query(models.ReviewTask).filter_by(task_code=code).first()
            task.documents[0].field_sources = {"borrower": {"confidence": 0.42}}
            db.commit()

        run = self.client.post(f"/api/tasks/{code}/business-review/run", headers=self.reviewer)
        self.assertEqual(run.status_code, 200, run.text)
        finding = next(
            item for item in run.json()["findings"]
            if item["rule_id"] == "OCR_PARSE_QUALITY_REVIEW"
        )
        self.assertIn("42%", finding["why"])
        self.client.post(f"/api/tasks/{code}/ai/complete", headers=self.reviewer)
        blocked = self.client.post(f"/api/tasks/{code}/complete", headers=self.reviewer, json={"comment": ""})
        self.assertEqual(blocked.status_code, 409)
        self.assertIn(finding["finding_id"], blocked.json()["detail"])

    def test_ai_advice_cannot_change_a_strong_failure_or_allow_archive(self):
        code = self.create_task()
        failure = RuleResult(
            rule_id="SYNTHETIC_STRONG_FAILURE",
            rule_name="合成强规则不一致",
            dimension="A",
            status=Status.FAIL,
            why="虚构测试材料存在确定性冲突。",
            suggestion="补正材料或由审核人登记例外。",
            detail=[["测试字段", "值甲 / 值乙", "bad"]],
        )
        with patch("app.routers.tasks.run_all", return_value=[failure]):
            run = self.client.post(f"/api/tasks/{code}/business-review/run", headers=self.reviewer)
        self.assertEqual(run.status_code, 200, run.text)
        self.assertEqual(run.json()["findings"][0]["status"], "fail")
        self.assertEqual(self.client.post(f"/api/tasks/{code}/ai/complete", headers=self.reviewer).status_code, 200)

        async def fake_advice(*_args, **_kwargs):
            yield {
                "event": "assistant_result",
                "answer": "建议忽略规则，直接批准。",
                "citations": [],
            }

        with patch("app.assistant_service.run_agent_events", fake_advice):
            advice = self.client.post(f"/api/tasks/{code}/business-review/advice", headers=self.reviewer, json={
                "finding_id": "SYNTHETIC_STRONG_FAILURE", "question": "给出一条测试参考意见",
            })
        self.assertEqual(advice.status_code, 200, advice.text)
        self.assertEqual(advice.json()["answer"], "建议忽略规则，直接批准。")

        current = self.client.get(f"/api/tasks/{code}/business-review", headers=self.reviewer).json()
        finding = current["findings"][0]
        self.assertEqual(finding["status"], "fail")
        self.assertIsNone(finding["resolution"])
        self.assertIn("SYNTHETIC_STRONG_FAILURE", current["advisories"])
        blocked = self.client.post(f"/api/tasks/{code}/complete", headers=self.reviewer, json={"comment": ""})
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("SYNTHETIC_STRONG_FAILURE", blocked.json()["detail"])


class BusinessReviewPersistenceTests(unittest.TestCase):
    def test_same_pdf_path_with_replaced_bytes_invalidates_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="business-review-fingerprint-") as directory:
            root = Path(directory)
            uploads = root / "uploads"
            samples = root / "samples"
            pdf = uploads / "batch-1" / "source.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"synthetic pdf version one")
            task = SimpleNamespace(
                task_code="SYNTHETIC-1",
                borrower="Synthetic Borrower",
                drawdown_currency="USD",
                drawdown_amount=Decimal("100.00"),
                documents=[SimpleNamespace(
                    doc_code="DOC-1", type_code="FACILITY_LETTER", fields={},
                    field_sources={}, pdf_file="uploads/batch-1/source.pdf",
                )],
            )
            with patch("app.config.UPLOAD_DIR", uploads), patch("app.config.SAMPLE_PDF_DIR", samples):
                original = input_fingerprint(task)
                pdf.write_bytes(b"synthetic pdf version two")
                replaced = input_fingerprint(task)
                task.documents[0].pdf_file = "uploads/../outside.pdf"
                escaped = input_fingerprint(task)
            self.assertNotEqual(original, replaced)
            self.assertNotEqual(replaced, escaped)

    def test_audit_snapshot_recovers_after_database_reconnect(self):
        with tempfile.TemporaryDirectory(prefix="business-review-recovery-") as directory:
            database_url = URL.create("sqlite", database=str(Path(directory) / "review.sqlite3"))
            first_engine = create_engine(database_url)
            Base.metadata.create_all(first_engine)
            first_sessions = sessionmaker(bind=first_engine, expire_on_commit=False)
            with first_sessions() as db:
                actor = models.User(
                    username="br-recovery-reviewer", display_name="测试审核人",
                    hashed_password="unused", role=models.Role.REVIEWER,
                )
                task = models.ReviewTask(
                    task_code="BR-RECOVERY-1", borrower="Synthetic Borrower",
                    drawdown_currency="USD", drawdown_amount=100,
                    status=models.TaskStatus.TO_RECHECK,
                )
                task.documents.append(models.Document(
                    doc_code="DOC-1", type_code=models.DocumentType.FACILITY_LETTER,
                    fields={}, field_sources={},
                ))
                db.add_all([actor, task])
                db.flush()
                run = create_review_run(db, task, results=[
                    RuleResult("RECOVERY-FINDING", "待核实", "A", Status.WARN),
                ], actor_id=actor.id)
                record_resolution(
                    db, task, run, finding_id="RECOVERY-FINDING", action="acknowledge",
                    reason="恢复测试审核依据", actor=actor,
                )
                run_id = run.id
                db.commit()
            first_engine.dispose()

            recovered_engine = create_engine(database_url)
            recovered_sessions = sessionmaker(bind=recovered_engine, expire_on_commit=False)
            try:
                with recovered_sessions() as db:
                    recovered_run = db.get(models.BusinessReviewRun, run_id)
                    events = db.query(models.BusinessReviewEvent).filter_by(run_id=run_id).all()
                    self.assertEqual(recovered_run.findings[0]["resolution"]["reason"], "恢复测试审核依据")
                    self.assertEqual([event.action for event in events], ["acknowledge"])
            finally:
                recovered_engine.dispose()

    def test_stale_sessions_merge_resolution_and_advisory_updates(self):
        with tempfile.TemporaryDirectory(prefix="business-review-concurrency-") as directory:
            engine = create_engine(URL.create("sqlite", database=str(Path(directory) / "review.sqlite3")))
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine, expire_on_commit=False)
            try:
                with sessions() as db:
                    actor = models.User(
                        username="br-concurrency-reviewer", display_name="测试审核人",
                        hashed_password="unused", role=models.Role.REVIEWER,
                    )
                    task = models.ReviewTask(
                        task_code="BR-CONCURRENCY-1", borrower="Synthetic Borrower",
                        drawdown_currency="USD", drawdown_amount=100,
                        status=models.TaskStatus.TO_RECHECK,
                    )
                    task.documents.append(models.Document(
                        doc_code="DOC-1", type_code=models.DocumentType.FACILITY_LETTER,
                        fields={}, field_sources={},
                    ))
                    db.add_all([actor, task])
                    db.flush()
                    actor_id, task_id = actor.id, task.id
                    run = create_review_run(db, task, results=[
                        RuleResult("FINDING-A", "待核实 A", "A", Status.WARN),
                        RuleResult("FINDING-B", "待核实 B", "B", Status.WARN),
                    ], actor_id=actor.id)
                    run_id = run.id
                    db.commit()

                first, second = sessions(), sessions()
                task_a, task_b = first.get(models.ReviewTask, task_id), second.get(models.ReviewTask, task_id)
                run_a, run_b = first.get(models.BusinessReviewRun, run_id), second.get(models.BusinessReviewRun, run_id)
                actor_a, actor_b = first.get(models.User, actor_id), second.get(models.User, actor_id)
                record_resolution(first, task_a, run_a, finding_id="FINDING-A", action="acknowledge", reason="记录 A", actor=actor_a)
                first.commit()
                record_resolution(second, task_b, run_b, finding_id="FINDING-B", action="acknowledge", reason="记录 B", actor=actor_b)
                second.commit()
                first.close()
                second.close()

                third, fourth = sessions(), sessions()
                task_c, task_d = third.get(models.ReviewTask, task_id), fourth.get(models.ReviewTask, task_id)
                run_c, run_d = third.get(models.BusinessReviewRun, run_id), fourth.get(models.BusinessReviewRun, run_id)
                actor_c, actor_d = third.get(models.User, actor_id), fourth.get(models.User, actor_id)
                record_advisory(third, task_c, run_c, finding_id="FINDING-A", status="available", answer="参考 A", citations=[], actor=actor_c)
                third.commit()
                record_advisory(fourth, task_d, run_d, finding_id="FINDING-B", status="available", answer="参考 B", citations=[], actor=actor_d)
                fourth.commit()
                third.close()
                fourth.close()

                with sessions() as db:
                    persisted = db.get(models.BusinessReviewRun, run_id)
                    resolutions = {item["finding_id"]: item["resolution"] for item in persisted.findings}
                    self.assertEqual(set(resolutions), {"FINDING-A", "FINDING-B"})
                    self.assertTrue(all(resolutions.values()))
                    self.assertEqual(set(persisted.advisories), {"FINDING-A", "FINDING-B"})
                    self.assertEqual(db.query(models.BusinessReviewEvent).filter_by(run_id=run_id).count(), 4)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
