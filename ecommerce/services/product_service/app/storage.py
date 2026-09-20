"""SQLAlchemy-backed repository for products."""

from __future__ import annotations

import uuid

from app.db import Base, ProductORM, engine, session_scope
from app.models import Product, ProductCreate, ProductUpdate


class ProductRepository:
    def list(self, limit: int = 50, offset: int = 0) -> list[Product]:
        with session_scope() as session:
            rows = session.query(ProductORM).order_by(ProductORM.id.asc()).offset(offset).limit(limit).all()
            return [Product.model_validate(row, from_attributes=True) for row in rows]

    def get(self, product_id: str) -> Product | None:
        with session_scope() as session:
            row = session.get(ProductORM, product_id)
            return Product.model_validate(row, from_attributes=True) if row else None

    def create(self, data: ProductCreate) -> Product:
        with session_scope() as session:
            row = ProductORM(id=str(uuid.uuid4()), **data.model_dump())
            session.add(row)
            session.flush()
            session.refresh(row)
            return Product.model_validate(row, from_attributes=True)

    def update(self, product_id: str, data: ProductUpdate) -> Product | None:
        with session_scope() as session:
            row = session.get(ProductORM, product_id)
            if row is None:
                return None
            for field, value in data.model_dump().items():
                setattr(row, field, value)
            session.flush()
            session.refresh(row)
            return Product.model_validate(row, from_attributes=True)

    def delete(self, product_id: str) -> bool:
        with session_scope() as session:
            row = session.get(ProductORM, product_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def clear(self) -> None:
        """Used by tests to reset state between runs — drops and recreates the schema."""
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)


product_repository = ProductRepository()
