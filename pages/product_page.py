"""Single (variable) product page object.

Selectors below were taken from the live DOM:
  - variation selects:   select#size, select#color  (standard WooCommerce variations form)
  - Player Number:       input.wc-pao-addon-custom-text  (WooCommerce Product Add-Ons plugin)
  - add-on subtotal:     #product-addons-total .wc-pao-subtotal-line .amount
  - Clear link:          a.reset_variations
"""
from __future__ import annotations

import json
import re

from playwright.sync_api import Locator, Page, expect

from pages.base_page import BasePage
from utils.helpers import normalize, parse_price, poll_until, prices_equal, money


class ProductPage(BasePage):
    def __init__(self, page: Page):
        super().__init__(page)
        # summary
        self.title = page.locator("h1.product_title")
        self.price_range = page.locator("p.price:not(#product-addons-total p.price)").first
        self.variation_price = page.locator(".single_variation .woocommerce-Price-amount").first
        self.categories = page.locator(".product_meta .posted_in a")
        # variation form
        self.form = page.locator("form.variations_form")
        self.size_select = page.locator("form.variations_form select#size")
        self.color_select = page.locator("form.variations_form select#color")
        self.clear_link = page.locator("a.reset_variations")
        self.variation_id = page.locator("form.variations_form input.variation_id")
        self.add_to_cart_button = page.locator("button.single_add_to_cart_button")
        self.quantity = page.locator("form.cart input.qty")
        # Product Add-Ons (Player Number)
        self.player_number = page.locator("input.wc-pao-addon-custom-text")
        self.addon_totals = page.locator("#product-addons-total")
        self.addon_line_amount = page.locator("#product-addons-total li:has(.wc-pao-addon-name) .wc-pao-col2 .amount")
        self.addon_line_name = page.locator("#product-addons-total .wc-pao-addon-name")
        self.addon_line_value = page.locator("#product-addons-total .wc-pao-addon-value")
        self.subtotal_amount = page.locator("#product-addons-total .wc-pao-subtotal-line .amount")
        # gallery
        self.gallery = page.locator(".woocommerce-product-gallery")
        self.main_image = page.locator(".woocommerce-product-gallery__wrapper > a img.attachment-shop_single").first
        self.thumbnail_links = page.locator(".woocommerce-product-gallery .thumbnails a")
        # tabs
        self.tab_description = page.locator(".woocommerce-tabs ul.tabs li.description_tab a")
        self.tab_additional = page.locator(".woocommerce-tabs ul.tabs li.additional_information_tab a")
        self.tab_reviews = page.locator(".woocommerce-tabs ul.tabs li.reviews_tab a")
        self.panel_description = page.locator("#tab-description")
        self.panel_additional = page.locator("#tab-additional_information")
        self.panel_reviews = page.locator("#tab-reviews")
        self.attributes_table = page.locator("table.woocommerce-product-attributes")
        # reviews
        self.reviews = page.locator("#reviews")
        self.review_items = page.locator("#reviews ol.commentlist > li")
        self.review_form_wrapper = page.locator("#review_form")
        self.review_login_message = page.locator("#reviews").get_by_text(re.compile("must be logged in", re.I))
        # related + prev/next product navigation
        self.related_section = page.locator("section.related.products")
        self.related_cards = page.locator("section.related.products li.product")
        self.nav_prev = page.locator("a.avia-post-nav.avia-post-prev")
        self.nav_next = page.locator("a.avia-post-nav.avia-post-next")

    # ---- loading ------------------------------------------------------------------
    def wait_loaded(self) -> "ProductPage":
        expect(self.title, "Product title should be visible").to_be_visible()
        return self

    def title_text(self) -> str:
        return normalize(self.title.text_content())

    # ---- variation data (from the form's own data attribute, used to cross-check the UI) ----
    def get_variation_data(self) -> list[dict]:
        raw = self.form.get_attribute("data-product_variations")
        if not raw or raw == "false":
            return []
        return json.loads(raw)

    # ---- options --------------------------------------------------------------------
    def _select_for(self, attribute: str) -> Locator:
        return {"size": self.size_select, "color": self.color_select}[attribute]

    def get_available_options(self, attribute: str) -> list[str]:
        select = self._select_for(attribute)
        expect(select, f"{attribute} select should be visible").to_be_visible()
        return select.evaluate("s => [...s.options].filter(o => o.value && !o.disabled).map(o => o.value)")

    def select_size(self, size: str) -> None:
        self.size_select.select_option(value=size)
        expect(self.size_select, f"Size '{size}' should be selected").to_have_value(size)

    def select_color(self, color: str) -> None:
        self.color_select.select_option(value=color)
        expect(self.color_select, f"Color '{color}' should be selected").to_have_value(color)

    def select_variation(self, size: str, color: str) -> None:
        self.select_size(size)
        self.select_color(color)
        self.wait_for_variation_selected()

    def selected_size(self) -> str:
        return self.size_select.input_value()

    def selected_color(self) -> str:
        return self.color_select.input_value()

    def wait_for_variation_selected(self) -> None:
        expect(self.variation_price, "Variation price should appear once size+color are chosen").to_be_visible()
        expect(self.add_to_cart_button, "Add to cart should be enabled for a valid variation").not_to_have_class(
            re.compile(r"\bdisabled\b")
        )
        expect(self.variation_id, "A variation_id should be set").not_to_have_value("")

    # ---- prices ---------------------------------------------------------------------
    def get_price_range(self) -> tuple[float, float]:
        text = self.price_range.text_content(timeout=5000)
        amounts = [parse_price(a) for a in re.findall(r"\$\s?[\d,]+(?:\.\d+)?", text or "")]
        assert amounts, f"No price found in top price element: {text!r}"
        return min(amounts), max(amounts)

    def get_product_price(self) -> float:
        """Current variation price (valid once a variation is selected)."""
        expect(self.variation_price).to_be_visible()
        return parse_price(self.variation_price.text_content(timeout=5000))

    def wait_for_variation_price(self, expected: float, message: str = "") -> float:
        return poll_until(
            self.page, self.get_product_price, lambda v: prices_equal(v, expected),
            message=message or f"Variation price should become {money(expected)}",
        )

    def get_subtotal(self) -> float:
        expect(self.subtotal_amount, "Add-on subtotal should be visible").to_be_visible()
        return parse_price(self.subtotal_amount.text_content(timeout=5000))

    def wait_for_subtotal(self, expected: float, message: str = "") -> float:
        return poll_until(
            self.page, self.get_subtotal, lambda v: prices_equal(v, expected),
            message=message or f"Subtotal should become {money(expected)}",
        )

    def get_player_number_charge(self) -> float:
        expect(self.addon_line_amount, "Player Number charge line should be visible").to_be_visible()
        return parse_price(self.addon_line_amount.text_content(timeout=5000))

    # ---- player number / clear / add to cart -------------------------------------------
    def enter_player_number(self, value: str) -> None:
        expect(self.player_number, "Player Number field should be visible").to_be_visible()
        self.player_number.fill(value)
        self.player_number.blur()  # plugin recalculates on input/change

    def clear_player_number(self) -> None:
        self.player_number.fill("")
        self.player_number.blur()

    def click_clear(self) -> None:
        expect(self.clear_link, "Clear link should be visible").to_be_visible()
        self.clear_link.click()

    def add_to_cart(self) -> None:
        expect(self.add_to_cart_button, "Add to cart button should be enabled").to_be_enabled()
        self.add_to_cart_button.click()

    def expect_added_notice(self, product_name: str) -> None:
        notice = self.woo_notice.first
        expect(notice, "WooCommerce success notice should be visible").to_be_visible(timeout=15_000)
        expect(notice).to_contain_text("has been added to your cart")
        expect(notice, "Notice should name the product that was added").to_contain_text(product_name)
        expect(notice.get_by_role("link", name=re.compile("view cart", re.I)), "'View cart' link").to_be_visible()

    # ---- tabs -------------------------------------------------------------------------
    def open_tab(self, tab: Locator, panel: Locator) -> None:
        expect(tab, "Tab should be visible").to_be_visible()
        tab.click()
        expect(panel, "Tab panel should be visible after clicking its tab").to_be_visible()

    # ---- gallery ----------------------------------------------------------------------
    def main_image_src(self) -> str:
        return self.main_image.get_attribute("src") or ""

    # ---- misc -------------------------------------------------------------------------
    def category_links(self) -> list[dict]:
        expect(self.categories.first, "Category links should be visible").to_be_visible()
        return self.categories.evaluate_all(
            "links => links.map(a => ({text: a.textContent.trim(), href: a.getAttribute('href')}))"
        )
