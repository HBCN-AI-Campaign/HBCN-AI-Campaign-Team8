import time
import unittest
from http.cookies import SimpleCookie
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.main import UI_SESSION_COOKIE, _ui_session_signature, require_service_token, trial_ui


def request_from(host, origin=None):
    headers = [(b"host", b"127.0.0.1:8010")]
    if origin:
        headers.append((b"origin", origin.encode()))
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
        "headers": headers,
        "client": (host, 54321),
        "server": ("127.0.0.1", 8010),
    })


class UISessionTests(unittest.TestCase):
    def setUp(self):
        self.original_token = settings.SERVICE_TOKEN
        settings.SERVICE_TOKEN = "unit-test-secret"

    def tearDown(self):
        settings.SERVICE_TOKEN = self.original_token

    def test_local_ui_issues_short_lived_http_only_cookie_without_exposing_token(self):
        response = trial_ui(request_from("127.0.0.1"))

        cookie = SimpleCookie()
        cookie.load(response.headers["set-cookie"])
        session = cookie[UI_SESSION_COOKIE]
        self.assertTrue(session["httponly"])
        self.assertEqual(session["samesite"], "strict")
        self.assertEqual(session["path"], "/api/v1")
        self.assertEqual(session["max-age"], "28800")
        body = Path(response.path).read_bytes() if hasattr(response, "path") else response.body
        self.assertNotIn(b"unit-test-secret", body)
        self.assertNotIn(b"SERVICE_TOKEN", body)

    def test_remote_clients_cannot_open_local_ui(self):
        with self.assertRaises(HTTPException) as raised:
            trial_ui(request_from("192.0.2.10"))
        self.assertEqual(raised.exception.status_code, 404)

    def test_local_same_origin_session_authenticates_api_without_bearer_header(self):
        issued_at = str(int(time.time()))
        payload = f"{issued_at}.test-session"
        session = f"{payload}.{_ui_session_signature(payload)}"

        require_service_token(
            request_from("127.0.0.1", "http://127.0.0.1:8010"),
            authorization=None,
            rag_ui_session=session,
        )

    def test_session_rejects_remote_or_cross_origin_requests(self):
        issued_at = str(int(time.time()))
        payload = f"{issued_at}.test-session"
        session = f"{payload}.{_ui_session_signature(payload)}"
        for request in (
            request_from("192.0.2.10", "http://127.0.0.1:8010"),
            request_from("127.0.0.1", "http://attacker.invalid"),
        ):
            with self.subTest(client=request.client.host, origin=request.headers.get("origin")):
                with self.assertRaises(HTTPException) as raised:
                    require_service_token(request, authorization=None, rag_ui_session=session)
                self.assertEqual(raised.exception.status_code, 401)

    def test_expired_session_is_rejected_but_bearer_api_access_remains(self):
        issued_at = str(int(time.time()) - 8 * 60 * 60 - 1)
        payload = f"{issued_at}.test-session"
        expired_session = f"{payload}.{_ui_session_signature(payload)}"
        with self.assertRaises(HTTPException) as raised:
            require_service_token(
                request_from("127.0.0.1", "http://127.0.0.1:8010"),
                authorization=None,
                rag_ui_session=expired_session,
            )
        self.assertEqual(raised.exception.status_code, 401)

        require_service_token(
            request_from("192.0.2.10"),
            authorization="Bearer unit-test-secret",
            rag_ui_session=None,
        )


if __name__ == "__main__":
    unittest.main()
