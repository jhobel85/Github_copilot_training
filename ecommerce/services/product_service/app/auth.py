"""API-key authentication for Product Service resource routes."""

from __future__ import annotations

from hmac import compare_digest
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import API_KEY

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: Annotated[str | None, Security(api_key_header)]) -> None:
    if api_key is None or not compare_digest(api_key, API_KEY):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
