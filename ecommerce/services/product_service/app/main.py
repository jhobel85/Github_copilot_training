"""Product Service entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from app.logging_config import add_request_context, configure_logging
from app.routes import router

configure_logging()

app = FastAPI(title="Product Service", version="1.0.0")
add_request_context(app)
app.include_router(router)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
