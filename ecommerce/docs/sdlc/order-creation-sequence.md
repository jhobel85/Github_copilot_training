# SDLC Exercise — Sequence Diagrams

**Phase:** Design · **Slice:** Order cancellation
**Input:** [user-stories.md](user-stories.md), [api-design.md](api-design.md)

## Order creation (existing behavior)

```mermaid
sequenceDiagram
    actor Customer
    participant Order as Order Service
    participant Product as Product Service
    participant Inventory as Inventory Service

    Customer->>Order: POST /orders {customerId, productId, quantity} + optional Idempotency-Key
    Order->>Order: claim key + canonical request identity
    alt exact completed replay
        Order-->>Customer: 201 immutable creation-response snapshot
    else key reused with different payload
        Order-->>Customer: 409
    else new request
        Order->>Product: GET /products/{productId}
    alt product missing
        Product-->>Order: 404
        Order-->>Customer: 404
    else Product Service unreachable/timeout
        Product-->>Order: (timeout / error)
        Order-->>Customer: 502
    else product found
        Product-->>Order: 200 {price}
        Order->>Inventory: GET /inventory/{productId}
        alt inventory missing
            Inventory-->>Order: 404
            Order-->>Customer: 404
        else Inventory Service unreachable/timeout
            Inventory-->>Order: (timeout / error)
            Order-->>Customer: 502
        else inventory found
            Inventory-->>Order: 200 {quantity}
            alt quantity < requested
                Order-->>Customer: 409 insufficient inventory
            else quantity sufficient
                Order->>Inventory: PATCH /inventory/{productId} {quantityDelta: -requested}
                alt stock drained in the meantime
                    Inventory-->>Order: 409
                    Order-->>Customer: 409 insufficient inventory (no order created)
                else reduction fails
                    Inventory-->>Order: (non-200 / timeout)
                    Order-->>Customer: 502 (no order created)
                else reduction succeeds
                    Inventory-->>Order: 200
                    Order->>Order: atomically persist Order + immutable creation-response snapshot
                    Order-->>Customer: 201 order confirmation
                end
                end
            end
        end
    end
```

## Order cancellation (new slice, US-07)

```mermaid
sequenceDiagram
    actor Customer
    participant Order as Order Service
    participant Inventory as Inventory Service

    Customer->>Order: PATCH /orders/{id} {status: CANCELLED}
    Order->>Order: look up order by id
    alt order not found
        Order-->>Customer: 404
    else order already CANCELLED
        Order-->>Customer: 409
    else order is CONFIRMED
        Order->>Inventory: PATCH /inventory/{productId} {quantityDelta: +order.quantity}
        alt inventory missing
            Inventory-->>Order: 404
            Order-->>Customer: 404
        else restore fails
            Inventory-->>Order: (non-200 / timeout)
            Order-->>Customer: 502 (order status unchanged, stays CONFIRMED)
        else restore succeeds
            Inventory-->>Order: 200
            Order->>Order: set status = CANCELLED
            Order-->>Customer: 200 updated order
        end
    end
```

**Shared property, both flows:** the inventory update is a single atomic `PATCH` carrying a *delta*, not a
read-then-write of an absolute quantity. Inventory Service applies `quantityDelta` to its own stored value
and rejects the call with `409` if that would drive stock below zero, so concurrent creates and cancels for
the same product can no longer overwrite each other. The availability `GET` that still precedes order
creation is only there to produce a friendly pre-flight `409`; correctness rests on the `PATCH`.

Creation sends `order-create:{caller_key}` to Inventory and cancellation sends
`order-cancel:{order_id}`. For keyed creation, Order Service serializes the claim and result write in a
SQLite immediate transaction, so concurrent exact replays observe one persisted order and one inventory
adjustment. Replays read the immutable creation-response snapshot rather than the mutable order row, so a
later cancellation cannot change the original `CONFIRMED` response.

> Earlier revisions of this slice read the current quantity and wrote back an absolute value, which left a
> race window between the `GET` and the `PATCH`. That gap was closed during review remediation — see
> [review-findings.md](review-findings.md).
