"""Shop / category listing page object (Enfold theme + WooCommerce)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.sync_api import Locator, Page, expect

from pages.base_page import BasePage
from utils.helpers import normalize, parse_price


@dataclass
class ListedProduct:
    name: str
    href: str
    image_src: str
    min_price: float
    max_price: float
    price_text: str


class ShopPage(BasePage):
    PATH = "/shop/"

    def __init__(self, page: Page):
        super().__init__(page)
        self.product_cards = page.locator("ul.products li.product")
        self.pagination = page.locator(".woocommerce-pagination, .avia-pagination, nav.pagination")
        # The theme replaces the standard WooCommerce <select class="orderby"> with link lists.
        # Each menu is: ul.sort-param-xxx > li (label) > ul > li > a (options, shown on hover)
        self.sort_order_menu = page.locator("ul.sort-param-order > li").first
        self.sort_order_options = page.locator("ul.sort-param-order ul li a")
        self.sort_order_current = page.locator("ul.sort-param-order ul li.current-param")
        self.sort_direction_link = page.locator("ul.sort-param-sort a")
        self.per_page_menu = page.locator("ul.sort-param-count > li").first
        self.per_page_options = page.locator("ul.sort-param-count ul li a")
        self.per_page_current = page.locator("ul.sort-param-count ul li.current-param")

    # ---- navigation ---------------------------------------------------------------
    def open_shop(self) -> "ShopPage":
        self.goto(self.PATH)
        self.wait_for_products()
        return self

    def wait_for_products(self) -> None:
        expect(self.product_cards.first, "At least one product card should be visible").to_be_visible()

    def open_product(self, name: str):
        """Click the product title link (found by NAME, not position) and return its page object."""
        from pages.product_page import ProductPage

        link = self.product_link(name)
        expect(link, f"Product link for '{name}' should be visible").to_be_visible()
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            link.click()
        product = ProductPage(self.page)
        product.wait_loaded()
        return product

    # ---- product cards ------------------------------------------------------------
    def product_card(self, name: str) -> Locator:
        title = self.page.locator("h2.woocommerce-loop-product__title").filter(
            has_text=re.compile(rf"^\s*{re.escape(name)}\s*$")
        )
        return self.product_cards.filter(has=title)

    def product_link(self, name: str) -> Locator:
        return self.product_card(name).locator("a.woocommerce-LoopProduct-link")

    def product_title(self, name: str) -> Locator:
        return self.product_card(name).locator("h2.woocommerce-loop-product__title")

    def product_image(self, name: str) -> Locator:
        return self.product_card(name).locator("img").first

    def select_options_button(self, name: str) -> Locator:
        # Rendered as <a class="button product_type_variable" aria-label="Select options for “name”">
        return self.product_card(name).locator("a.button.product_type_variable")

    def get_products(self) -> list[ListedProduct]:
        self.wait_for_products()
        raw = self.product_cards.evaluate_all(
            """cards => cards.map(li => {
                const title = li.querySelector('h2.woocommerce-loop-product__title');
                const link = li.querySelector('a.woocommerce-LoopProduct-link');
                const img = li.querySelector('img');
                const price = li.querySelector('span.price');
                const amounts = [...li.querySelectorAll('span.price .woocommerce-Price-amount')]
                    .filter(e => !e.closest('del')).map(e => e.textContent.trim());
                return {name: title ? title.textContent : '',
                        href: link ? link.getAttribute('href') : '',
                        image: img ? (img.getAttribute('src') || '') : '',
                        amounts, priceText: price ? price.textContent : ''};
            })"""
        )
        products = []
        for item in raw:
            prices = [parse_price(a) for a in item["amounts"]] or [0.0]
            products.append(
                ListedProduct(
                    name=normalize(item["name"]),
                    href=item["href"],
                    image_src=item["image"],
                    min_price=min(prices),
                    max_price=max(prices),
                    price_text=normalize(item["priceText"]),
                )
            )
        return products

    def get_product_names(self) -> list[str]:
        return [p.name for p in self.get_products()]

    def get_product_price(self, name: str) -> tuple[float, float]:
        product = next(p for p in self.get_products() if p.name == name)
        return product.min_price, product.max_price

    # ---- sorting --------------------------------------------------------------------
    def _choose_from_menu(self, menu: Locator, options: Locator, label: "re.Pattern | str") -> None:
        pattern = label if isinstance(label, re.Pattern) else re.compile(rf"^\s*{re.escape(label)}\s*$")
        option = options.filter(has_text=pattern)
        menu.hover()  # options are only revealed on hover
        expect(option, f"Menu option {label!r} should become visible after hovering").to_be_visible()
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            option.click()
        self.wait_for_products()

    def get_sort_option_names(self) -> list[str]:
        self.sort_order_menu.wait_for(state="visible")
        return [normalize(t) for t in self.sort_order_options.all_text_contents() if normalize(t)]

    def select_sort_option(self, option_name: str) -> None:
        self._choose_from_menu(self.sort_order_menu, self.sort_order_options, option_name)

    def current_sort_option(self) -> str:
        return normalize(self.sort_order_current.text_content())

    def toggle_sort_direction(self) -> None:
        expect(self.sort_direction_link, "Sort direction link should be visible").to_be_visible()
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            self.sort_direction_link.click()
        self.wait_for_products()

    # ---- products per page ----------------------------------------------------------
    def get_per_page_options(self) -> list[int]:
        return [int(re.search(r"\d+", normalize(t)).group()) for t in self.per_page_options.all_text_contents()
                if re.search(r"\d+", t)]

    def configured_per_page(self) -> int:
        return int(re.search(r"\d+", normalize(self.per_page_current.text_content())).group())

    def select_per_page(self, count: int) -> None:
        self._choose_from_menu(self.per_page_menu, self.per_page_options, re.compile(rf"^\s*{count}\b"))

    def has_pagination(self) -> bool:
        return self.pagination.count() > 0 and self.pagination.first.is_visible()
