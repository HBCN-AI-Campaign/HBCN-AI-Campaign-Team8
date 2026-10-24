"""Material set index: numbering, availability, path guards, and byte identity."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.business_review.material_sets import (
    MATERIAL_SETS,
    MaterialSetError,
    describe_documents,
    describe_set,
    material_set,
    normalize_case_code,
    resolve_document,
    resolve_root,
    set_documents,
)
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.security import create_access_token

FOLDER_NAME = "第八套材料（编造完）（客户&供应商名称更改）"
REAL_FILENAMES = [
    "FOL-编造完.pdf",
    "商业合同 - 编造完.pdf",
    "形式发票 - 编造完.pdf",
    "报关单 - 编造完.pdf",
    "提款指令 - 编造完.pdf",
    "支付指令 - 编造完.pdf",
    "运单 - 编造完.pdf",
]


def make_directory_link(link: Path, target: Path) -> bool:
    """Create a real directory link, so the traversal guard is exercised and not mocked."""
    commands = (
        ["powershell.exe", "-NoProfile", "-Command",
         f"New-Item -ItemType Junction -Path '{link}' -Target '{target}'"],
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
    )
    for command in commands:
        try:
            completed = subprocess.run(command, capture_output=True, text=True)
        except OSError:
            continue
        if completed.returncode == 0 and link.exists():
            return True
    return False


def build_set(root: Path, folder_name: str = FOLDER_NAME, filenames=None) -> Path:
    folder = root / folder_name
    folder.mkdir(parents=True)
    for index, name in enumerate(filenames or REAL_FILENAMES):
        (folder / name).write_bytes(f"%PDF-1.4 synthetic material {index}".encode())
    return folder


class CaseCodeTests(unittest.TestCase):
    def test_accepts_the_forms_an_operator_would_type(self):
        for raw in ("8", "08", "0008", "第8套", "第八套", "第八套材料", " 第 8 套 ", "case 8"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_case_code(raw), "0008")
        self.assertEqual(normalize_case_code("第九套材料"), "0009")
        self.assertEqual(normalize_case_code("第十套"), "0010")

    def test_rejects_unknown_and_malformed_input(self):
        for raw in ("", "   ", "12", "abc", "第11套", None, 8, [], "0"):
            with self.subTest(raw=raw):
                self.assertIsNone(normalize_case_code(raw))

    def test_every_indexed_code_is_reachable_by_its_own_number(self):
        for item in MATERIAL_SETS:
            with self.subTest(code=item.code):
                self.assertEqual(normalize_case_code(item.code), item.code)
                self.assertEqual(material_set(item.code), item)


class MaterialResolutionTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="material-sets-")
        self.root = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def test_unset_root_is_an_explicit_failure(self):
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", ""):
            with self.assertRaises(MaterialSetError):
                resolve_root()
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root / "missing")):
            with self.assertRaises(MaterialSetError):
                resolve_root()

    def test_reports_available_for_a_complete_set(self):
        build_set(self.root)
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            described = describe_set(resolve_root(), material_set("0008"))
        self.assertTrue(described["available"], described["reason"])
        self.assertEqual(described["document_count"], 7)
        self.assertEqual(len(described["document_types"]), 7)

    def test_never_returns_the_folder_path_or_root(self):
        build_set(self.root)
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            described = describe_set(resolve_root(), material_set("0008"))
        serialized = str(described)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn(FOLDER_NAME, serialized)

    def test_multiple_and_missing_folder_matches_are_refused(self):
        build_set(self.root)
        (self.root / "第八套材料备份").mkdir()
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            described = describe_set(resolve_root(), material_set("0008"))
        self.assertFalse(described["available"])
        self.assertIn("恰好一个", described["reason"])

    def test_wrong_document_count_is_refused(self):
        build_set(self.root, filenames=REAL_FILENAMES[:6])
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            described = describe_set(resolve_root(), material_set("0008"))
        self.assertFalse(described["available"])
        self.assertIn("实际 6 份", described["reason"])

    def test_unknown_document_type_is_refused_before_it_can_be_loaded(self):
        names = REAL_FILENAMES[:6] + ["未命名文件.pdf"]
        build_set(self.root, filenames=names)
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            described = describe_set(resolve_root(), material_set("0008"))
        self.assertFalse(described["available"])
        self.assertIn("无法推断单据类型", described["reason"])

    def test_index_outside_the_fresh_list_is_refused(self):
        build_set(self.root)
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            root = resolve_root()
            for index in (-1, 7, 99):
                with self.subTest(index=index):
                    with self.assertRaises(MaterialSetError):
                        resolve_document(root, material_set("0008"), index)
            self.assertEqual(resolve_document(root, material_set("0008"), 0).name, REAL_FILENAMES[0])

    def test_document_list_order_matches_the_download_index(self):
        build_set(self.root)
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            root = resolve_root()
            listed = describe_documents(root, material_set("0008"))
            for item in listed:
                resolved = resolve_document(root, material_set("0008"), item["index"])
                self.assertEqual(resolved.name, item["filename"])

    def test_a_link_pointing_outside_the_set_stops_the_load(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "外部运单.pdf").write_bytes(b"%PDF-1.4 outside")
        folder = build_set(self.root / "materials")
        if not make_directory_link(folder / "linked", outside):
            self.skipTest("this environment cannot create a directory link")
        # rglob follows the link, so the per-file containment re-check is what stops it.
        resolved_folder = folder.resolve()
        escaped = [path.name for path in folder.rglob("*.pdf")
                   if not path.resolve().is_relative_to(resolved_folder)]
        self.assertEqual(escaped, ["外部运单.pdf"])
        with self.assertRaises(MaterialSetError):
            set_documents(resolved_folder)


class MaterialApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as db:
            db.add_all([
                models.User(username="mat-operator", display_name="经办人", hashed_password="unused", role=models.Role.OPERATOR),
                models.User(username="mat-reviewer", display_name="审核人", hashed_password="unused", role=models.Role.REVIEWER),
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
        self.operator = {"Authorization": "Bearer " + create_access_token("mat-operator", "operator")}
        self.reviewer = {"Authorization": "Bearer " + create_access_token("mat-reviewer", "reviewer")}
        self._temp = tempfile.TemporaryDirectory(prefix="material-api-")
        self.root = Path(self._temp.name)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.engine_patch.stop()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self._temp.cleanup()

    def test_unconfigured_root_disables_the_feature_without_falling_back(self):
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", ""):
            listed = self.client.get("/api/materials/sets", headers=self.operator)
        self.assertEqual(listed.status_code, 200, listed.text)
        body = listed.json()
        self.assertFalse(body["configured"])
        self.assertTrue(all(not item["available"] for item in body["sets"]))
        self.assertTrue(all(item["reason"] for item in body["sets"]))

    def test_only_the_operator_may_read_materials(self):
        build_set(self.root)
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            self.assertEqual(self.client.get("/api/materials/sets", headers=self.reviewer).status_code, 403)
            self.assertEqual(
                self.client.get("/api/materials/sets/0008/documents", headers=self.reviewer).status_code, 403)
            self.assertEqual(self.client.get("/api/materials/sets", headers=self.operator).status_code, 200)

    def test_listing_reports_availability_for_all_three_sets(self):
        build_set(self.root)
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            listed = self.client.get("/api/materials/sets", headers=self.operator).json()
        by_code = {item["case_code"]: item for item in listed["sets"]}
        self.assertTrue(by_code["0008"]["available"], by_code["0008"]["reason"])
        self.assertFalse(by_code["0009"]["available"])
        self.assertEqual(by_code["0008"]["document_types"][0], "FACILITY_LETTER")

    def test_download_returns_the_original_bytes_so_the_hash_chain_holds(self):
        folder = build_set(self.root)
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            listed = self.client.get("/api/materials/sets/0008/documents", headers=self.operator).json()
            self.assertEqual([item["filename"] for item in listed["documents"]], REAL_FILENAMES)
            for item in listed["documents"]:
                response = self.client.get(
                    f"/api/materials/sets/0008/documents/{item['index']}", headers=self.operator)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.content, (folder / item["filename"]).read_bytes())
                self.assertEqual(response.headers["cache-control"], "private, no-store")
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                self.assertNotIn(str(self.root), str(dict(response.headers)))

    def test_unknown_code_and_out_of_range_index_are_not_found(self):
        build_set(self.root)
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            for path in ("/api/materials/sets/0012/documents", "/api/materials/sets/0008/documents/99",
                         "/api/materials/sets/0008/documents/-1"):
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path, headers=self.operator).status_code, 404)

    def test_an_incomplete_set_fails_its_listing_rather_than_loading_late(self):
        build_set(self.root, filenames=REAL_FILENAMES[:5])
        with patch.object(settings, "BUSINESS_MATERIALS_ROOT", str(self.root)):
            response = self.client.get("/api/materials/sets/0008/documents", headers=self.operator)
        self.assertEqual(response.status_code, 409)
        self.assertIn("实际 5 份", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()