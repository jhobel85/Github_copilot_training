"""REST endpoints for the Inventory Service."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.auth import require_api_key
from app.models import InventoryCreate, InventoryItem, InventoryUpdate
from app.storage import (
    IdempotencyKeyConflictError,
    InsufficientInventoryError,
    inventory_repository,
)

router = APIRouter(prefix="/inventory", tags=["inventory"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=list[InventoryItem])
def list_inventory(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[InventoryItem]:
    return inventory_repository.list(limit=limit, offset=offset)


@router.get("/{product_id}", response_model=InventoryItem)
def get_inventory(product_id: str) -> InventoryItem:
    item = inventory_repository.get(product_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inventory for product '{product_id}' not found")
    return item


@router.post("", response_model=InventoryItem, status_code=status.HTTP_201_CREATED)
def create_inventory(payload: InventoryCreate) -> InventoryItem:
    item = inventory_repository.create(payload)
    if item is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Inventory for product '{payload.productId}' already exists",
        )
    return item


@router.patch("/{product_id}", response_model=InventoryItem)
def update_inventory(
    product_id: str,
    payload: InventoryUpdate,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ] = None,
) -> InventoryItem:
    try:
        item = inventory_repository.update(product_id, payload, idempotency_key)
    except InsufficientInventoryError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except IdempotencyKeyConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inventory for product '{product_id}' not found")
    return item
