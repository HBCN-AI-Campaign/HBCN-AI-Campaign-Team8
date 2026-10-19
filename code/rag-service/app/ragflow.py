from typing import Any
import time

import httpx

from .config import settings


class RAGFlowError(RuntimeError):
    pass


class RAGFlowNotConfiguredError(RAGFlowError):
    pass


DATASET_SETTINGS = {
    "business_rules": "RAGFLOW_BUSINESS_RULES_DATASET_ID",
    "project_design": "RAGFLOW_PROJECT_DESIGN_DATASET_ID",
}

DATASET_NAME_SETTINGS = {
    "business_rules": "RAGFLOW_BUSINESS_RULES_DATASET_NAME",
    "project_design": "RAGFLOW_PROJECT_DESIGN_DATASET_NAME",
}


class RAGFlowClient:
    def __init__(self) -> None:
        self.base_url = settings.RAGFLOW_BASE_URL.rstrip("/")
        self.headers = {"Authorization": f"Bearer {settings.RAGFLOW_API_KEY}"}

    def _require_connection(self) -> None:
        if not self.base_url or not settings.RAGFLOW_API_KEY:
            raise RAGFlowNotConfiguredError("RAGFLOW_BASE_URL 或 RAGFLOW_API_KEY 尚未配置")

    def dataset_id(self, scope: str) -> str:
        setting_name = DATASET_SETTINGS.get(scope)
        dataset_id = getattr(settings, setting_name, "") if setting_name else ""
        if not self.base_url or not settings.RAGFLOW_API_KEY:
            raise RAGFlowNotConfiguredError(f"RAGFlow 或 {scope} 知识库尚未配置")
        if dataset_id:
            return dataset_id
        name_setting = DATASET_NAME_SETTINGS.get(scope)
        dataset_name = getattr(settings, name_setting, "") if name_setting else ""
        matches = self.list_datasets(name=dataset_name)
        if matches and matches[0].get("id"):
            return str(matches[0]["id"])
        raise RAGFlowNotConfiguredError(f"RAGFlow 知识库 {dataset_name} 尚未初始化")

    def list_datasets(self, *, name: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"page": 1, "page_size": 100}
        if name:
            params["name"] = name
        data = self._request("GET", "/api/v1/datasets", params=params)
        result = data.get("data", [])
        return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    def create_dataset(self, *, name: str, description: str) -> str:
        data = self._request(
            "POST",
            "/api/v1/datasets",
            payload={
                "name": name,
                "description": description,
                "language": settings.RAGFLOW_LANGUAGE,
                "parser_id": settings.RAGFLOW_PARSER_ID,
                "permission": "me",
            },
        )
        result = data.get("data", {})
        dataset_id = result.get("id") if isinstance(result, dict) else None
        if not dataset_id:
            raise RAGFlowError("RAGFlow 创建知识库后未返回 dataset id")
        return str(dataset_id)

    def ensure_dataset(self, *, scope: str, description: str) -> str:
        self._require_connection()
        configured = getattr(settings, DATASET_SETTINGS[scope])
        if configured:
            return configured
        name = getattr(settings, DATASET_NAME_SETTINGS[scope])
        matches = self.list_datasets(name=name)
        if matches and matches[0].get("id"):
            return str(matches[0]["id"])
        return self.create_dataset(name=name, description=description)

    def retrieve(self, *, query: str, scope: str, top_k: int) -> list[dict[str, Any]]:
        dataset_id = self.dataset_id(scope)
        response_data = self._request(
            "POST",
            "/api/v1/retrieval",
            payload={
                "question": query,
                "dataset_ids": [dataset_id],
                "knn_top_k": top_k,
                "keyword": True,
                "keywords_similarity_weight": 0.7,
                "similarity_threshold": 0.2,
                "highlight": True,
                "page": 1,
                "page_size": top_k,
            },
        )
        data = response_data.get("data", {})
        chunks = data.get("chunks", []) if isinstance(data, dict) else []
        return [chunk for chunk in chunks if isinstance(chunk, dict)]

    def upload(
        self,
        *,
        scope: str,
        filename: str,
        content: bytes,
        content_type: str,
        dataset_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> list[str]:
        self._require_connection()
        dataset_id = dataset_id or self.dataset_id(scope)
        try:
            response = httpx.post(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/documents",
                files={"file": (filename, content, content_type)},
                headers=self.headers,
                timeout=settings.REQUEST_TIMEOUT_SECONDS,
            )
            data = self._decode(response)
            result = data.get("data", [])
            document_ids = (
                [item.get("id") for item in result if isinstance(item, dict) and item.get("id")]
                if isinstance(result, list)
                else []
            )
            if not document_ids:
                raise RAGFlowError("RAGFlow 未返回已上传的 document_ids")
            self._request(
                "POST",
                f"/api/v1/datasets/{dataset_id}/chunks",
                payload={"document_ids": document_ids},
            )
            if metadata:
                self.update_document_metadata(
                    dataset_id=dataset_id,
                    document_ids=[str(document_id) for document_id in document_ids],
                    metadata=metadata,
                )
            return [str(document_id) for document_id in document_ids]
        except httpx.HTTPError as exc:
            raise RAGFlowError(f"RAGFlow 上传失败：{exc}") from exc

    def update_document_metadata(
        self,
        *,
        dataset_id: str,
        document_ids: list[str],
        metadata: dict[str, str],
    ) -> None:
        self._request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/metadata/update",
            payload={
                "selector": {"document_ids": document_ids},
                "updates": [{"key": key, "value": value} for key, value in metadata.items()],
                "deletes": [],
            },
        )

    def list_documents(
        self,
        *,
        scope: str,
        run: str | None = None,
        dataset_id: str | None = None,
    ) -> list[dict[str, Any]]:
        dataset_id = dataset_id or self.dataset_id(scope)
        params: dict[str, Any] = {"page": 1, "page_size": 100}
        if run:
            params["run"] = run
        documents: list[dict[str, Any]] = []
        for page in range(1, 101):
            params["page"] = page
            data = self._request("GET", f"/api/v1/datasets/{dataset_id}/documents", params=params)
            result = data.get("data", {})
            batch = result.get("docs", []) if isinstance(result, dict) else []
            if not isinstance(batch, list) or not batch:
                break
            documents.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < params["page_size"]:
                break
        return documents

    def wait_for_documents(
        self,
        *,
        scope: str,
        document_ids: list[str],
        dataset_id: str | None = None,
    ) -> list[dict[str, Any]]:
        dataset_id = dataset_id or self.dataset_id(scope)
        deadline = time.monotonic() + settings.PARSE_POLL_TIMEOUT_SECONDS
        wanted = set(document_ids)
        while time.monotonic() < deadline:
            documents = [
                doc
                for doc in self.list_documents(scope=scope, dataset_id=dataset_id)
                if str(doc.get("id")) in wanted
            ]
            if documents and all(str(doc.get("run")) in {"3", "DONE"} for doc in documents):
                return documents
            if any(str(doc.get("run")) in {"4", "FAIL"} for doc in documents):
                raise RAGFlowError("RAGFlow 文档解析失败，请查看 RAGFlow 文档状态")
            time.sleep(settings.PARSE_POLL_INTERVAL_SECONDS)
        raise RAGFlowError("等待 RAGFlow 文档解析超时")

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            self._require_connection()
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                json=payload,
                params=params,
                headers={**self.headers, "Content-Type": "application/json"},
                timeout=settings.REQUEST_TIMEOUT_SECONDS,
            )
            return self._decode(response)
        except httpx.HTTPError as exc:
            raise RAGFlowError(f"RAGFlow 请求失败：{exc}") from exc

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RAGFlowError("RAGFlow 返回了无效 JSON") from exc
        if not isinstance(payload, dict) or payload.get("code") not in (None, 0):
            message = payload.get("message", "未知业务错误") if isinstance(payload, dict) else "响应格式错误"
            raise RAGFlowError(f"RAGFlow 返回错误：{message}")
        return payload
