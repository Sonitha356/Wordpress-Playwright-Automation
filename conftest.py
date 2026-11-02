"""Merged conftest: original project setup + fixtures for the YG_013-YG_039 shop/product suite."""
from __future__ import annotations

import base64
import os
from datetime import datetime

import pytest
from playwright.sync_api import Page, expect

from pages.base_page import BasePage
from pages.product_page import ProductPage
from pages.shop_page import ShopPage
from utils.helpers import (
    PRIMARY_PRODUCT,
    REPORT_DIR,
    SCREENSHOT_DIR,
    screenshot_name,
)
pytest_plugins = ["utils.yg_excel_report"]
print("conftest.py loaded")

# Only the new suite uses these; existing tests keep Playwright's defaults.
NEW_SUITE_FILES = {"test_shop.py", "test_product.py"}
EXPECT_TIMEOUT_MS = 10_000
ACTION_TIMEOUT_MS = 15_000
NAVIGATION_TIMEOUT_MS = 30_000
"test_yg_requirements.py"

def pytest_configure(config):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ---- original setup (unchanged): ignore HTTPS errors inside Playwright only ---------------------
@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    print("ignore_https_errors=True applied")
    return {
        **browser_context_args,
        "ignore_https_errors": True,
    }


# ---- new suite: timeouts + viewport, applied ONLY to test_shop.py / test_product.py ---------------
@pytest.fixture(autouse=True)
def _new_suite_defaults(request):
    if os.path.basename(str(request.node.fspath)) not in NEW_SUITE_FILES:
        yield
        return
    page: Page = request.getfixturevalue("page")
    page.set_viewport_size({"width": 1440, "height": 900})
    page.set_default_timeout(ACTION_TIMEOUT_MS)
    page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
    try:  # available in recent Playwright versions
        expect.set_options(timeout=EXPECT_TIMEOUT_MS)
    except AttributeError:
        pass
    yield


# ---- page-object fixtures ---------------------------------------------------------------------------
@pytest.fixture
def shop_page(page: Page) -> ShopPage:
    return ShopPage(page)


@pytest.fixture
def product_page(page: Page) -> ProductPage:
    """The primary product's detail page, reached by clicking through the shop (no hard-coded slug)."""
    return ShopPage(page).open_shop().open_product(PRIMARY_PRODUCT)


@pytest.fixture
def clean_cart(page: Page):
    """Removes cart items after tests that add to the cart. Never places an order."""
    yield
    BasePage(page).empty_cart()


# ---- screenshot on failure (original behaviour kept, YG tests get clean names + HTML report attach) ----
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when not in ("setup", "call") or not report.failed:
        return
    page = item.funcargs.get("page")
    if not page:
        return

    os.makedirs("screenshots", exist_ok=True)
    if "YG_" in item.name:
        filename = str(SCREENSHOT_DIR / screenshot_name(item.name))  # e.g. YG_026_price_by_size.png
    else:
        filename = os.path.join(
            "screenshots", f"{item.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
    try:
        page.screenshot(path=filename, full_page=True)
    except Exception as exc:  # page/browser may already be closed
        print(f"Could not take failure screenshot: {exc!r}")
        return
    print(f"Screenshot saved: {filename}")

    try:  # attach to the pytest-html report when the plugin is active
        from pytest_html import extras

        with open(filename, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode()
        extra_list = list(getattr(report, "extras", None) or getattr(report, "extra", None) or [])
        extra_list.append(extras.png(encoded, name=os.path.basename(filename)))
        report.extras = extra_list  # pytest-html >= 4
        report.extra = extra_list   # pytest-html 3.x
    except Exception:
        pass
