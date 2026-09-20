# SDLC Exercise — User Stories

**Phase:** Planning · **Slice:** Order cancellation (`PATCH /orders/{id}`)
**Output consumed by:** Design ([api-design.md](api-design.md))

## Product management

### US-01 — List the catalog
As a store operator, I want to list all products, so that I can see the current catalog.

| # | Given | When | Then |
|---|---|---|---|
| 1 | products exist | `GET /products` | `200` with the full list |
| 2 (failure) | a product id that doesn't exist | `GET /products/{id}` | `404` |

### US-02 — Register a new product
As a store operator, I want to create a product, so that it becomes orderable.

| # | Given | When | Then |
|---|---|---|---|
| 1 | a valid name/category/price | `POST /products` | `201` with the created product |
| 2 (failure) | price <= 0 or a blank name | `POST /products` | `422` |

## Inventory management

### US-03 — Check stock for a product
As an inventory clerk, I want to look up current stock for a product, so that I can confirm availability
before promising it to a customer.

| # | Given | When | Then |
|---|---|---|---|
| 1 | inventory exists for the product | `GET /inventory/{productId}` | `200` with quantity |
| 2 (failure) | no inventory record for the product | `GET /inventory/{productId}` | `404` |

### US-04 — Adjust stock levels
As an inventory clerk, I want to update the quantity for a product, so that stock reflects reality after a
delivery, correction, or cancellation.

| # | Given | When | Then |
|---|---|---|---|
| 1 | inventory exists | `PATCH /inventory/{productId}` with a new quantity | `200` with the updated record |
| 2 (failure) | inventory doesn't exist for the product | `PATCH /inventory/{productId}` | `404` |

## Order processing

### US-05 — Place an order
As a customer, I want to place an order for a product, so that I can purchase it.

| # | Given | When | Then |
|---|---|---|---|
| 1 | the product exists and has enough stock | `POST /orders` | `201`, inventory reduced by the order quantity |
| 2 (failure) | the product doesn't exist | `POST /orders` | `404` |
| 3 (failure) | requested quantity exceeds available stock | `POST /orders` | `409` |
| 4 (failure) | Product or Inventory Service is unreachable/times out | `POST /orders` | `502` |

### US-06 — View an order
As a customer, I want to look up an order I placed, so that I can confirm its details.

| # | Given | When | Then |
|---|---|---|---|
| 1 | the order exists | `GET /orders/{id}` | `200` with the order |
| 2 (failure) | the order doesn't exist | `GET /orders/{id}` | `404` |

### US-07 — Cancel an order *(new slice)*
As a customer, I want to cancel an order I placed, so that my reserved stock is released and the order stops
being fulfilled.

| # | Given | When | Then |
|---|---|---|---|
| 1 | the order exists and is not already cancelled | `PATCH /orders/{id}` `{"status": "CANCELLED"}` | `200`, order `status` becomes `CANCELLED`, inventory increased back by the order's quantity |
| 2 (failure) | the order doesn't exist | `PATCH /orders/{id}` | `404` |
| 3 (failure) | the order is already cancelled | `PATCH /orders/{id}` | `409` |
| 4 (failure) | the requested status isn't `CANCELLED` | `PATCH /orders/{id}` | `422` |
| 5 (failure) | Inventory Service is unreachable/times out while restoring stock | `PATCH /orders/{id}` | `502`, order status unchanged |

### US-08 — List my orders
As a customer, I want to list all orders, so that I can see order history including cancellations.

| # | Given | When | Then |
|---|---|---|---|
| 1 | orders exist, some cancelled | `GET /orders` | `200` with every order and its current `status` |

---
Every row above must trace to an endpoint in [api-design.md](api-design.md); US-07 is the slice this exercise
carries through Design, Coding, Testing, and Review.
