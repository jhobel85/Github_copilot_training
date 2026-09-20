"""Environment-driven configuration for the Inventory Service."""

from __future__ import annotations

import os

API_KEY = os.getenv("API_KEY", "local-development-api-key")
# Applied idempotency adjustments older than this are pruned on the next delta update so
# persistent volumes stay bounded. Well beyond any sane client retry window.
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400"))
