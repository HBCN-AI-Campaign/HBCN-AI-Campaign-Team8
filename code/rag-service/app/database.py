from __future__ import annotations

import atexit
import base64
import hashlib
import re
import select
import socketserver
import threading
from functools import lru_cache
from pathlib import Path

import paramiko
from sqlalchemy import URL, create_engine
from sqlalchemy.engine import make_url

from .config import settings


class ResourceError(RuntimeError):
    pass


def resource_fields(filename: str) -> dict[str, str]:
    content = Path(filename).read_text(encoding="utf-8-sig")
    return {
        key.strip(): value.strip().strip("\"'")
        for key, value in re.findall(r"(?m)^([^\n:=：]+)[:=：]\s*(.*)$", content)
    }


class PinnedHostKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if not settings.RAG_SSH_HOST_KEY_SHA256 or fingerprint != settings.RAG_SSH_HOST_KEY_SHA256:
            raise ResourceError("ECS 主机指纹未配置或不匹配，已拒绝连接")
        client.get_host_keys().add(hostname, key.get_name(), key)


class PrivateDatabaseTunnel:
    def __init__(self, destination: tuple[str, int]):
        fields = resource_fields(settings.RAG_SSH_RESOURCE_FILE)
        self.fields = fields
        self.destination = destination
        self.lock = threading.Lock()
        self.client: paramiko.SSHClient | None = None
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                channel = None
                try:
                    channel = owner.transport().open_channel("direct-tcpip", owner.destination, self.client_address, timeout=10)
                    if channel is None:
                        return
                    while not owner.stopped.is_set():
                        ready, _, _ = select.select([self.request, channel], [], [], 1)
                        if self.request in ready:
                            data = self.request.recv(65536)
                            if not data:
                                break
                            channel.sendall(data)
                        if channel in ready:
                            data = channel.recv(65536)
                            if not data:
                                break
                            self.request.sendall(data)
                except Exception:
                    return
                finally:
                    if channel is not None:
                        channel.close()

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.stopped = threading.Event()
        self.server = Server(("127.0.0.1", 0), Handler)
        try:
            self.transport()
        except Exception:
            self.server.server_close()
            raise
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        atexit.register(self.close)

    def transport(self):
        with self.lock:
            transport = self.client.get_transport() if self.client else None
            if transport and transport.is_active():
                return transport
            if self.client:
                self.client.close()
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(PinnedHostKey())
            try:
                self.client.connect(
                    self.fields["公网IP"],
                    port=int(self.fields.get("SSH端口", "22")),
                    username=self.fields["用户名"],
                    password=self.fields["root初始密码"],
                    timeout=12,
                    banner_timeout=12,
                    auth_timeout=12,
                    allow_agent=False,
                    look_for_keys=False,
                )
            except Exception:
                self.client.close()
                raise ResourceError("ECS 私网连接失败，请核对资源和主机指纹") from None
            transport = self.client.get_transport()
            transport.set_keepalive(20)
            return transport

    def close(self):
        if self.stopped.is_set():
            return
        self.stopped.set()
        self.server.shutdown()
        self.server.server_close()
        if self.client:
            self.client.close()


@lru_cache(maxsize=1)
def database_url() -> URL:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,48}", settings.RAG_DATABASE_SCHEMA):
        raise ResourceError("数据库 schema 配置无效")
    if settings.RAG_DATABASE_URL.get_secret_value():
        url = make_url(settings.RAG_DATABASE_URL.get_secret_value())
        query = {"sslmode": settings.RAG_POSTGRES_SSLMODE, "connect_timeout": "12", **url.query}
        return url.set(drivername="postgresql+psycopg", query=query)
    if not settings.RAG_DATABASE_RESOURCE_FILE:
        raise ResourceError("PostgreSQL 连接尚未配置")
    fields = resource_fields(settings.RAG_DATABASE_RESOURCE_FILE)
    hostname = fields["PGHOST"]
    port = int(fields["PGPORT"])
    if settings.RAG_SSH_RESOURCE_FILE:
        tunnel = private_tunnel(hostname, port)
        hostname, port = tunnel.server.server_address
    return URL.create(
        "postgresql+psycopg",
        username=fields["PGUSER"],
        password=fields["PGPASSWORD"],
        host=hostname,
        port=port,
        database=fields["PGDATABASE"],
        query={"sslmode": settings.RAG_POSTGRES_SSLMODE, "connect_timeout": "12"},
    )


@lru_cache(maxsize=1)
def private_tunnel(hostname: str, port: int):
    return PrivateDatabaseTunnel((hostname, port))


@lru_cache(maxsize=1)
def sql_engine():
    return create_engine(database_url(), pool_pre_ping=True, pool_size=3, max_overflow=2, hide_parameters=True)
