#!/usr/bin/env bash
#
# compose_smoke.sh — end-to-end smoke test against the *composed* deployment.
#
# Verifies the checks a manual `docker compose up` session would perform:
#   1. all three services come up healthy (health-gated dependency order),
#   2. product -> inventory -> order E2E works across container boundaries,
#   3. Idempotency-Key replay leaves stock unchanged,
#   4. data survives a container restart (named SQLite volumes),
#   5. auth is enforced (401 without key, /health stays open).
#
# Usage (repo root):  bash scripts/compose_smoke.sh
# Exits non-zero on the first failed check; always tears down (keeps volumes).

set -euo pipefail

cd "$(dirname "$0")/.."

K="local-development-api-key"
PRODUCT_URL="http://localhost:8001"
INVENTORY_URL="http://localhost:8002"
ORDER_URL="http://localhost:8003"

fail() {
    echo "SMOKE FAIL: $*" >&2
    exit 1
}

pass() {
    echo "ok - $*"
}

cleanup() {
    docker compose down --remove-orphans
}
trap cleanup EXIT

echo "== building and starting the composed stack"
docker compose up -d --build

echo "== waiting for /health on all three services"
wait_until_ready() {
    local url="$1" name="$2"
    for _ in $(seq 1 60); do
        local code
        code=$(curl -s -o /dev/null -w '%{http_code}' "${url}/health") || true
        if [ "$code" = "200" ]; then
            pass "${name} healthy"
            return 0
        fi
        sleep 1
    done
    docker compose logs --no-color >&2 || true
    fail "${name} did not become healthy"
}
wait_until_ready "$PRODUCT_URL" "product"
wait_until_ready "$INVENTORY_URL" "inventory"
wait_until_ready "$ORDER_URL" "order"

echo "== auth checks"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$PRODUCT_URL/products" \
    -H 'Content-Type: application/json' -d '{"name":"x","category":"y","price":1}')
[ "$code" = "401" ] || fail "expected 401 without API key, got $code"
pass "resource endpoint rejects missing API key (401)"

code=$(curl -s -o /dev/null -w '%{http_code}' "$ORDER_URL/health")
[ "$code" = "200" ] || fail "expected 200 on unauthenticated /health, got $code"
pass "/health remains unauthenticated (200)"

echo "== cross-container E2E: product -> inventory -> order"
product_json=$(curl -s -X POST "$PRODUCT_URL/products" -H 'Content-Type: application/json' \
    -H "X-API-Key: $K" -d '{"name":"Smoke Widget","category":"tools","price":19.99}')
PID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$product_json") \
    || fail "product creation did not return an id"
pass "product created: $PID"

curl -s -X POST "$INVENTORY_URL/inventory" -H 'Content-Type: application/json' \
    -H "X-API-Key: $K" -d "{\"productId\":\"$PID\",\"warehouse\":\"WH-SMOKE\",\"quantity\":100}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d["quantity"]==100 else 1)' \
    || fail "inventory creation did not return quantity 100"
pass "inventory registered (qty 100)"

order_json=$(curl -s -X POST "$ORDER_URL/orders" -H 'Content-Type: application/json' \
    -H "X-API-Key: $K" -H 'Idempotency-Key: compose-smoke-1' \
    -d "{\"customerId\":\"smoke-cust\",\"productId\":\"$PID\",\"quantity\":3}")
ORDER_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$order_json") \
    || fail "order creation did not return an id"
pass "order created: $ORDER_ID"

stock=$(curl -s "$INVENTORY_URL/inventory/$PID" -H "X-API-Key: $K" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["quantity"])')
[ "$stock" = "97" ] || fail "expected stock 97 after order, got $stock"
pass "order reduced stock across container boundaries (100 -> 97)"

echo "== idempotent replay leaves stock unchanged"
replay_json=$(curl -s -X POST "$ORDER_URL/orders" -H 'Content-Type: application/json' \
    -H "X-API-Key: $K" -H 'Idempotency-Key: compose-smoke-1' \
    -d "{\"customerId\":\"smoke-cust\",\"productId\":\"$PID\",\"quantity\":3}")
replay_id=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$replay_json")
[ "$replay_id" = "$ORDER_ID" ] || fail "replay returned a different order id"
stock=$(curl -s "$INVENTORY_URL/inventory/$PID" -H "X-API-Key: $K" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["quantity"])')
[ "$stock" = "97" ] || fail "stock changed after idempotent replay: $stock"
pass "Idempotency-Key replay returned the same order, stock unchanged (97)"

echo "== persistence across container restart"
docker compose restart
wait_until_ready "$PRODUCT_URL" "product (after restart)"
wait_until_ready "$INVENTORY_URL" "inventory (after restart)"
wait_until_ready "$ORDER_URL" "order (after restart)"

stock=$(curl -s "$INVENTORY_URL/inventory/$PID" -H "X-API-Key: $K" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["quantity"])')
[ "$stock" = "97" ] || fail "stock wrong after restart: $stock"
orders=$(curl -s "$ORDER_URL/orders?limit=50" -H "X-API-Key: $K" \
    | python3 -c 'import json,sys; ids=[o["id"] for o in json.load(sys.stdin)]; sys.exit(0 if sys.argv[1] in ids else 1)' "$ORDER_ID") \
    || fail "created order missing after restart"
pass "data survived container restart (stock 97, order present)"

echo ""
echo "compose smoke: ALL CHECKS PASSED"
