"""Environment-driven configuration for the Product Service."""

from __future__ import annotations

import os

API_KEY = os.getenv("API_KEY", "local-development-api-key")
