"""Elements and behaviour shared by every page (header menu, cart counter, notices, cart rows)."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page, expect

from utils.helpers import normalize, parse_price


class BasePage:
    PATH = "/"

    def __init__(self, page: Page):
        self.page = page
        # The theme (Enfold + Max Mega Menu) renders the menu twice (desktop + mobile); ':visible'
        # keeps only the one the user can actually see.
        self.menu_links = page.locator("ul.max-mega-menu > li.mega-menu-item > a.mega-menu-link:visible")
        # Header cart bubble. Updated asynchronously by WooCommerce cart fragments.
        self.cart_counter = page.locator(".av-cart-counter").first
        self.woo_notice = page.locator(".woocommerce-message")

    # ---- navigation ---------------------------------------------------------------
    def goto(self, path: str | None = None) -> None:
        self.page.goto(path or self.PATH, wait_until="domcontentloaded")

    @property
    def url_path(self) -> str:
        return urlparse(self.page.url).path

    def expect_path(self, path: str, message: str = "") -> None:
        expect(self.page, message or f"URL path should be {path}").to_have_url(
            re.compile(rf"^https?://[^/]+{re.escape(path.rstrip('/'))}/?(\?.*)?(#.*)?$")
        )

    # ---- header menu --------------------------------------------------------------
    def get_menu_items(self) -> list[dict]:
        expect(self.menu_links.first, "Header menu should be visible").to_be_visible()
        return self.menu_links.evaluate_all(
            "links => links.map(a => ({text: a.textContent.trim(), href: a.getAttribute('href')}))"
        )

    def menu_link(self, text: str) -> Locator:
        return self.menu_links.filter(has_text=re.compile(rf"^\s*{re.escape(text)}\s*$", re.I))

    # ---- cart ---------------------------------------------------------------------
    def cart_count(self) -> int:
        text = (self.cart_counter.text_content(timeout=5000) or "0").strip()
        return int(re.sub(r"\D", "", text) or 0)

    def expect_cart_count(self, expected: int) -> None:
        # Counter is refreshed asynchronously after add-to-cart, so rely on auto-retry.
        expect(self.cart_counter, f"Header cart counter should show {expected}").to_have_text(
            re.compile(rf"^\s*{expected}\s*$"), timeout=15_000
        )

    def cart_row(self, product_name: str) -> Locator:
        return self.page.locator("tr.cart_item").filter(
            has=self.page.locator(".product-name", has_text=product_name)
        )

    def read_cart_row(self, product_name: str) -> dict:
        """Parse a cart row into name / unit price / quantity / subtotal / variation dict."""
        row = self.cart_row(product_name).first
        expect(row, f"Cart should contain '{product_name}'").to_be_visible()
        terms = [normalize(t).rstrip(":").strip() for t in row.locator("dl.variation dt").all_text_contents()]
        values = [normalize(v) for v in row.locator("dl.variation dd").all_text_contents()]
        subtotal_text = normalize(row.locator(".product-subtotal").text_content())
        return {
            "name": normalize(row.locator(".product-name").text_content()),
            "unit_price": parse_price(row.locator(".product-price").text_content()),
            "quantity": int(row.locator("input.qty").input_value()),
            "subtotal_text": subtotal_text,
            "includes_tax": "incl. tax" in subtotal_text.lower(),
            "attributes": dict(zip(terms, values)),
        }

    def empty_cart(self) -> None:
        """Best-effort cleanup so test runs never leave items behind (never places an order)."""
        try:
            self.goto("/cart/")
            for _ in range(10):
                remove = self.page.locator("a.remove")
                if remove.count() == 0:
                    break
                remove.first.click()
                self.page.wait_for_load_state("domcontentloaded")
        except Exception as exc:  # cleanup must never mask the real test result
            print(f"Cart cleanup skipped: {exc!r}")
