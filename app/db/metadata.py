"""Application metadata + analysis history, stored in PostgreSQL via SQLAlchemy.
(Use Alembic for migrations in a real deployment; create_all keeps the starter simple.)"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from sqlalchemy import JSON, DateTime, Integer, String, Text, create_engine, delete, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.security import SecretBox

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(20))
    stored_path: Mapped[str] = mapped_column(Text)
    n_rows: Mapped[int] = mapped_column(Integer)
    n_cols: Mapped[int] = mapped_column(Integer)
    profile: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DbConnection(Base):
    __tablename__ = "db_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    dialect: Mapped[str] = mapped_column(String(20))
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    database: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    password_enc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(20), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    question: Mapped[str] = mapped_column(Text)
    intent: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    sql: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    spec: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    facts: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    charts: Mapped[Optional[list]] = mapped_column(JSONType, nullable=True)
    kpis: Mapped[Optional[list]] = mapped_column(JSONType, nullable=True)
    insight: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DashboardItem(Base):
    __tablename__ = "dashboard_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), index=True)  # "dataset:3" | "connection:2"
    kind: Mapped[str] = mapped_column(String(20))  # chart | kpi | table
    title: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSONType)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def scope_of(source_type: str, source_id: int) -> str:
    return f"{source_type}:{source_id}"


def _d(obj: Any) -> dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class MetadataRepo:
    def __init__(self, url: str, secret_key: str = "") -> None:
        self.engine = create_engine(url, pool_pre_ping=True)
        self._Session = sessionmaker(self.engine, expire_on_commit=False)
        self._secret_key = secret_key
        self._box: SecretBox | None = None
        Base.metadata.create_all(self.engine)

    @property
    def box(self) -> SecretBox:
        if self._box is None:
            self._box = SecretBox(self._secret_key)
        return self._box

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def _add(self, obj: Any) -> dict[str, Any]:
        with self.session() as s:
            s.add(obj)
            s.flush()
            return _d(obj)

    # datasets
    def add_dataset(self, **kw: Any) -> dict[str, Any]:
        return self._add(Dataset(**kw))

    def get_dataset(self, dataset_id: int) -> dict[str, Any] | None:
        with self.session() as s:
            o = s.get(Dataset, dataset_id)
            return _d(o) if o else None

    def list_datasets(self) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.scalars(select(Dataset).order_by(Dataset.id.desc())).all()
            return [{k: v for k, v in _d(r).items() if k != "profile"} for r in rows]

    # connections
    def add_connection(self, password: str, **kw: Any) -> dict[str, Any]:
        d = self._add(DbConnection(password_enc=self.box.encrypt(password), **kw))
        d.pop("password_enc", None)
        return d

    def get_connection(self, conn_id: int, with_secret: bool = False) -> dict[str, Any] | None:
        with self.session() as s:
            o = s.get(DbConnection, conn_id)
            if not o:
                return None
            d = _d(o)
            enc = d.pop("password_enc")
            if with_secret:
                d["password"] = self.box.decrypt(enc)
            return d

    def list_connections(self) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.scalars(select(DbConnection).order_by(DbConnection.id.desc())).all()
            return [{k: v for k, v in _d(r).items() if k != "password_enc"} for r in rows]

    # chat + runs
    def add_message(self, session_id: str, role: str, content: str, source_type: str | None, source_id: int | None) -> None:
        self._add(ChatMessage(session_id=session_id, role=role, content=content, source_type=source_type, source_id=source_id))

    def history(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)
                             .order_by(ChatMessage.id.desc()).limit(limit)).all()
            return [{"role": r.role, "content": r.content} for r in reversed(rows)]

    def add_run(self, **kw: Any) -> dict[str, Any]:
        return self._add(AnalysisRun(**kw))

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self.session() as s:
            o = s.get(AnalysisRun, run_id)
            return _d(o) if o else None

    def last_run(self, session_id: str, with_result: bool = False) -> dict[str, Any] | None:
        with self.session() as s:
            q = select(AnalysisRun).where(AnalysisRun.session_id == session_id)
            if with_result:
                q = q.where(AnalysisRun.result_path.is_not(None))
            o = s.scalars(q.order_by(AnalysisRun.id.desc()).limit(1)).first()
            return _d(o) if o else None

    def recent_runs(self, source_type: str, source_id: int, limit: int = 10) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.scalars(select(AnalysisRun).where(AnalysisRun.source_type == source_type, AnalysisRun.source_id == source_id)
                             .order_by(AnalysisRun.id.desc()).limit(limit)).all()
            return [_d(r) for r in rows]

    # dashboard
    def add_dashboard_item(self, scope: str, kind: str, title: str, payload: dict) -> dict[str, Any]:
        with self.session() as s:
            pos = len(s.scalars(select(DashboardItem.id).where(DashboardItem.scope == scope)).all())
        return self._add(DashboardItem(scope=scope, kind=kind, title=title, payload=payload, position=pos))

    def list_dashboard_items(self, scope: str) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.scalars(select(DashboardItem).where(DashboardItem.scope == scope).order_by(DashboardItem.position, DashboardItem.id)).all()
            return [_d(r) for r in rows]

    def delete_dashboard_item(self, item_id: int) -> None:
        with self.session() as s:
            s.execute(delete(DashboardItem).where(DashboardItem.id == item_id))
