"""Bounded upstream batch: ordering, budget and cross-thread cancellation."""
import threading
import unittest
from unittest.mock import Mock, patch

from app.answer_graph import build_answer_graph
from app.config import settings
from app.graph_transport import GraphRun
from app.request_control import current_control
from test_query_retrieval import encoded_plan, assess, evidence


class ParallelRetrievalTests(unittest.TestCase):
    query = "支付指令金额不符如何处理？"
    variants = [("金额差错核对流程", "general"), ("payment amount discrepancy", "translated")]

    def runtime(self):
        return Mock(complete=Mock(side_effect=[encoded_plan(*self.variants), assess(selected=[1, 2, 3])]))

    def state(self):
        return {"query": self.query, "scope": "business_rules", "top_k": 5}

    def test_parallel_completion_keeps_serial_fusion_and_query_budget(self):
        entered, release = threading.Event(), threading.Event()
        active, maximum = 0, 0
        lock = threading.Lock()
        expected = [self.query, *[text for text, _ in self.variants]]

        def retrieve(*, query, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                if active == 2:
                    entered.set()
            try:
                if query == self.query:
                    if not entered.wait(5):
                        raise AssertionError("queries were serialized")
                    if not release.wait(5):
                        raise AssertionError("second query never completed")
                else:
                    release.set()
                return [evidence(str(expected.index(query)), "金额核对 " + query)]
            finally:
                with lock:
                    active -= 1

        with patch.object(settings, "RAG_RETRIEVAL_CONCURRENCY", 2):
            parallel = build_answer_graph(Mock(retrieve=Mock(side_effect=retrieve)), self.runtime(), generate_answer=False).invoke(self.state())["result"]
        self.assertEqual(maximum, 2)
        serial_engine = Mock(retrieve=Mock(side_effect=lambda query, **kwargs: [evidence(str(expected.index(query)), "金额核对 " + query)]))
        with patch.object(settings, "RAG_RETRIEVAL_CONCURRENCY", 1):
            serial = build_answer_graph(serial_engine, self.runtime(), generate_answer=False).invoke(self.state())["result"]
        self.assertEqual(parallel, serial)
        limited = Mock(retrieve=Mock(return_value=[]))
        runtime = Mock(complete=Mock(side_effect=[encoded_plan(*self.variants), assess()]))
        with patch.object(settings, "RAG_MAX_RETRIEVAL_QUERIES", 1):
            build_answer_graph(limited, runtime).invoke(self.state())
        self.assertEqual(limited.retrieve.call_count, 1)
        self.assertEqual(limited.retrieve.call_args.kwargs["query"], self.query)

    def test_cancellation_reaches_workers_skips_queued_queries_and_keeps_capacity_until_cleanup(self):
        entered, release = threading.Event(), threading.Event()
        lock = threading.Lock()
        controls = []
        engine, runtime = Mock(), self.runtime()

        def retrieve(**kwargs):
            with lock:
                controls.append(current_control.get())
                if len(controls) == 2:
                    entered.set()
            if not release.wait(5):
                raise AssertionError("test cleanup did not release database")
            return []

        engine.retrieve.side_effect = retrieve
        slots = threading.BoundedSemaphore(1)
        slots.acquire()
        with patch.object(settings, "RAG_RETRIEVAL_CONCURRENCY", 2):
            run = GraphRun(build_answer_graph(engine, runtime), self.state(), slots)
            try:
                self.assertTrue(entered.wait(5))
                self.assertTrue(all(control is run.control for control in controls))
                run.cancel()
                self.assertFalse(slots.acquire(False), "capacity released while workers still active")
                release.set()
                self.assertTrue(run.done.wait(5))
            finally:
                run.cancel(); release.set(); run.worker.join(5)
        self.assertEqual(engine.retrieve.call_count, 2, "queued third query started after cancel")
        self.assertEqual(runtime.complete.call_count, 1, "assessment started after cancel")
        self.assertTrue(run.queue.empty())
        self.assertTrue(slots.acquire(False))
        slots.release()

    def test_dependency_failure_never_publishes_sufficiency(self):
        runtime = self.runtime()
        engine = Mock(retrieve=Mock(side_effect=RuntimeError("synthetic dependency failure")))
        with patch.object(settings, "RAG_RETRIEVAL_CONCURRENCY", 1), self.assertRaises(RuntimeError):
            build_answer_graph(engine, runtime, generate_answer=False).invoke(self.state())
        self.assertEqual(runtime.complete.call_count, 1)
        self.assertEqual(engine.retrieve.call_count, 1, "queued I/O continued after a dependency failure")

    def test_total_deadline_stops_queued_io_and_model_assessment(self):
        clock = [100.0]
        runtime = self.runtime()

        def retrieve(**kwargs):
            clock[0] += settings.RAG_TOTAL_TIMEOUT_SECONDS + 1
            return []

        engine = Mock(retrieve=Mock(side_effect=retrieve))
        with patch.object(settings, "RAG_RETRIEVAL_CONCURRENCY", 1), patch("app.answer_graph.time.monotonic", side_effect=lambda: clock[0]):
            result = build_answer_graph(engine, runtime, generate_answer=False).invoke(self.state())["result"]
        self.assertEqual(engine.retrieve.call_count, 1)
        self.assertEqual(runtime.complete.call_count, 1)
        self.assertEqual(result["stop_reason"], "time_budget")
        self.assertNotEqual(result["evidence_status"], "sufficient")
