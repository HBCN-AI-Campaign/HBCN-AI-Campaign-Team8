import unittest

from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.main import require_service_token, trial_ui


def request_from(host):
    return Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/ui/",
        "raw_path": b"/ui/",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": (host, 54321),
        "server": ("127.0.0.1", 8010),
    })


class UISessionTests(unittest.TestCase):
    def setUp(self):
        self.original_token = settings.SERVICE_TOKEN
        settings.SERVICE_TOKEN = "unit-test-secret"

    def tearDown(self):
        settings.SERVICE_TOKEN = self.original_token

    def test_local_ui_issues_http_only_cookie_without_exposing_token(self):
        response = trial_ui(request_from("127.0.0.1"))

        cookie = response.headers["set-cookie"]
        self.assertIn("rag_ui_session=unit-test-secret", cookie)
        self.assertIn("httponly", cookie.lower())
        self.assertIn("samesite=strict", cookie.lower())
        self.assertNotIn(b"unit-test-secret", response.body)
        self.assertNotIn(b"SERVICE_TOKEN", response.body)

    def test_remote_clients_cannot_open_local_ui(self):
        with self.assertRaises(HTTPException) as raised:
            trial_ui(request_from("192.0.2.10"))
        self.assertEqual(raised.exception.status_code, 404)

    def test_ui_cookie_authenticates_api_but_invalid_token_does_not(self):
        require_service_token(authorization=None, rag_ui_session="unit-test-secret")
        with self.assertRaises(HTTPException) as raised:
            require_service_token(authorization=None, rag_ui_session="wrong")
        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
