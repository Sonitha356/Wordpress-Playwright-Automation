"""Shop page + product listing tests (YG_013 - YG_020)."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from pages.product_page import ProductPage
from pages.shop_page import ShopPage
from utils.helpers import (
    PRIMARY_PRODUCT,
    assert_image_loaded,
    detect_order,
    find_duplicates,
    image_stem,
    log_finding,
    normalize,
    parse_price,
)


# =========================================================================================
# Shop page
# =========================================================================================
def test_YG_013_sort_feature(shop_page: ShopPage):
    """Every sort option listed by the page is applied; Price/Name are verified for both directions."""
    shop_page.open_shop()
    options = shop_page.get_sort_option_names()
    assert options, "No sort options were found in the sort menu"
    baseline = sorted(shop_page.get_product_names())
    assert baseline, "Shop should list products before sorting"

    for option in options:
        shop_page.select_sort_option(option)
        assert shop_page.current_sort_option() == option, f"'{option}' should be marked as the current sort"
        products = shop_page.get_products()
        assert sorted(p.name for p in products) == baseline, (
            f"Sorting by '{option}' must not add/remove products"
        )

        key = option.lower()
        if key in ("price", "name"):
            def series(items):
                if key == "price":
                    return [p.min_price for p in items]
                return [p.name.casefold() for p in items]

            first = detect_order(series(products))
            assert first in ("asc", "desc"), (
                f"'{option}' sort should be monotonic but order was {first}: {series(products)}"
            )
            shop_page.toggle_sort_direction()
            second_products = shop_page.get_products()
            second = detect_order(series(second_products))
            assert {first, second} == {"asc", "desc"}, (
                f"Toggling direction for '{option}' should flip the order (got {first} then {second})"
            )
            assert sorted(p.name for p in second_products) == baseline
            # Make sure the lowest->highest / A->Z view was actually exercised and checked.
            ascending_view = products if first == "asc" else second_products
            values = series(ascending_view)
            assert values == sorted(values), f"'{option}' ascending view is not sorted: {values}"
        else:
            # Default Order / Date / Popularity have no visible sortable value on the card:
            # verify the page re-renders consistently (same products, same order on reload).
            before = shop_page.get_product_names()
            shop_page.page.reload(wait_until="domcontentloaded")
            shop_page.wait_for_products()
            assert shop_page.get_product_names() == before, f"'{option}' order should be stable on reload"


def test_YG_014_products_per_page(shop_page: ShopPage):
    """Displayed product count matches the configured per-page value; pagination behaves accordingly."""
    shop_page.open_shop()
    configured = shop_page.configured_per_page()
    assert configured > 0, "Configured products-per-page should be a positive number"
    offered = shop_page.get_per_page_options()
    assert configured in offered, f"Current per-page value {configured} should be one of {offered}"

    names = shop_page.get_product_names()
    assert not find_duplicates(names), f"Duplicate products on one page: {find_duplicates(names)}"
    assert 0 < len(names) <= configured, f"{len(names)} products shown but limit is {configured}"

    if len(names) < configured:
        assert not shop_page.has_pagination(), (
            "Fewer products than the per-page limit, so no pagination should be rendered"
        )
        log_finding(
            "YG_014",
            f"{len(names)} products total < {configured} per page: pagination (Next/Previous) is not rendered, "
            "so next/previous/duplicate-across-pages checks are not applicable on current data.",
        )
    else:
        # Full page -> more pages are expected. Walk them all and ensure no duplicates across pages.
        seen = list(names)
        guard = 0
        while shop_page.page.locator(".woocommerce-pagination a.next, a.next.page-numbers").count() and guard < 20:
            with shop_page.page.expect_navigation(wait_until="domcontentloaded"):
                shop_page.page.locator(".woocommerce-pagination a.next, a.next.page-numbers").first.click()
            shop_page.wait_for_products()
            page_names = shop_page.get_product_names()
            assert not set(page_names) & set(seen), "Same product appeared on two pages"
            seen += page_names
            guard += 1
        assert guard > 0, "A full first page should have a working Next link"
        with shop_page.page.expect_navigation(wait_until="domcontentloaded"):
            shop_page.page.locator(".woocommerce-pagination a.prev, a.prev.page-numbers").first.click()

    # Every other per-page option keeps showing the products that exist (never more than the limit).
    for count in [c for c in offered if c != configured]:
        shop_page.select_per_page(count)
        assert shop_page.configured_per_page() == count, f"Selecting '{count} products per page' was not applied"
        shown = shop_page.get_product_names()
        assert len(shown) == len(names) or len(shown) <= count
        assert not find_duplicates(shown)


def test_YG_015_header_menu_listing(shop_page: ShopPage):
    """Each visible header menu item is visible, enabled, clickable and lands on its own page."""
    shop_page.open_shop()
    items = shop_page.get_menu_items()
    assert len(items) >= 1, "Header menu has no visible items"
    expected_labels = {"home", "shop", "cart", "checkout", "my account"}
    assert {i["text"].lower() for i in items} >= expected_labels, (
        f"Expected menu items {expected_labels} but found {[i['text'] for i in items]}"
    )

    for item in items:
        shop_page.goto("/shop/")
        link = shop_page.menu_link(item["text"])
        expect(link, f"Menu item '{item['text']}' should be visible").to_be_visible()
        expect(link, f"Menu item '{item['text']}' should be enabled").to_be_enabled()
        with shop_page.page.expect_navigation(wait_until="domcontentloaded"):
            link.click()
        destination = re.sub(r"^https?://[^/]+", "", item["href"]).split("?")[0]
        if item["text"].lower() == "checkout":
            # WooCommerce may redirect an empty-cart checkout back to the cart; both are valid outcomes.
            assert shop_page.url_path.rstrip("/") in (destination.rstrip("/"), "/cart"), (
                f"Checkout opened unexpected page {shop_page.url_path}"
            )
        else:
            shop_page.expect_path(destination, f"'{item['text']}' should open {destination}")
        assert "error404" not in (shop_page.page.locator("body").get_attribute("class") or ""), (
            f"'{item['text']}' opened a 404 page"
        )
        assert normalize(shop_page.page.title()), f"'{item['text']}' page has an empty <title>"
        if item["text"].lower() != "home":
            slug = item["text"].lower().replace(" ", "-")
            assert slug in destination, f"Menu item '{item['text']}' should link to a '{slug}' URL, got {destination}"


# =========================================================================================
# Product listing
# =========================================================================================
def test_YG_016_product_image(shop_page: ShopPage):
    """Every listed product has a visible, fully loaded (non-broken) image; the primary one matches its page."""
    shop_page.open_shop()
    products = shop_page.get_products()
    assert products, "No products listed"
    for product in products:
        image = shop_page.product_image(product.name)
        assert_image_loaded(shop_page.page, image, f"Listing image of '{product.name}'")
        assert product.image_src, f"'{product.name}' has an empty image src"
        size = image.evaluate("i => [i.naturalWidth, i.naturalHeight]")
        assert min(size) >= 50, f"'{product.name}' image is suspiciously small: {size}"

    # Correspondence: the listing image must be one of the product page's own gallery images.
    primary_src = next(p.image_src for p in products if p.name == PRIMARY_PRODUCT)
    product_page = shop_page.open_product(PRIMARY_PRODUCT)
    gallery_hrefs = product_page.gallery.locator("a").evaluate_all("a => a.map(x => x.getAttribute('href') || '')")
    assert image_stem(primary_src) in {image_stem(h) for h in gallery_hrefs}, (
        f"Listing image '{image_stem(primary_src)}' is not part of the product gallery {gallery_hrefs}"
    )


def test_YG_017_product_name(shop_page: ShopPage):
    """Names are visible, non-empty, linked to a product page, and match that page's title."""
    shop_page.open_shop()
    products = shop_page.get_products()
    assert products, "No products listed"
    for product in products:
        assert product.name, "A product card has an empty name"
        expect(shop_page.product_title(product.name), f"Name '{product.name}' should be visible").to_be_visible()
        assert "/product/" in product.href, f"'{product.name}' is not linked to a product page: {product.href!r}"

    for product in products:
        shop_page.goto(product.href)
        detail = ProductPage(shop_page.page).wait_loaded()
        assert detail.title_text() == product.name, (
            f"Listing name '{product.name}' differs from product page title '{detail.title_text()}'"
        )


def test_YG_018_price_range(shop_page: ShopPage):
    """Listing shows a price range for variable products and it is consistent with the variation prices."""
    shop_page.open_shop()
    products = shop_page.get_products()
    assert products, "No products listed"
    for product in products:
        assert product.price_text.count("$") >= 1, f"'{product.name}' price has no currency: {product.price_text!r}"
        assert 0 < product.min_price <= product.max_price, f"'{product.name}' has an invalid range"

    for product in products:
        shop_page.goto(product.href)
        detail = ProductPage(shop_page.page).wait_loaded()
        variations = detail.get_variation_data()
        if not variations:
            log_finding("YG_018", f"'{product.name}' exposes no inline variation data; deep check skipped.")
            continue
        prices = [float(v["display_price"]) for v in variations]
        assert min(prices) - 0.005 <= product.min_price and product.max_price <= max(prices) + 0.005, (
            f"'{product.name}': listing range {product.min_price}-{product.max_price} is outside "
            f"variation prices {min(prices)}-{max(prices)}"
        )
        if product.name == PRIMARY_PRODUCT:  # strict equality for the primary product
            assert (min(prices), max(prices)) == (product.min_price, product.max_price)
            # Also compare with the range shown on the product page itself.
            assert detail.get_price_range() == (product.min_price, product.max_price)


def test_YG_019_page_redirection_to_details_page(shop_page: ShopPage):
    """Clicking the product image, then the product name, opens the matching details page."""
    shop_page.open_shop()
    listed = next(p for p in shop_page.get_products() if p.name == PRIMARY_PRODUCT)
    expected_path = re.sub(r"^https?://[^/]+", "", listed.href)

    for label, locator in (("image", shop_page.product_image(PRIMARY_PRODUCT)),
                           ("name", shop_page.product_title(PRIMARY_PRODUCT))):
        shop_page.goto("/shop/")
        with shop_page.page.expect_navigation(wait_until="domcontentloaded"):
            locator.click()
        shop_page.expect_path(expected_path, f"Clicking the product {label} should open {expected_path}")
        assert ProductPage(shop_page.page).wait_loaded().title_text() == PRIMARY_PRODUCT, (
            f"Product page opened via {label} shows the wrong product"
        )


def test_YG_020_select_options(shop_page: ShopPage):
    """'Select options' on every variable product opens its own details page with the variation form."""
    shop_page.open_shop()
    products = shop_page.get_products()
    assert products, "No products listed"
    for product in products:
        shop_page.goto("/shop/")
        button = shop_page.select_options_button(product.name)
        expect(button, f"'Select options' for '{product.name}' should be visible").to_be_visible()
        expect(button).to_have_text(re.compile("select options", re.I))
        with shop_page.page.expect_navigation(wait_until="domcontentloaded"):
            button.click()
        detail = ProductPage(shop_page.page).wait_loaded()
        shop_page.expect_path(re.sub(r"^https?://[^/]+", "", product.href))
        assert detail.title_text() == product.name, f"'Select options' opened '{detail.title_text()}' not '{product.name}'"
        expect(detail.form, "Variation form should be present for a variable product").to_be_visible()
        expect(detail.add_to_cart_button, "Add to cart is disabled until options are chosen").to_have_class(
            re.compile(r"\bdisabled\b")
        )
