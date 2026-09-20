"""End-to-end walkthrough of all three services through their Swagger UI.

Drives a real Chromium browser exactly the way a human would test manually:
open ``/docs``, hit Authorize with the API key, expand an operation, click
Try it out, fill the form, click Execute, and assert on the rendered response.

This starts real services (see ``conftest.py``) and talks to them over real
HTTP, so it exercises the order-service->product/inventory client chain too.

Options (env vars):
  BROWSER_HEADLESS   default ``1``; set ``0`` to watch a live Chromium window
  BROWSER_SLOWMO     ms per Playwright action (default 0); e.g. 500 to slow down
  BROWSER_VIDEO      set ``1`` to record a WebM next to this file

Requires: ``pip install playwright && python -m playwright install chromium``
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright")
from playwright.sync_api import Page, sync_playwright

SHOTS = Path(__file__).with_name("artifacts")
VIDEO_DIR = Path(__file__).with_name("video")

pytestmark = pytest.mark.browser


def _step_delay() -> int:
    """Base pause between steps so live/video runs stay readable."""
    return 700 if int(os.getenv("BROWSER_SLOWMO", "0")) > 0 else 200


def _opblock(page: Page, op_id: str):
    return page.locator(f"div[id$='{op_id}']").first


def _authorize(page: Page, api_key: str) -> None:
    page.click("button.authorize")
    page.wait_for_timeout(300)
    page.fill("#api_key_value", api_key)
    page.click(".auth-wrapper .modal-btn.authorize")
    page.wait_for_timeout(200)
    page.click(".auth-wrapper .btn-done")
    page.wait_for_timeout(300)


def _ensure_expanded(page: Page, op_id: str) -> None:
    btn = _opblock(page, op_id).locator(".opblock-summary-control")
    if btn.get_attribute("aria-expanded") == "false":
        btn.click()
        page.wait_for_timeout(_step_delay())


def _try_out(page: Page, op_id: str) -> None:
    ob = _opblock(page, op_id)
    if ob.locator("button.btn.execute").count() > 0:
        return  # already in try-it-out mode
    ob.locator(".try-out__btn:not(.cancel):not(.reset)").first.click()
    page.wait_for_timeout(_step_delay())


def _fill_path_param(page: Page, op_id: str, attr: str, value: str) -> None:
    _ensure_expanded(page, op_id)
    _opblock(page, op_id).locator(f"input[placeholder='{attr}']").first.fill(value)


def _fill_body(page: Page, op_id: str, payload: dict) -> None:
    _ensure_expanded(page, op_id)
    _opblock(page, op_id).locator(".opblock-body textarea").first.fill(json.dumps(payload))


def _execute(page: Page, op_id: str) -> None:
    _ensure_expanded(page, op_id)
    _opblock(page, op_id).locator("button.btn.execute").click()
    page.wait_for_selector(f"div[id$='{op_id}'] .live-responses-table .response", timeout=10000)
    page.wait_for_timeout(_step_delay())


def _response(page: Page, op_id: str) -> tuple[str, str]:
    """(status_code_text, rendered_body_text) of the latest live response."""
    cur = _opblock(page, op_id).locator(".live-responses-table .response").last
    code = cur.locator(".response-col_status").first.inner_text().strip()
    hc = cur.locator(".highlight-code")
    body = hc.first.inner_text().strip() if hc.count() else ""
    return code, body


def _json_body(body: str) -> dict:
    """Parse the rendered response JSON; the UI prefixes it with 'Download '."""
    cleaned = body.removeprefix("Download").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"rendered body is not JSON: {cleaned[:200]}") from exc
    assert isinstance(parsed, dict), f"expected JSON object, got {type(parsed).__name__}"
    return parsed


def _shot(page: Page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"))


def _extract_id(body: str) -> str:
    match = re.search(r'"id"\s*:\s*"([^"]+)"', body)
    assert match, f"no id found in rendered response: {body[:200]}"
    return match.group(1)


def _http_get_json(url: str, api_key: str) -> dict:
    """Plain HTTP GET with the test API key (for cross-service invariants)."""
    request = urllib.request.Request(url, headers={"X-API-Key": api_key})
    with urllib.request.urlopen(request, timeout=10) as resp:
        return json.loads(resp.read())


def _public_or_local(services: dict[str, str], name: str) -> str:
    public = services.get("public", {})
    return f"{public[name]}/docs" if name in public else f"{services[name]}/docs (local)"


def test_swagger_ui_walkthrough(services: dict[str, str]) -> None:
    """Full manual-style walkthrough: products -> inventory -> orders, with
    200/201 happy paths, 404, 422 and 409 cases, all asserted from the UI."""
    api_key = services["api_key"]
    headless = os.getenv("BROWSER_HEADLESS", "1") != "0"
    slowmo = int(os.getenv("BROWSER_SLOWMO", "0"))
    record_video = os.getenv("BROWSER_VIDEO", "0") == "1"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless, slow_mo=slowmo, args=["--no-sandbox"])
        context_kwargs: dict[str, object] = {"viewport": {"width": 1550, "height": 1150}, "device_scale_factor": 1}
        if record_video:
            VIDEO_DIR.mkdir(parents=True, exist_ok=True)
            context_kwargs["record_video_dir"] = str(VIDEO_DIR)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        try:
            # ---------------- PRODUCT SERVICE ----------------
            page.goto(f"{services['product']}/docs")
            page.wait_for_selector("#operations")
            _authorize(page, api_key)
            _shot(page, "01_product_authorized")

            op = "list_products_products_get"
            _ensure_expanded(page, op)
            _try_out(page, op)
            _execute(page, op)
            _shot(page, "02_product_get_list")
            code, body = _response(page, op)
            assert code.startswith("200"), f"GET /products: {code}"

            op = "create_product_products_post"
            _ensure_expanded(page, op)
            _try_out(page, op)
            _fill_body(page, op, {"name": "Browser Espresso Kit", "category": "kitchen", "price": 34.5})
            _execute(page, op)
            _shot(page, "03_product_create_201")
            code, body = _response(page, op)
            assert code.startswith("201"), f"POST /products: {code} {body[:150]}"
            pid = _extract_id(body)

            op = "get_product_products__product_id__get"
            _ensure_expanded(page, op)
            _try_out(page, op)
            _fill_path_param(page, op, "product_id", pid)
            _execute(page, op)
            _shot(page, "04_product_get_id")
            code, body = _response(page, op)
            assert code.startswith("200") and pid in body, f"GET /products/{{id}}: {code}"

            _fill_path_param(page, op, "product_id", "nope-missing")
            _execute(page, op)
            _shot(page, "05_product_get_404")
            code, body = _response(page, op)
            assert code.startswith("404"), f"GET missing product: {code}"

            op = "create_product_products_post"
            _ensure_expanded(page, op)
            _try_out(page, op)
            _fill_body(page, op, {"name": "", "price": -1})
            _execute(page, op)
            _shot(page, "06_product_create_422")
            code, body = _response(page, op)
            assert code.startswith("422"), f"POST invalid product: {code}"

            # ---------------- INVENTORY SERVICE ----------------
            page.goto(f"{services['inventory']}/docs")
            page.wait_for_selector("#operations")
            _authorize(page, api_key)

            op = "create_inventory_inventory_post"
            _ensure_expanded(page, op)
            _try_out(page, op)
            _fill_body(page, op, {"productId": pid, "warehouse": "WH-WEB", "quantity": 40})
            _execute(page, op)
            _shot(page, "07_inventory_create_201")
            code, body = _response(page, op)
            assert code.startswith("201"), f"POST /inventory: {code} {body[:150]}"
            assert _json_body(body)["quantity"] == 40, f"POST /inventory: {body[:150]}"

            op = "update_inventory_inventory__product_id__patch"
            _ensure_expanded(page, op)
            _try_out(page, op)
            _fill_path_param(page, op, "product_id", pid)
            _fill_body(page, op, {"quantityDelta": 10})
            _execute(page, op)
            _shot(page, "08_inventory_delta_200")
            code, body = _response(page, op)
            assert code.startswith("200"), f"PATCH delta +10: {code}"
            assert _json_body(body)["quantity"] == 50, f"PATCH delta +10: {body[:150]}"

            _fill_body(page, op, {"quantityDelta": -999})
            _execute(page, op)
            _shot(page, "09_inventory_delta_409")
            code, body = _response(page, op)
            assert code.startswith("409") and "Insufficient inventory" in body, f"PATCH -999: {code}"

            # ---------------- ORDER SERVICE ----------------
            page.goto(f"{services['order']}/docs")
            page.wait_for_selector("#operations")
            _authorize(page, api_key)

            op = "create_order_orders_post"
            _ensure_expanded(page, op)
            _try_out(page, op)
            _fill_body(page, op, {"customerId": "web-user", "productId": pid, "quantity": 2})
            _execute(page, op)
            _shot(page, "10_order_create_201")
            code, body = _response(page, op)
            assert code.startswith("201"), f"POST /orders: {code} {body[:150]}"
            order = _json_body(body)
            assert order["status"] == "CONFIRMED", f"order not CONFIRMED: {order}"
            assert order["totalPrice"] == 69, f"totalPrice wrong: {order['totalPrice']}"
            oid = _extract_id(body)

            # stock must have dropped 50 -> 48 across services (plain HTTP here:
            # the browser is on the Order Service UI, not the Inventory UI)
            stock = _http_get_json(f"{services['inventory']}/inventory/{pid}", api_key)["quantity"]
            assert stock == 48, f"stock after order (want 48): {stock}"

            _fill_body(page, op, {"customerId": "web-user", "productId": pid, "quantity": 9999})
            _execute(page, op)
            _shot(page, "11_order_create_409")
            code, body = _response(page, op)
            assert code.startswith("409"), f"POST /orders over stock: {code}"

            op = "update_order_status_orders__order_id__patch"
            _ensure_expanded(page, op)
            _try_out(page, op)
            _fill_path_param(page, op, "order_id", oid)
            _fill_body(page, op, {"status": "CANCELLED"})
            _execute(page, op)
            _shot(page, "12_order_cancel_200")
            code, body = _response(page, op)
            assert code.startswith("200"), f"PATCH cancel: {code}"
            assert _json_body(body)["status"] == "CANCELLED", f"PATCH cancel: {body[:150]}"

            op = "get_order_orders__order_id__get"
            _ensure_expanded(page, op)
            _try_out(page, op)
            _fill_path_param(page, op, "order_id", oid)
            _execute(page, op)
            _shot(page, "13_order_get_final")
            code, body = _response(page, op)
            assert code.startswith("200"), f"GET final order: {code}"
            assert _json_body(body)["status"] == "CANCELLED", f"GET final order: {body[:150]}"

            # stock restored 48 -> 50 (plain HTTP; browser is on the Order UI)
            stock = _http_get_json(f"{services['inventory']}/inventory/{pid}", api_key)["quantity"]
            assert stock == 50, f"stock after cancel (want 50): {stock}"

            view_pause = int(os.getenv("BROWSER_VIEW_PAUSE_SECONDS", "0"))
            if view_pause > 0:
                print(
                    f"\n[view] test done — the services (and their public tunnels, if any) "
                    f"stay up for {view_pause}s for manual browsing. Press Ctrl+C only if "
                    "you want to abort.\n"
                    "  product docs  : " + _public_or_local(services, "product"),
                    flush=True,
                )
                print("  inventory docs: " + _public_or_local(services, "inventory"), flush=True)
                print("  order docs    : " + _public_or_local(services, "order"), flush=True)
                remaining = view_pause
                while remaining > 0:
                    remaining -= 5
                    time.sleep(min(5, max(remaining, 0)))
        finally:
            context.close()
            browser.close()
