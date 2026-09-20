"""Pydantic schemas for the Product Service."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., min_length=1, max_length=100)
    price: float = Field(..., gt=0)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "category")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank or whitespace")
        return value.strip()


class ProductCreate(ProductBase):
    """Input schema for creating a product."""


class ProductUpdate(ProductBase):
    """Input schema for replacing a product."""


class Product(ProductBase):
    """Response schema returned to clients."""

    id: str
