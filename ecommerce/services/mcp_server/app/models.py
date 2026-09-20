"""Validated response schemas for upstream e-commerce services."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UpstreamResponse(BaseModel):
    """Base schema that tolerates additive upstream fields."""

    model_config = ConfigDict(extra="allow")


class ProductResponse(UpstreamResponse):
    """Successful Product Service resource payload."""

    id: str = Field(..., min_length=1, strict=True)
    name: str = Field(..., min_length=1, max_length=200, strict=True)
    category: str = Field(..., min_length=1, max_length=100, strict=True)
    price: float = Field(..., gt=0, strict=True)
    description: str | None = Field(default=None, max_length=2000)


class InventoryResponse(UpstreamResponse):
    """Successful Inventory Service resource payload."""

    productId: str = Field(..., min_length=1, strict=True)
    warehouse: str = Field(..., min_length=1, max_length=100, strict=True)
    quantity: int = Field(..., ge=0, strict=True)
    lastUpdated: datetime


class OrderResponse(UpstreamResponse):
    """Successful Order Service resource payload."""

    id: str = Field(..., min_length=1, strict=True)
    customerId: str = Field(..., min_length=1, strict=True)
    productId: str = Field(..., min_length=1, strict=True)
    quantity: int = Field(..., gt=0, strict=True)
    unitPrice: float = Field(..., gt=0, strict=True)
    totalPrice: float = Field(..., gt=0, strict=True)
    status: Literal["CONFIRMED", "CANCELLED"]
    createdAt: datetime
