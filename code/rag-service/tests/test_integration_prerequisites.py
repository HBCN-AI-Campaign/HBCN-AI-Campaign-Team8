import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from postgres_test_prereqs import validated_test_url


class PostgresIntegrationPrerequisiteTests(unittest.TestCase):
    def test_accepts_only_loopback_disposable_test_database(self):
        url = validated_test_url(
            "postgresql+psycopg://user:password@127.0.0.1:5432/hbcn_rag_test?sslmode=disable"
        )
        self.assertEqual(url.database, "hbcn_rag_test")

    def test_refuses_remote_shared_wrong_database_and_non_postgres_targets(self):
        urls = (
            "postgresql+psycopg://user:password@db.internal:5432/hbcn_rag_test?sslmode=disable",
            "postgresql+psycopg://user:password@127.0.0.1:5432/postgres?sslmode=disable",
            "postgresql+psycopg://user:password@127.0.0.1:5432/hbcn_rag_test?sslmode=require",
            "sqlite:///hbcn_rag_test.db",
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validated_test_url(url)

    def test_requires_a_database_url(self):
        with self.assertRaises(ValueError):
            validated_test_url("")

    def test_invalid_connection_string_error_does_not_echo_secrets(self):
        with self.assertRaisesRegex(ValueError, "connection details suppressed") as caught:
            validated_test_url("NOT-A-DSN?password=SENSITIVE-DSN-PASSWORD")
        self.assertNotIn("SENSITIVE-DSN-PASSWORD", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
