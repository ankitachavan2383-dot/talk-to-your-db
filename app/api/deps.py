from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.services import Services

_bearer = HTTPBearer(auto_error=False)


def get_svc(request: Request) -> Services:
    return request.app.state.svc


def get_graph(request: Request):
    return request.app.state.graph


def require_token(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    token = request.app.state.svc.settings.api_token
    if token and not (cred and secrets.compare_digest(cred.credentials, token)):
        raise HTTPException(status_code=401, detail="Invalid or missing API token")
