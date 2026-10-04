from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_svc
from app.core.serialization import sanitize
from app.core.services import Services
from app.db.connectors import UnsafeConnectionError, get_adapter, test_connection
from app.schemas import ConnectionCreate

router = APIRouter(prefix="/connections", tags=["connections"])


@router.post("")
def create_connection(body: ConnectionCreate, svc: Services = Depends(get_svc)):
    try:
        adapter = get_adapter(body.dialect)
        engine = adapter.make_engine(adapter.build_url(body.host, body.port, body.database, body.username, body.password), svc.settings.sql_timeout_s)
        test_connection(engine, adapter, svc.settings.require_readonly_role)
        engine.dispose()
    except UnsafeConnectionError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # never echo driver errors verbatim (may contain host/user details)
        raise HTTPException(400, f"Could not connect ({exc.__class__.__name__}). Check host, port, database and credentials.") from exc
    data = body.model_dump(exclude={"password"})
    return sanitize(svc.repo.add_connection(password=body.password, **data))


@router.get("")
def list_connections(svc: Services = Depends(get_svc)):
    return sanitize(svc.repo.list_connections())


@router.get("/{conn_id}/schema")
def get_schema(conn_id: int, refresh: bool = False, svc: Services = Depends(get_svc)):
    try:
        return svc.schema_for(conn_id, refresh=refresh)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Could not read schema ({exc.__class__.__name__}).") from exc


@router.delete("/{conn_id}")
def forget(conn_id: int, svc: Services = Depends(get_svc)):
    svc.forget_connection(conn_id)
    return {"ok": True}
