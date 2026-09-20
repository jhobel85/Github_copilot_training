"""REST endpoints for the Product Service."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import require_api_key
from app.models import Product, ProductCreate, ProductUpdate
from app.storage import product_repository

router = APIRouter(prefix="/products", tags=["products"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=list[Product])
def list_products(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Product]:
    return product_repository.list(limit=limit, offset=offset)


@router.get("/{product_id}", response_model=Product)
def get_product(product_id: str) -> Product:
    product = product_repository.get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product '{product_id}' not found")
    return product


@router.post("", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate) -> Product:
    return product_repository.create(payload)


@router.put("/{product_id}", response_model=Product)
def update_product(product_id: str, payload: ProductUpdate) -> Product:
    product = product_repository.update(product_id, payload)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product '{product_id}' not found")
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: str) -> None:
    if not product_repository.delete(product_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product '{product_id}' not found")
