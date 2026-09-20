"""Pydantic schemas for the Inventory Service."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class _WarehouseValidator(BaseModel):
    """Shared base holding the `warehouse` validator reused by Create and Update."""

    @field_validator("warehouse", check_fields=False)
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank or whitespace")
        return value.strip() if value is not None else value


class InventoryBase(_WarehouseValidator):
    warehouse: str = Field(..., min_length=1, max_length=100)
    quantity: int = Field(..., ge=0)


class InventoryCreate(InventoryBase):
    """Input schema for registering inventory for a product."""

    productId: str = Field(..., min_length=1)


class InventoryUpdate(_WarehouseValidator):
    """Input schema for partially updating inventory levels."""

    warehouse: str | None = Field(default=None, min_length=1, max_length=100)
    quantity: int | None = Field(default=None, ge=0)
    quantityDelta: int | None = Field(default=None)

    @model_validator(mode="after")
    def exclusive_quantity_fields(self) -> InventoryUpdate:
        if self.quantity is not None and self.quantityDelta is not None:
            raise ValueError("provide either 'quantity' or 'quantityDelta', not both")
        return self


class InventoryItem(InventoryBase):
    """Response schema returned to clients."""

    productId: str
    lastUpdated: datetime
