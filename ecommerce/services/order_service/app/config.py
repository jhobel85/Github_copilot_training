"""Environment-driven configuration for the Order Service."""

from __future__ import annotations

import os

API_KEY = os.getenv("API_KEY", "local-development-api-key")
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://localhost:8001")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8002")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "5"))
# Settled order idempotency records older than this are pruned on the next key-bearing
# creation so persistent volumes stay bounded. Well beyond any sane client retry window.
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400"))
