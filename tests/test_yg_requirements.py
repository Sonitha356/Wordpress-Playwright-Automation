"""YG_001 - YG_010: header/logo, search and the "Your Items" mini-cart widget.

Reuses the project's own pieces: the pytest-playwright ``page`` fixture, ``clean_cart`` and the
failure-screenshot hook from conftest.py, and the helpers in utils/helpers.py. Results are turned into
YG_test_results.xlsx by utils/yg_excel_report.py.

Safety: the tests add products to the cart (removed again by ``clean_cart``) and open the Cart and
Checkout pages. They never fill in the checkout form and never click Place Order.

Cart-based tests start from an empty cart (fresh browser context) and add the products listed in
CART_PRODUCTS first, because "Your Items" is empty otherwise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, expect

from utils.helpers import (
    BASE_URL,
    assert_image_loaded,
    log_finding,
    money,
    normalize,
    parse_price,
    prices_equal,
)
from utils.yg_excel_report import BlockedError

# --- test data ---------------------------------------------------------------------------------------
SEARCH_TERM = "polo"  # the literal word "apparel" returns no products on this site (see YG_002)
PRICE_TEXT = re.compile(r"^\$\d{1,3}(?:,\d{3})*\.\d{2}$")


@dataclass
class CartProduct:
    name: str       # product title as shown in search results / product page
    size: str
    color: str
    qty: int
    # filled in while adding to the cart
    product_path: str = ""
    page_price: float = 0.0     # variation price shown on the product page
    extra: dict = field(default_factory=dict)

    @property
    def cart_name(self) -> str:
        """Mini-cart title: WooCommerce appends the size variation, e.g. 'Nike Dri-Fit Polo - Medium'."""
        return f"{self.name} - {self.size}"


CART_PRODUCTS = [
    CartProduct("Nike Dri-Fit Polo", size="Medium", color="Black", qty=2),
    CartProduct("Ogio Code Stretch Polo", size="Medium", color="Black Heather", qty=3),
]


# --- helpers -------------------------------------------------------------------------------------------
def goto(page: Page, url: str) -> None:
    """Navigate and turn load problems into BLOCKED (environment) rather than FAIL (behaviour)."""
    try:
        response = page.goto(url, wait_until="domcontentloaded")
    except PlaywrightError as exc:
        raise BlockedError(f"Could not load {url}: {str(exc).splitlines()[0]}") from exc
    if response is not None and response.status >= 400:
        raise BlockedError(f"{url} returned HTTP {response.status}")


def your_items(page: Page) -> Locator:
    """The footer 'Your Items' WooCommerce mini-cart widget."""
    return page.locator("section.widget_shopping_cart").filter(has_text="Your Items")


def search_widget(page: Page) -> Locator:
    """The footer 'Search Apparel' widget."""
    return page.locator("section.widget_product_search, section.widget_woocommerce_product_search").filter(
        has_text="Search Apparel"
    )


def cart_items(page: Page) -> Locator:
    return your_items(page).locator("li.mini_cart_item")


def item_by_name(page: Page, cart_name: str) -> Locator:
    return cart_items(page).filter(has=page.locator("a[href*='/product/']", has_text=cart_name))


def item_link(item: Locator) -> Locator:
    return item.locator("a[href*='/product/']").first


def item_qty(item: Locator) -> int:
    text = normalize(item.locator("span.quantity").inner_text())
    match = re.match(r"(\d+)", text)
    assert match, f"Could not read a quantity from mini-cart text {text!r}"
    return int(match.group(1))


def item_price_text(item: Locator) -> str:
    return normalize(item.locator("span.quantity .woocommerce-Price-amount").first.inner_text())


def item_attributes(item: Locator) -> dict[str, str]:
    """{'Color': 'Black'} from the <dl class="variation"> list."""
    attrs: dict[str, str] = {}
    dts = item.locator("dl.variation dt")
    dds = item.locator("dl.variation dd")
    for i in range(dts.count()):
        attrs[normalize(dts.nth(i).inner_text()).rstrip(":").strip()] = normalize(dds.nth(i).inner_text())
    return attrs


def add_product_to_cart(page: Page, product: CartProduct) -> None:
    """Find the product through the site search, choose size/colour/quantity and add it to the cart."""
    goto(page, f"{BASE_URL}/?s={quote(product.name)}&post_type=product")
    card = page.locator("li.product").filter(has_text=product.name).first
    try:
        expect(card).to_be_visible()
    except AssertionError as exc:
        raise BlockedError(f"Product {product.name!r} not found by search; cannot prepare the cart.") from exc
    card.locator("a").first.click()
    try:
        expect(page).to_have_url(re.compile(r"/product/"))
        product.product_path = urlparse(page.url).path

        for label, value in (("size", product.size), ("color", product.color)):
            row = page.locator("table.variations tr").filter(has_text=re.compile(label, re.I))
            row.locator("select").select_option(label=value)

        add_button = page.locator("button.single_add_to_cart_button")
        expect(add_button).not_to_have_class(re.compile(r"\bdisabled\b"))
        variation_price = page.locator(".woocommerce-variation-price .woocommerce-Price-amount").first
        expect(variation_price).to_be_visible()
        product.page_price = parse_price(variation_price.inner_text())

        page.locator("input.qty").fill(str(product.qty))
        add_button.click()

        # Waits (retrying across a page reload) until the item shows up in the footer widget.
        expect(item_by_name(page, product.cart_name)).to_have_count(1)
    except (AssertionError, PlaywrightError) as exc:
        raise BlockedError(
            f"Could not add {product.name} ({product.size}/{product.color}) to the cart: "
            f"{str(exc).splitlines()[0]}"
        ) from exc


# --- fixtures --------------------------------------------------------------------------------------------
@pytest.fixture
def home(page: Page) -> Page:
    goto(page, f"{BASE_URL}/")
    return page


@pytest.fixture
def cart_with_items(page: Page, clean_cart) -> list[CartProduct]:
    """Adds CART_PRODUCTS to an empty cart and returns to the home page ('Your Items' is in the footer)."""
    products = [CartProduct(p.name, p.size, p.color, p.qty) for p in CART_PRODUCTS]
    for product in products:
        add_product_to_cart(page, product)
    goto(page, f"{BASE_URL}/")
    try:
        expect(cart_items(page)).to_have_count(len(products))
    except AssertionError as exc:
        raise BlockedError("Cart did not contain the products just added.") from exc
    return products


# --- YG_001 - YG_002: logo and search -------------------------------------------------------------------
def test_YG_001_logo_verification(page: Page):
    goto(page, f"{BASE_URL}/shop/")  # start away from the home page so the redirect is meaningful
    logo_link = page.locator("div.logo a").first
    logo_image = logo_link.locator("img")
    assert_image_loaded(page, logo_image, "Website logo")

    logo_link.click()
    expect(page, "Clicking the logo should open the home page").to_have_url(
        re.compile(rf"^{re.escape(BASE_URL)}/?$")
    )
    assert "/shop" not in page.url, f"Still on the shop page after clicking the logo: {page.url}"
    expect(page.locator("div.logo a img"), "Logo should still be visible on the page it redirects to").to_be_visible()


def test_YG_002_search_apparel(home: Page):
    page = home
    widget = search_widget(page)
    expect(widget, "'Search Apparel' widget should be visible in the footer").to_be_visible()
    widget.locator("input[type='search']").fill(SEARCH_TERM)
    widget.get_by_role("button", name="Search").click()

    expect(page, "Search should open the product search results").to_have_url(
        re.compile(rf"[?&]s={SEARCH_TERM}\b", re.I)
    )
    results = page.locator("li.product")
    expect(results.first, f"At least one product should be listed for '{SEARCH_TERM}'").to_be_visible()
    count = results.count()
    irrelevant = [
        normalize(results.nth(i).inner_text())[:60]
        for i in range(count)
        if SEARCH_TERM.lower() not in results.nth(i).inner_text().lower()
    ]
    assert not irrelevant, f"Results not matching '{SEARCH_TERM}' were listed: {irrelevant}"

    # Observation only (not asserted): what the literal word "apparel" returns.
    goto(page, f"{BASE_URL}/?s=apparel&post_type=product")
    log_finding("YG_002", f"Literal search 'apparel' returned {page.locator('li.product').count()} product(s); "
                          f"'{SEARCH_TERM}' returned {count}.")


# --- YG_003 - YG_008: the "Your Items" widget -----------------------------------------------------------
def test_YG_003_view_products_in_your_items(cart_with_items: list[CartProduct], page: Page):
    widget = your_items(page)
    expect(widget.get_by_role("heading", name="Your Items"), "'Your Items' heading").to_be_visible()
    expect(cart_items(page), "Number of products listed in Your Items").to_have_count(len(cart_with_items))
    for product in cart_with_items:
        item = item_by_name(page, product.cart_name)
        expect(item, f"'{product.cart_name}' should be listed exactly once in Your Items").to_have_count(1)
        expect(item, f"'{product.cart_name}' row should be visible").to_be_visible()
    listed = [normalize(item_link(cart_items(page).nth(i)).inner_text()) for i in range(cart_items(page).count())]
    assert sorted(listed) == sorted(p.cart_name for p in cart_with_items), (
        f"Your Items lists {listed}, expected {[p.cart_name for p in cart_with_items]}"
    )


def test_YG_004_click_product_link(cart_with_items: list[CartProduct], page: Page):
    for product in cart_with_items:
        goto(page, f"{BASE_URL}/")
        item_link(item_by_name(page, product.cart_name)).click()
        expect(page, f"Clicking '{product.cart_name}' should open its product page").to_have_url(
            re.compile(re.escape(product.product_path))
        )
        actual_path = urlparse(page.url).path
        assert actual_path == product.product_path, (
            f"Expected product page {product.product_path} but landed on {actual_path}"
        )
        heading = page.get_by_role("heading", level=1).first
        expect(heading, f"Product page title for {product.name}").to_have_text(product.name)


def test_YG_005_product_image(cart_with_items: list[CartProduct], page: Page):
    for product in cart_with_items:
        item = item_by_name(page, product.cart_name)
        image = item.locator("img").first
        assert_image_loaded(page, image, f"Image of '{product.cart_name}'")
        alt = normalize(image.get_attribute("alt"))
        assert alt == product.cart_name, (
            f"Image alt text {alt!r} does not match the product {product.cart_name!r}"
        )
        # The image sits inside the link that opens the same product page as the title link.
        href_path = urlparse(item_link(item).get_attribute("href") or "").path
        image_link_path = urlparse(image.locator("xpath=ancestor::a[1]").get_attribute("href") or "").path
        assert image_link_path == product.product_path == href_path, (
            f"Image links to {image_link_path!r}, title links to {href_path!r}, expected {product.product_path!r}"
        )


def test_YG_006_attribute_and_quantity_listing(cart_with_items: list[CartProduct], page: Page):
    for product in cart_with_items:
        item = item_by_name(page, product.cart_name)
        attrs = item_attributes(item)
        assert attrs.get("Color") == product.color, (
            f"{product.cart_name}: expected Color {product.color!r} but Your Items shows {attrs}"
        )
        assert normalize(item_link(item).inner_text()).endswith(product.size), (
            f"{product.cart_name}: the chosen size {product.size!r} is not shown in the item title"
        )
        assert item_qty(item) == product.qty, (
            f"{product.cart_name}: expected quantity {product.qty} but Your Items shows {item_qty(item)}"
        )


def test_YG_007_price_listing(cart_with_items: list[CartProduct], page: Page):
    # Product pages show the price excluding tax; Your Items shows it "(incl. tax)". The tax rule is not
    # documented, so the check is: valid money format, not below the product-page price, and the same
    # implied tax factor for every product (no single price out of line).
    factors = {}
    for product in cart_with_items:
        text = item_price_text(item_by_name(page, product.cart_name))
        assert PRICE_TEXT.match(text), f"{product.cart_name}: price {text!r} is not in $0.00 format"
        price = parse_price(text)
        assert price > 0, f"{product.cart_name}: price {text} is not greater than zero"
        assert price >= product.page_price - 0.005, (
            f"{product.cart_name}: Your Items price {text} is lower than the product page price "
            f"{money(product.page_price)}"
        )
        factors[product.cart_name] = price / product.page_price
    log_finding("YG_007", "Implied Your Items / product-page price factor: "
                + ", ".join(f"{k}={v:.4f}" for k, v in factors.items()))
    values = list(factors.values())
    assert max(values) - min(values) < 0.002, (
        f"Prices are not consistent with the product pages (price factor differs per product): {factors}"
    )


def test_YG_008_subtotal(cart_with_items: list[CartProduct], page: Page):
    widget = your_items(page)
    subtotal_label = widget.locator("p.woocommerce-mini-cart__total")
    expect(subtotal_label, "Subtotal line should be visible in Your Items").to_be_visible()
    expect(subtotal_label).to_contain_text("Subtotal")
    shown = parse_price(subtotal_label.locator(".woocommerce-Price-amount").first.inner_text())

    expected = 0.0
    for product in cart_with_items:
        item = item_by_name(page, product.cart_name)
        expected += item_qty(item) * parse_price(item_price_text(item))
    assert prices_equal(shown, expected, tolerance=0.01), (
        f"Subtotal shown is {money(shown)} but sum of quantity x price of the listed items is {money(expected)}"
    )


# --- YG_009 - YG_010: View Cart and Checkout ------------------------------------------------------------
def test_YG_009_view_cart(cart_with_items: list[CartProduct], page: Page):
    your_items(page).get_by_role("link", name="View cart").click()
    expect(page, "View Cart should open the Cart page").to_have_url(re.compile(r"/cart/?(\?.*)?$"))
    cart_form = page.locator("form.woocommerce-cart-form")
    expect(cart_form, "Cart page should show the cart table").to_be_visible()
    for product in cart_with_items:
        expect(
            cart_form.get_by_role("link", name=re.compile(re.escape(product.name))).first,
            f"{product.name} should be listed on the Cart page",
        ).to_be_visible()


def test_YG_010_checkout(cart_with_items: list[CartProduct], page: Page):
    your_items(page).locator("a.checkout").click()
    expect(page, "Checkout should open the Checkout page").to_have_url(re.compile(r"/checkout/?(\?.*)?$"))
    expect(page.locator("form.checkout"), "Checkout form should be shown").to_be_visible()
    # Stops here on purpose: nothing is entered and Place Order is never clicked.
