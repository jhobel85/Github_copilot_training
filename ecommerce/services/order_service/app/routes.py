"""REST endpoints for the Order Service."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.auth import require_api_key
from app.clients import (
    InsufficientInventoryError,
    InventoryClient,
    InventoryIdempotencyConflictError,
    ProductClient,
    UpstreamNotFoundError,
    UpstreamUnavailableError,
)
from app.clients import (
    inventory_client as default_inventory_client,
)
from app.clients import (
    product_client as default_product_client,
)
from app.models import Order, OrderCreate, OrderStatusUpdate
from app.storage import (
    OrderIdempotencyConflictError,
    OrderIdempotencyPendingError,
    order_repository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(require_api_key)])


def get_product_client() -> ProductClient:
    return default_product_client


def get_inventory_client() -> InventoryClient:
    return default_inventory_client


@router.get("", response_model=list[Order])
def list_orders(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Order]:
    return order_repository.list(limit=limit, offset=offset)


@router.get("/{order_id}", response_model=Order)
def get_order(order_id: str) -> Order:
    order = order_repository.get(order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Order '{order_id}' not found")
    return order


@router.post("", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    product_client: ProductClient = Depends(get_product_client),
    inventory_client: InventoryClient = Depends(get_inventory_client),
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ] = None,
) -> Order:
    if idempotency_key is None:
        return order_repository.add(_create_confirmed_order(payload, product_client, inventory_client, None))

    request_identity = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        return order_repository.create_idempotently(
            idempotency_key,
            request_identity,
            lambda: _create_confirmed_order(
                payload,
                product_client,
                inventory_client,
                f"order-create:{idempotency_key}",
            ),
        )
    except OrderIdempotencyConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except OrderIdempotencyPendingError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def _create_confirmed_order(
    payload: OrderCreate,
    product_client: ProductClient,
    inventory_client: InventoryClient,
    inventory_idempotency_key: str | None,
) -> Order:
    try:
        product = product_client.get_product(payload.productId)
        inventory = inventory_client.get_inventory(payload.productId)
    except UpstreamNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except UpstreamUnavailableError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"{exc.service} service unavailable: {exc.detail}"
        ) from exc

    available = inventory.quantity
    unit_price = product.price

    if available < payload.quantity:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Insufficient inventory for product '{payload.productId}': {available} available, "
            f"{payload.quantity} requested",
        )

    try:
        inventory_client.reduce_inventory(
            payload.productId,
            payload.quantity,
            inventory_idempotency_key,
        )
    except InsufficientInventoryError as exc:
        # Stock dropped between the check above and this call; the server-side delta caught it.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except InventoryIdempotencyConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UpstreamNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except UpstreamUnavailableError as exc:
        logger.error("Inventory reduction failed for product '%s': %s", payload.productId, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"{exc.service} service unavailable: {exc.detail}"
        ) from exc

    order = Order(
        id=str(uuid.uuid4()),
        customerId=payload.customerId,
        productId=payload.productId,
        quantity=payload.quantity,
        unitPrice=unit_price,
        totalPrice=round(unit_price * payload.quantity, 2),
        status="CONFIRMED",
        createdAt=datetime.now(UTC),
    )
    return order


@router.patch("/{order_id}", response_model=Order)
def update_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    inventory_client: InventoryClient = Depends(get_inventory_client),
) -> Order:
    order = order_repository.get(order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Order '{order_id}' not found")
    if order.status == payload.status:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Order '{order_id}' is already cancelled")

    try:
        inventory_client.restore_inventory(
            order.productId,
            order.quantity,
            f"order-cancel:{order.id}",
        )
    except UpstreamNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InventoryIdempotencyConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UpstreamUnavailableError as exc:
        # Order stays in its prior state; only a successful restore flips it to CANCELLED.
        logger.error("Inventory restoration failed for order '%s': %s", order_id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"{exc.service} service unavailable: {exc.detail}"
        ) from exc

    order.status = payload.status
    return order_repository.add(order)
