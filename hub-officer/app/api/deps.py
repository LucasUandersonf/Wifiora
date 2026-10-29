from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Query, Request, status

from app.config import get_settings
from app.core.office import Office


def get_office(request: Request) -> Office:
    return request.app.state.office


def require_founder(
    x_founder_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None, description="Somente para SSE (EventSource não envia headers)"),
) -> str:
    expected = get_settings().founder_token
    supplied = x_founder_token or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None) or token
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token do fundador inválido")
    return "founder"
