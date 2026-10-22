"""Immutable reference versions, four-eyes publication and derived invalidation.

Separate SQLAlchemy tables never enter the public knowledge vector index. All
content reads filter exact namespaces and current lifecycle state. Low-frequency
curation writes share a database mutex; reads remain independent. Schema creation
is explicit, not an application-startup migration.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import (JSON, Column, DateTime, ForeignKey, Index, Integer, MetaData,
                        String, Table, Text, UniqueConstraint, func, inspect,
                        literal_column, or_, select, update)

from .config import settings
from .database import ResourceError, sql_engine
from .lexical_index import lexical_tokens, query_expression
from .reference_contracts import ReferenceCandidate


class ReferenceConflict(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def aware(value):
    # SQLite test transport loses timezone information; PostgreSQL uses timestamptz.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def payload_digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ReferenceStore:
    def __init__(self, engine, *, schema=None, clock=utc_now):
        self.engine, self.clock = engine, clock
        self.metadata = MetaData(schema=schema)
        self.lock = Table("reference_lock_v1", self.metadata, Column("id", Integer, primary_key=True))
        self.versions = Table("reference_versions_v1", self.metadata,
            Column("id", String(36), primary_key=True), Column("namespace", String(64), nullable=False),
            Column("logical_id", String(80), nullable=False), Column("kind", String(30), nullable=False),
            Column("version", Integer, nullable=False), Column("revision", Integer, nullable=False),
            Column("state", String(20), nullable=False), Column("author", String(100), nullable=False),
            Column("reviewer", String(100)), Column("content_sha256", String(64), nullable=False),
            Column("retain_until", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("product", String(100), nullable=False), Column("jurisdiction", String(100), nullable=False),
            Column("issue_type", String(100), nullable=False), Column("policy_version", String(100), nullable=False),
            Column("leakage_group_id", String(100), nullable=False),
            Column("payload", JSON, nullable=False), Column("search_text", Text, nullable=False),
            UniqueConstraint("namespace", "kind", "logical_id", "version"))
        Index("reference_visibility_v1", self.versions.c.namespace, self.versions.c.kind, self.versions.c.state)
        Index("reference_fts_v1", func.to_tsvector(literal_column("'pg_catalog.simple'::regconfig"), self.versions.c.search_text),
              _table=self.versions, postgresql_using="gin").ddl_if(dialect="postgresql")
        self.dependencies = Table("reference_dependencies_v1", self.metadata,
            Column("child_id", String(36), ForeignKey(self.versions.c.id), primary_key=True),
            Column("parent_id", String(36), ForeignKey(self.versions.c.id), primary_key=True))
        Index("reference_parent_v1", self.dependencies.c.parent_id)
        self.events = Table("reference_audit_v1", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("namespace", String(64), nullable=False), Column("version_id", String(36), nullable=False),
            Column("actor", String(100), nullable=False), Column("action", String(40), nullable=False),
            Column("at", DateTime(timezone=True), nullable=False), Column("details", JSON, nullable=False))

    def apply_schema(self):
        """Explicit operator action. Does not create a schema or touch KB tables."""
        with self.engine.begin() as connection:
            self.metadata.create_all(connection)
            if connection.execute(select(self.lock.c.id).where(self.lock.c.id == 1)).first() is None:
                connection.execute(self.lock.insert().values(id=1))

    def require_ready(self):
        inspector = inspect(self.engine)
        if any(not inspector.has_table(table.name, schema=table.schema) for table in self.metadata.tables.values()):
            raise ResourceError("参考库表尚未部署；需先审核并显式运行参考库迁移")

    @contextmanager
    def writing(self):
        with self.engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(select(func.set_config("lock_timeout", "5000", True)))
                connection.execute(select(func.set_config("statement_timeout", "10000", True)))
            if connection.execute(select(self.lock.c.id).where(self.lock.c.id == 1).with_for_update()).first() is None:
                raise ResourceError("参考库写入锁未初始化")
            yield connection

    def _event(self, connection, row, actor, action, **details):
        connection.execute(self.events.insert().values(namespace=row["namespace"], version_id=row["id"],
            actor=actor.subject, action=action, at=self.clock(), details={"content_sha256": row["content_sha256"],
                "version": row["version"], "revision_at_observation": row["revision"], **details}))

    def _row(self, connection, namespace, version_id):
        row = connection.execute(select(self.versions).where(self.versions.c.namespace == namespace,
            self.versions.c.id == str(version_id))).mappings().first()
        if row is None:
            raise LookupError("reference not found")
        return dict(row)

    def _parents(self, connection, row):
        return [dict(item) for item in connection.execute(select(self.versions).join(self.dependencies,
            self.dependencies.c.parent_id == self.versions.c.id).where(self.dependencies.c.child_id == row["id"]))
            .mappings().all()]

    def _active(self, row):
        return row["state"] == "approved" and aware(row["retain_until"]) > self.clock() and bool(row["payload"])

    def _valid_parents(self, connection, row, *, excluded=()):
        if row["kind"] == "case_reference":
            return True
        parents = self._parents(connection, row)
        return len(parents) >= 2 and len({parent["logical_id"] for parent in parents}) >= 2 and all(
            self._active(parent) and parent["kind"] == "case_reference" and
            parent["namespace"] == row["namespace"] and parent["leakage_group_id"] not in excluded and
            all(parent[key] == row[key] for key in ("product", "jurisdiction", "issue_type", "policy_version"))
            for parent in parents)

    @staticmethod
    def public(row, *, include_payload=True):
        result = {key: row[key] for key in ("id", "namespace", "logical_id", "kind", "version", "revision", "state",
                  "author", "reviewer", "content_sha256", "retain_until", "created_at")}
        result["use_limit"] = ("historical_reference_only; not a rule, current-case fact or approval probability"
            if row["kind"] == "case_reference" else "planning_checklist_or_query_strategy_only; not system instructions or approval rules")
        if include_payload:
            result["content"] = row["payload"]
        return result

    def create(self, actor, candidate: ReferenceCandidate):
        actor.require(candidate.namespace, "author")
        now = self.clock()
        if candidate.retain_until <= now or candidate.source_reviewed_at > now or candidate.business_date > now.date():
            raise ReferenceConflict("invalid source time or elapsed retention")
        payload = candidate.model_dump(mode="json")
        with self.writing() as connection:
            version = connection.execute(select(func.max(self.versions.c.version)).where(
                self.versions.c.namespace == candidate.namespace, self.versions.c.kind == candidate.kind,
                self.versions.c.logical_id == candidate.logical_id)).scalar_one() or 0
            row = {"id": str(uuid4()), "namespace": candidate.namespace, "kind": candidate.kind,
                   "logical_id": candidate.logical_id, "version": version + 1, "revision": 1, "state": "candidate",
                   "author": actor.subject, "reviewer": None, "content_sha256": payload_digest(payload),
                   "created_at": now, "retain_until": candidate.retain_until, "payload": payload,
                   "search_text": " ".join(lexical_tokens(candidate.facts_summary + " " + candidate.handling)),
                   **{key: getattr(candidate, key) for key in ("product", "jurisdiction", "issue_type", "policy_version", "leakage_group_id")}}
            parents = []
            for parent_id in candidate.parent_version_ids:
                parent = self._row(connection, candidate.namespace, parent_id)
                if parent["kind"] != "case_reference" or not self._active(parent):
                    raise ReferenceConflict("memory source case is not currently approved")
                parents.append(parent)
            if parents and (len({item["logical_id"] for item in parents}) < 2 or
                            any(candidate.retain_until > aware(item["retain_until"]) for item in parents)):
                raise ReferenceConflict("memory needs distinct cases and cannot outlive any source")
            connection.execute(self.versions.insert().values(**row))
            if parents:
                connection.execute(self.dependencies.insert(), [{"child_id": row["id"], "parent_id": parent["id"]} for parent in parents])
                if not self._valid_parents(connection, row):
                    raise ReferenceConflict("memory source conditions do not match")
            self._event(connection, row, actor, "candidate_created", parent_ids=[item["id"] for item in parents])
            return self.public(row)

    def _check_revision(self, row, action):
        if row["revision"] != action.expected_revision or row["content_sha256"] != action.content_sha256:
            raise ReferenceConflict("stale revision or content binding")
        if aware(row["retain_until"]) <= self.clock() or not row["payload"]:
            raise ReferenceConflict("reference retention has elapsed")

    def _invalidate_children(self, connection, parent, actor, *, erase=False):
        changed = 0
        children = connection.execute(select(self.versions).join(self.dependencies,
            self.dependencies.c.child_id == self.versions.c.id).where(self.dependencies.c.parent_id == parent["id"]))
        for child in children.mappings().all():
            if erase and not child["payload"]:
                continue
            if child["state"] in {"withdrawn", "expired", "superseded"} and not erase:
                continue
            values = {"state": "expired" if erase else "withdrawn", "revision": child["revision"] + 1}
            if erase:
                values.update(payload={}, search_text="")
            connection.execute(update(self.versions).where(self.versions.c.id == child["id"]).values(**values))
            self._event(connection, child, actor, "source_erased" if erase else "source_invalidated", parent_id=parent["id"])
            changed += 1
        return changed

    def approve(self, actor, namespace, version_id, action):
        actor.require(namespace, "reviewer")
        with self.writing() as connection:
            row = self._row(connection, namespace, version_id)
            self._check_revision(row, action)
            payload = row["payload"]
            if row["state"] != "candidate" or row["author"] == actor.subject:
                raise ReferenceConflict("publication needs a separate reviewer and candidate state")
            if not payload["redaction_confirmed"] or not payload["sharing_authorized"] or payload["evaluation_only"] or payload["conclusion_status"] != "confirmed":
                raise ReferenceConflict("redaction, sharing and confirmed non-evaluation evidence are required")
            if any(row[key].strip().casefold() in {"unknown", "未知", "待确认", "n/a"} for key in
                   ("product", "jurisdiction", "issue_type", "policy_version")):
                raise ReferenceConflict("unknown applicability cannot become guidance")
            if not self._valid_parents(connection, row):
                raise ReferenceConflict("memory sources are no longer valid")
            peers = connection.execute(select(self.versions).where(self.versions.c.namespace == namespace,
                self.versions.c.kind == row["kind"], self.versions.c.logical_id == row["logical_id"],
                self.versions.c.state == "approved")).mappings().all()
            if any(peer["version"] > row["version"] for peer in peers):
                raise ReferenceConflict("cannot publish an older version over a newer approved version")
            for peer in peers:
                connection.execute(update(self.versions).where(self.versions.c.id == peer["id"])
                    .values(state="superseded", revision=peer["revision"] + 1))
                self._invalidate_children(connection, peer, actor)
                self._event(connection, peer, actor, "superseded", replacement_id=row["id"])
            row.update(state="approved", reviewer=actor.subject, revision=row["revision"] + 1)
            connection.execute(update(self.versions).where(self.versions.c.id == row["id"])
                .values(state=row["state"], reviewer=row["reviewer"], revision=row["revision"]))
            self._event(connection, row, actor, "approved")
            return self.public(row)

    def withdraw(self, actor, namespace, version_id, action):
        actor.require(namespace, "reviewer")
        with self.writing() as connection:
            row = self._row(connection, namespace, version_id)
            self._check_revision(row, action)
            if row["state"] not in {"candidate", "approved"}:
                raise ReferenceConflict("reference is already inactive")
            connection.execute(update(self.versions).where(self.versions.c.id == row["id"])
                .values(state="withdrawn", revision=row["revision"] + 1))
            self._invalidate_children(connection, row, actor)
            self._event(connection, row, actor, "withdrawn", reason=action.reason)
            return {"id": row["id"], "state": "withdrawn", "revision": row["revision"] + 1}

    def get(self, actor, namespace, version_id, *, inspect_candidate=False):
        actor.require(namespace, "reviewer" if inspect_candidate else "reader")
        with self.engine.begin() as connection:
            row = self._row(connection, namespace, version_id)
            if aware(row["retain_until"]) <= self.clock() or not row["payload"]:
                raise LookupError("reference not found")
            if not inspect_candidate and (not self._active(row) or not self._valid_parents(connection, row)):
                raise LookupError("reference not found")
            self._event(connection, row, actor, "curation_read" if inspect_candidate else "reference_read")
            return self.public(row)

    def search(self, actor, query):
        actor.require(query.namespace, "reader")
        words = list(dict.fromkeys(lexical_tokens(query.query)))
        if not words:
            return []
        if len(words) > 256:
            raise ReferenceConflict("reference query exceeds token budget")
        v = self.versions
        statement = select(v).where(v.c.namespace == query.namespace, v.c.kind == query.kind,
            v.c.state == "approved", v.c.retain_until > self.clock(),
            *[getattr(v.c, key) == getattr(query, key) for key in ("product", "jurisdiction", "issue_type", "policy_version")])
        if query.excluded_leakage_groups:
            statement = statement.where(v.c.leakage_group_id.not_in(query.excluded_leakage_groups))
        if query.kind == "experience_memory":
            parent = v.alias("source_case")
            dependency_rows = self.dependencies.join(parent, self.dependencies.c.parent_id == parent.c.id)
            invalid = or_(parent.c.state != "approved", parent.c.retain_until <= self.clock(),
                parent.c.namespace != v.c.namespace, parent.c.kind != "case_reference",
                *[getattr(parent.c, key) != getattr(v.c, key) for key in ("product", "jurisdiction", "issue_type", "policy_version")])
            if query.excluded_leakage_groups:
                invalid = or_(invalid, parent.c.leakage_group_id.in_(query.excluded_leakage_groups))
            invalid_source = select(1).select_from(dependency_rows).where(self.dependencies.c.child_id == v.c.id, invalid).exists()
            source_count = select(func.count(func.distinct(parent.c.logical_id))).select_from(dependency_rows).where(
                self.dependencies.c.child_id == v.c.id).scalar_subquery()
            statement = statement.where(~invalid_source, source_count >= 2)
        with self.engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(select(func.set_config("statement_timeout", "10000", True)))
                terms = func.to_tsvector(literal_column("'pg_catalog.simple'::regconfig"), v.c.search_text)
                expression = query_expression(query.query)
                statement = statement.where(terms.op("@@")(expression)).order_by(func.ts_rank_cd(terms, expression).desc(), v.c.id).limit(query.top_k)
            else:
                # Portable mechanism tests; production reference service is PostgreSQL-only.
                statement = statement.order_by(v.c.id)
            rows = connection.execute(statement).mappings()
            result = []
            for row in rows:
                if not set(words).intersection(row["search_text"].split()) or not self._valid_parents(connection, row, excluded=query.excluded_leakage_groups):
                    continue
                result.append(self.public(row))
                self._event(connection, row, actor, "reference_read", mode="search")
                if len(result) == query.top_k:
                    break
            return result

    def purge_expired(self, actor, namespace):
        actor.require(namespace, "reviewer")
        with self.writing() as connection:
            rows = connection.execute(select(self.versions).where(self.versions.c.namespace == namespace,
                self.versions.c.retain_until <= self.clock(), self.versions.c.state != "expired")).mappings().all()
            erased = 0
            for row in rows:
                row = self._row(connection, namespace, row["id"])
                if row["state"] == "expired":
                    continue
                connection.execute(update(self.versions).where(self.versions.c.id == row["id"])
                    .values(state="expired", revision=row["revision"] + 1, payload={}, search_text=""))
                erased += self._invalidate_children(connection, row, actor, erase=True)
                self._event(connection, row, actor, "retention_erased")
                erased += 1
            return {"erased_versions": erased}

    def audit(self, actor, namespace, *, after=0):
        actor.require(namespace, "reviewer")
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(select(self.events).where(
                self.events.c.namespace == namespace, self.events.c.id > after).order_by(self.events.c.id).limit(100)).mappings()]


@lru_cache(maxsize=1)
def get_reference_store():
    store = ReferenceStore(sql_engine(), schema=settings.RAG_DATABASE_SCHEMA)
    store.require_ready()
    return store
