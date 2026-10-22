"""Local operator bridge authorization; no database/model calls."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import settings
from app.main import app


class LocalQualityUITests(unittest.TestCase):
    def test_operator_bridge_requires_cookie_loopback_origin_role_scope_and_live_registry(self):
        with TemporaryDirectory() as folder:
            key = "synthetic-local-review-key-" + "k" * 40
            registry = Path(folder) / "principals.json"
            entry = {"subject": "synthetic-local-operator", "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
                "namespaces": ["business_rules"], "roles": ["reviewer"],
                "valid_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
            def save(**changes):
                registry.write_text(json.dumps({"principals": [{**entry, **changes}]}))
            save()
            row = {"id": "11111111-1111-1111-1111-111111111111", "scope": "business_rules", "state": "quality_review", "pages": []}
            engine = Mock()
            engine.documents.get.return_value = row
            engine.documents.public.side_effect = lambda value: value
            with patch.object(settings, "SERVICE_TOKEN", "synthetic-service"), \
                 patch.object(settings, "RAG_UI_DOCUMENT_REVIEW_KEY", SecretStr(key)), \
                 patch.object(settings, "RAG_DOCUMENT_REVIEW_PRINCIPALS_FILE", str(registry)), \
                 patch("app.main.engine_kind", return_value="postgres"), \
                 patch("app.backend_api.postgres_engine", return_value=engine):
                def address(host):
                    async def wrapped(scope, receive, send):
                        await app({**scope, "client": (host, 12345)}, receive, send)
                    return wrapped
                client = TestClient(address("127.0.0.1"), base_url="http://127.0.0.1")
                remote = TestClient(address("192.0.2.11"), base_url="http://127.0.0.1")
                path = f'/api/v1/documents/{row["id"]}/quality'
                bearer = {"Authorization": "Bearer synthetic-service"}
                try:
                    self.assertEqual(client.get(path, headers=bearer).status_code, 401)
                    self.assertEqual(client.get("/api/v1/capabilities", headers=bearer).json()["document_quality_review_scopes"], [])
                    client.get("/ui/")
                    response = client.get("/api/v1/capabilities")
                    self.assertEqual(response.json()["document_quality_review_scopes"], ["business_rules"])
                    self.assertNotIn(key, response.text)
                    self.assertEqual(client.get(path).status_code, 200)
                    self.assertEqual(client.get(path, headers={"Origin": "https://other.test"}).status_code, 401)
                    self.assertEqual(client.get(path, headers={"Sec-Fetch-Site": "cross-site"}).status_code, 401)
                    remote.cookies.update(client.cookies)
                    self.assertEqual(remote.get(path, headers=bearer).status_code, 401)
                    self.assertEqual(client.get(path, headers={"Host": "public.test"}).status_code, 401)
                    save(namespaces=["law"])
                    self.assertEqual(client.get(path).status_code, 403)
                    save(roles=["reader"])
                    self.assertEqual(client.get(path).status_code, 403)
                    save(valid_until="2020-01-01T00:00:00Z")
                    self.assertEqual(client.get(path).status_code, 401)
                    self.assertEqual(client.get("/api/v1/capabilities").json()["document_quality_review_scopes"], [])
                    save()
                    registry.unlink()
                    self.assertEqual(client.get(path).status_code, 503)
                finally:
                    client.close(); remote.close()
