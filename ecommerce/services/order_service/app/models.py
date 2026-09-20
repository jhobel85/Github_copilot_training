"""Pydantic schemas for the Order Service."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OrderStatus = Literal["CONFIRMED", "CANCELLED"]


class OrderCreate(BaseModel):
    """Input schema for placing an order."""

    model_config = ConfigDict(extra="allow")

    customerId: str = Field(..., min_length=1)
    productId: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)


class OrderStatusUpdate(BaseModel):
    """Input schema for transitioning an order's status."""

    status: Literal["CANCELLED"]


class Order(BaseModel):
    """Response schema returned to clients."""

    # validate_assignment so `order.status = ...` is checked like a constructor argument.
    model_config = ConfigDict(validate_assignment=True)

    id: str
    customerId: str
    productId: str
    quantity: int
    unitPrice: float
    totalPrice: float
    status: OrderStatus
    createdAt: datetime


class UpstreamProduct(BaseModel):
    """Validated subset of the Product Service response used to create orders."""

    id: str
    price: float = Field(..., gt=0)


class UpstreamInventory(BaseModel):
    """Validated subset of the Inventory Service response used to create orders."""

    productId: str
    quantity: int = Field(..., ge=0)
