-- Current reference for the SQLAlchemy ORM schema created by Base.metadata.create_all().
-- Each service owns a separate SQLite database; this file is documentation, not a
-- migration or a combined database deployment script.

CREATE TABLE products (
    id          VARCHAR NOT NULL PRIMARY KEY,
    name        VARCHAR NOT NULL,
    category    VARCHAR NOT NULL,
    price       FLOAT NOT NULL,
    description VARCHAR
);

CREATE TABLE inventory (
    "productId"   VARCHAR NOT NULL PRIMARY KEY,
    warehouse     VARCHAR NOT NULL,
    quantity      INTEGER NOT NULL,
    "lastUpdated" DATETIME NOT NULL
);

CREATE TABLE applied_inventory_adjustments (
    "idempotencyKey"   VARCHAR NOT NULL PRIMARY KEY,
    "productId"        VARCHAR NOT NULL,
    "quantityDelta"    INTEGER NOT NULL,
    "resultWarehouse"  VARCHAR NOT NULL,
    "resultQuantity"   INTEGER NOT NULL,
    "resultLastUpdated" DATETIME NOT NULL
);

CREATE TABLE orders (
    id           VARCHAR NOT NULL PRIMARY KEY,
    "customerId" VARCHAR NOT NULL,
    "productId"  VARCHAR NOT NULL,
    quantity     INTEGER NOT NULL,
    "unitPrice"  FLOAT NOT NULL,
    "totalPrice" FLOAT NOT NULL,
    status       VARCHAR NOT NULL,
    "createdAt"  DATETIME NOT NULL
);

CREATE TABLE order_idempotency (
    "idempotencyKey" VARCHAR NOT NULL PRIMARY KEY,
    "requestIdentity" VARCHAR NOT NULL,
    "orderId" VARCHAR NOT NULL UNIQUE REFERENCES orders (id),
    "responseSnapshot" TEXT NOT NULL
);

CREATE TABLE order_idempotency_claims (
    "idempotencyKey" VARCHAR NOT NULL PRIMARY KEY,
    "requestIdentity" VARCHAR NOT NULL,
    "ownerToken" VARCHAR NOT NULL,
    "leaseExpiresAt" DATETIME NOT NULL
);
