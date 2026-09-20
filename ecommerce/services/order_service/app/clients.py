"""HTTP clients for the Product and Inventory services."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx
from pydantic import BaseModel, ValidationError

from app.config import API_KEY, INVENTORY_SERVICE_URL, PRODUCT_SERVICE_URL, REQUEST_TIMEOUT_SECONDS
from app.logging_config import get_request_id
from app.models import UpstreamInventory, UpstreamProduct

logger = logging.getLogger(__name__)

MAX_GET_ATTEMPTS = 3
INITIAL_RETRY_DELAY_SECONDS = 0.1


class UpstreamNotFoundError(Exception):
    """Raised when the upstream service reports the resource does not exist."""


class UpstreamUnavailableError(Exception):
    """Raised when the upstream service times out or returns an unexpected error."""

    def __init__(self, service: str, detail: str) -> None:
        self.service = service
        self.detail = detail
        super().__init__(detail)


class InsufficientInventoryError(Exception):
    """Raised when Inventory Service rejects an adjustment for lack of stock."""


class InventoryIdempotencyConflictError(Exception):
    """Raised when Inventory Service rejects reuse of an idempotency key."""


class ProductClient:
    def __init__(
        self,
        base_url: str = PRODUCT_SERVICE_URL,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        api_key: str = API_KEY,
    ) -> None:
        self._base_url = base_url
        self._client = http_client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        self._sleep = sleep
        self._api_key = api_key

    def get_product(self, product_id: str) -> UpstreamProduct:
        response = _get_with_retry(
            client=self._client,
            url=f"{self._base_url}/products/{product_id}",
            service="product",
            resource=f"product '{product_id}'",
            sleep=self._sleep,
            api_key=self._api_key,
        )

        if response.status_code == 404:
            raise UpstreamNotFoundError(f"Product '{product_id}' not found")
        if response.status_code != 200:
            logger.error("Product Service returned %s for product '%s'", response.status_code, product_id)
            raise UpstreamUnavailableError("product", f"Product Service returned {response.status_code}")
        product = _validate_response(UpstreamProduct, response, "product")
        _verify_product_identifier("product", product.id, product_id)
        return product


class InventoryClient:
    def __init__(
        self,
        base_url: str = INVENTORY_SERVICE_URL,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        api_key: str = API_KEY,
    ) -> None:
        self._base_url = base_url
        self._client = http_client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        self._sleep = sleep
        self._api_key = api_key

    def get_inventory(self, product_id: str) -> UpstreamInventory:
        response = _get_with_retry(
            client=self._client,
            url=f"{self._base_url}/inventory/{product_id}",
            service="inventory",
            resource=f"inventory for product '{product_id}'",
            sleep=self._sleep,
            api_key=self._api_key,
        )

        if response.status_code == 404:
            raise UpstreamNotFoundError(f"Inventory for product '{product_id}' not found")
        if response.status_code != 200:
            logger.error("Inventory Service returned %s for product '%s'", response.status_code, product_id)
            raise UpstreamUnavailableError("inventory", f"Inventory Service returned {response.status_code}")
        inventory = _validate_response(UpstreamInventory, response, "inventory")
        _verify_product_identifier("inventory", inventory.productId, product_id)
        return inventory

    def _adjust_quantity(self, product_id: str, delta: int, idempotency_key: str | None = None) -> None:
        response = _patch_with_key_protected_retry(
            client=self._client,
            url=f"{self._base_url}/inventory/{product_id}",
            payload={"quantityDelta": delta},
            headers=_upstream_headers(self._api_key),
            idempotency_key=idempotency_key,
            product_id=product_id,
            sleep=self._sleep,
        )

        if response.status_code == 404:
            raise UpstreamNotFoundError(f"Inventory for product '{product_id}' not found")
        if response.status_code == 409:
            detail = _parse_inventory_conflict(response)
            if detail.startswith("Idempotency-Key"):
                raise InventoryIdempotencyConflictError(detail)
            raise InsufficientInventoryError(detail)
        if response.status_code != 200:
            logger.error(
                "Inventory Service update returned %s for product '%s'", response.status_code, product_id
            )
            raise UpstreamUnavailableError(
                "inventory", f"Inventory Service update returned {response.status_code}"
            )
        inventory = _validate_response(UpstreamInventory, response, "inventory")
        _verify_product_identifier("inventory", inventory.productId, product_id)

    def reduce_inventory(self, product_id: str, quantity: int, idempotency_key: str | None = None) -> None:
        self._adjust_quantity(product_id, -quantity, idempotency_key)

    def restore_inventory(self, product_id: str, quantity: int, idempotency_key: str | None = None) -> None:
        """Used by order cancellation to put reserved stock back."""
        self._adjust_quantity(product_id, quantity, idempotency_key)


def _get_with_retry(
    client: httpx.Client,
    url: str,
    service: str,
    resource: str,
    sleep: Callable[[float], None],
    api_key: str,
) -> httpx.Response:
    for attempt in range(MAX_GET_ATTEMPTS):
        try:
            response = client.get(url, headers=_upstream_headers(api_key))
        except httpx.RequestError as exc:
            if attempt == MAX_GET_ATTEMPTS - 1:
                logger.error("%s Service request failed for %s: %s", service.title(), resource, exc)
                raise UpstreamUnavailableError(service, f"{service.title()} Service request failed") from exc
        else:
            if response.status_code < 500 or attempt == MAX_GET_ATTEMPTS - 1:
                return response

        sleep(INITIAL_RETRY_DELAY_SECONDS * (2**attempt))

    raise RuntimeError("unreachable")


def _patch_with_key_protected_retry(
    client: httpx.Client,
    url: str,
    payload: dict[str, int],
    headers: dict[str, str],
    idempotency_key: str | None,
    product_id: str,
    sleep: Callable[[float], None],
) -> httpx.Response:
    """Single-attempt PATCH unless the request failed at the transport layer.

    A `httpx.RequestError` (connect/timeout/read failure) leaves it ambiguous whether the
    adjustment reached Inventory Service. When the caller supplied an `Idempotency-Key` —
    order creation and cancellation always do — one extra attempt with the *same* key is
    safe: Inventory replays recorded keys with the stored snapshot, so a duplicate delta
    cannot land. Without a key, any retry is a double-decrement risk, so we stay
    single-attempt. Non-transport `HTTPError`s and any received response (including 5xx)
    are never retried here: explicit responses surface via the caller's status mapping,
    and the caller's own key-based retry covers them.
    """
    max_attempts = 2 if idempotency_key is not None else 1
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    for attempt in range(max_attempts):
        try:
            return client.patch(url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            if attempt == max_attempts - 1:
                if isinstance(exc, httpx.TimeoutException):
                    logger.error("Inventory Service timed out updating product '%s'", product_id)
                    raise UpstreamUnavailableError(
                        "inventory", "Inventory Service request timed out"
                    ) from exc
                logger.error("Inventory Service update failed for product '%s': %s", product_id, exc)
                raise UpstreamUnavailableError("inventory", "Inventory Service request failed") from exc
            sleep(INITIAL_RETRY_DELAY_SECONDS * (2**attempt))
        except httpx.HTTPError as exc:
            # Non-transport failure (e.g. invalid URL): never retriable, surfaced as 502 as before.
            logger.error("Inventory Service update failed for product '%s': %s", product_id, exc)
            raise UpstreamUnavailableError("inventory", "Inventory Service request failed") from exc
    raise RuntimeError("unreachable")


def _upstream_headers(api_key: str) -> dict[str, str]:
    headers = {"X-API-Key": api_key}
    request_id = get_request_id()
    if request_id is not None:
        headers["X-Request-ID"] = request_id
    return headers


def _validate_response[UpstreamModel: BaseModel](
    model: type[UpstreamModel],
    response: httpx.Response,
    service: str,
) -> UpstreamModel:
    try:
        return model.model_validate(response.json())
    except (ValidationError, ValueError) as exc:
        logger.error("%s Service response validation failed: %s", service.title(), exc)
        raise UpstreamUnavailableError(
            service, f"{service.title()} Service response validation failed: {exc}"
        ) from exc


def _verify_product_identifier(service: str, actual: str, requested: str) -> None:
    if actual != requested:
        logger.error(
            "%s Service returned product identifier '%s' for requested product '%s'",
            service.title(),
            actual,
            requested,
        )
        raise UpstreamUnavailableError(
            service,
            f"{service.title()} Service response identifier mismatch: expected '{requested}', got '{actual}'",
        )


def _parse_inventory_conflict(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError as exc:
        _raise_invalid_inventory_conflict(exc)

    if not isinstance(payload, dict) or not isinstance(payload.get("detail"), str):
        _raise_invalid_inventory_conflict()

    detail = payload["detail"]
    if detail.startswith(("Insufficient inventory", "Idempotency-Key")):
        return detail
    _raise_invalid_inventory_conflict()


def _raise_invalid_inventory_conflict(exc: ValueError | None = None) -> None:
    detail = "Inventory Service conflict response validation failed"
    logger.error(detail)
    raise UpstreamUnavailableError("inventory", detail) from exc


# Singletons so requests reuse pooled httpx connections instead of opening one per request.
product_client = ProductClient()
inventory_client = InventoryClient()
