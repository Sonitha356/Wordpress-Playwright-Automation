"""Product details page tests (YG_021 - YG_039). Primary product: see utils.helpers.PRIMARY_PRODUCT."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from pages.product_page import ProductPage
from pages.shop_page import ShopPage
from utils.helpers import (
    NOT_AUTOMATABLE,
    PLAYER_NUMBER_FEE,
    PLAYER_NUMBER_VALUE,
    PRIMARY_PRODUCT,
    assert_image_loaded,
    assert_price_equal,
    log_finding,
    money,
    normalize,
    parse_price,
    poll_until,
)

DISABLED = re.compile(r"\bdisabled\b")
SLIDER_SELECTORS = (
    ".slick-slider, .swiper, .swiper-container, .owl-carousel, .flickity-slider, "
    ".avia-slideshow, .bx-wrapper, .splide"
)


# ---------------------------------------------------------------------------------------------
# local helpers
# ---------------------------------------------------------------------------------------------
def expected_variation_price(pp: ProductPage, size: str, color: str) -> float:
    """Price the site itself publishes (form data attribute) for a size/color combination."""
    for variation in pp.get_variation_data():
        attrs = variation["attributes"]
        if attrs.get("attribute_size", "") in ("", size) and attrs.get("attribute_color", "") in ("", color):
            return float(variation["display_price"])
    raise AssertionError(f"No variation published for size={size!r}, color={color!r}")


def first_color(pp: ProductPage) -> str:
    colors = pp.get_available_options("color")
    assert colors, "Product should offer at least one color"
    return colors[0]


def assert_cart_price(cart_price: float, expected: float, includes_tax: bool) -> None:
    """The cart displays prices incl. tax on this site (e.g. $51.00 -> $54.06); accept that explicitly."""
    if prices_close(cart_price, expected):
        return
    assert includes_tax, f"Cart price {money(cart_price)} != expected {money(expected)} and no tax note shown"
    assert expected < cart_price <= expected * 1.25, (
        f"Cart price {money(cart_price)} is not a plausible tax-inclusive version of {money(expected)}"
    )
    log_finding(
        "CART",
        f"Cart shows tax-inclusive price {money(cart_price)} vs {money(expected)} on the product page "
        f"(implied rate {cart_price / expected - 1:.2%}).",
    )


def prices_close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.005


# =============================================================================================
# YG_021 - YG_024: image, name, price, description
# =============================================================================================
def test_YG_021_product_image_and_gallery(product_page: ProductPage):
    pp, page = product_page, product_page.page
    assert_image_loaded(page, pp.main_image, "Main product image")

    count = pp.thumbnail_links.count()
    assert count >= 1, "Gallery should contain thumbnails"
    for i in range(count):
        thumb = pp.thumbnail_links.nth(i)
        assert_image_loaded(page, thumb.locator("img"), f"Gallery thumbnail #{i + 1}")
        href = thumb.get_attribute("href")
        assert href, f"Thumbnail #{i + 1} has no full-size image link"
        response = page.request.get(href)
        assert response.ok, f"Full-size gallery image #{i + 1} returned HTTP {response.status}: {href}"

    # Thumbnail click: the site may swap the main image, open a lightbox or navigate to the file.
    target = pp.thumbnail_links.nth(1 if count > 1 else 0)
    before_src, before_url = pp.main_image_src(), page.url
    target.scroll_into_view_if_needed()
    target.click()
    lightbox = page.locator(".mfp-wrap, .mfp-container, .mfp-img, .pswp, .avia-popup").first

    def reaction() -> dict:
        return {
            "main_image_changed": pp.main_image_src() != before_src,
            "lightbox_opened": lightbox.is_visible(),
            "navigated": page.url != before_url,
        }

    state = poll_until(
        page, reaction, lambda s: any(s.values()), timeout_ms=6000,
        message="Clicking a gallery thumbnail produced no observable change "
                "(main image unchanged, no lightbox, no navigation)",
    )
    log_finding("YG_021", f"Thumbnail click behaviour observed: {state}")


def test_YG_022_product_name(product_page: ProductPage):
    expect(product_page.title, "Product title should be visible").to_be_visible()
    assert product_page.title_text(), "Product title must not be empty"
    assert product_page.title_text() == PRIMARY_PRODUCT, "Title does not match the product selected in the shop"
    expect(product_page.page, "Browser tab title should contain the product name").to_have_title(
        re.compile(re.escape(PRIMARY_PRODUCT))
    )


def test_YG_023_product_price(product_page: ProductPage):
    pp = product_page
    low, high = pp.get_price_range()
    assert "$" in normalize(pp.price_range.text_content()), "Price must show the $ currency symbol"
    assert 0 < low <= high, f"Invalid price range {low}-{high}"

    sizes, color = pp.get_available_options("size"), first_color(pp)
    pp.select_color(color)
    for size in sizes:
        pp.select_size(size)
        expected = expected_variation_price(pp, size, color)
        pp.wait_for_variation_price(expected, f"Variation price for {size}/{color}")
        assert low - 0.005 <= expected <= high + 0.005, f"{size} price {expected} is outside range {low}-{high}"
        assert normalize(pp.variation_price.text_content()).startswith("$"), "Variation price lacks currency"

    # Sale price: only meaningful if the variation data says something is on sale.
    on_sale = [v for v in pp.get_variation_data()
               if float(v.get("display_regular_price", v["display_price"])) > float(v["display_price"])]
    if on_sale:
        pp.select_size(on_sale[0]["attributes"]["attribute_size"] or sizes[0])
        pp.select_color(color)
        expect(pp.page.locator(".single_variation del"), "Regular (struck-through) price").to_be_visible()
        expect(pp.page.locator(".single_variation ins"), "Sale price").to_be_visible()
    else:
        log_finding("YG_023", "No variation is on sale: sale-price display not applicable.")


def test_YG_024_description(product_page: ProductPage):
    pp = product_page
    expect(pp.panel_description, "Description panel is shown by default").to_be_visible()
    text = normalize(pp.panel_description.text_content())
    assert len(text) > 20, f"Description looks empty or too short: {text!r}"
    assert pp.panel_description.locator("li, p").count() > 0, "Description should contain paragraphs or bullet points"


# =============================================================================================
# YG_025 - YG_030: variations, player number, clear
# =============================================================================================
def test_YG_025_size_and_color(product_page: ProductPage):
    pp = product_page
    sizes, colors = pp.get_available_options("size"), pp.get_available_options("color")
    assert sizes and colors, f"Expected size and color options, got sizes={sizes}, colors={colors}"
    expect(pp.add_to_cart_button, "Add to cart is disabled before any selection").to_have_class(DISABLED)

    for size in sizes:
        for color in colors:
            pp.select_variation(size, color)
            assert pp.selected_size() == size and pp.selected_color() == color, "Selected state not retained"
            assert pp.variation_id.input_value(), f"{size}/{color} did not resolve to a variation"


def test_YG_026_price_by_size(product_page: ProductPage):
    pp = product_page
    color = first_color(pp)
    pp.select_color(color)
    range_before = pp.get_price_range()
    results = []
    for size in pp.get_available_options("size"):
        pp.select_size(size)
        expected = expected_variation_price(pp, size, color)
        after = pp.wait_for_variation_price(expected, f"Price should update after selecting size {size}")
        results.append((size, after))
        log_finding("YG_026", f"before(range)={range_before} size={size} after={money(after)}")

    distinct = {price for _, price in results}
    if len(distinct) == 1:
        log_finding("YG_026", f"All sizes share one price ({money(distinct.pop())}); nothing to compare.")
        return
    cheapest = min(results, key=lambda r: r[1])
    priciest = max(results, key=lambda r: r[1])
    assert cheapest[1] < priciest[1]
    # Switch from the cheapest to the most expensive size and confirm the displayed price really moved.
    pp.select_size(cheapest[0])
    pp.wait_for_variation_price(cheapest[1])
    pp.select_size(priciest[0])
    pp.wait_for_variation_price(priciest[1], f"Price should change from {money(cheapest[1])} when picking {priciest[0]}")


def test_YG_027_player_number(product_page: ProductPage):
    pp = product_page
    pp.select_variation(pp.get_available_options("size")[0], first_color(pp))
    expect(pp.player_number, "Player Number field should be visible").to_be_visible()
    expect(pp.page.get_by_text(re.compile(r"Add Your Player Number \(\$3\.00\)")).first).to_be_visible()

    pp.enter_player_number(PLAYER_NUMBER_VALUE)
    expect(pp.addon_line_name).to_contain_text("Player Number")
    expect(pp.addon_line_value, "Entered number should be echoed in the totals").to_have_text(PLAYER_NUMBER_VALUE)
    assert_price_equal(pp.get_player_number_charge(), PLAYER_NUMBER_FEE, "Player Number charge:")

    # Emptying the field must remove the charge again.
    pp.clear_player_number()
    poll_until(pp.page, pp.addon_line_amount.count, lambda n: n == 0,
               message="Player Number charge should disappear when the field is emptied")

    # Validation: only assert it if the plugin actually declares restrictions.
    restrictions = pp.player_number.get_attribute("data-restrictions") or "[]"
    if restrictions.strip() in ("[]", ""):
        log_finding("YG_027", "Player Number field declares no input restrictions/max length: "
                              "no invalid-input validation exists to automate.")
        pp.enter_player_number("AB-7")
        assert_price_equal(pp.get_player_number_charge(), PLAYER_NUMBER_FEE, "Free-text entry charge:")
    else:
        log_finding("YG_027", f"Player Number restrictions declared by the plugin: {restrictions}")


def test_YG_028_subtotal_with_player_number(product_page: ProductPage):
    pp = product_page
    color = first_color(pp)
    sizes = pp.get_available_options("size")
    by_price = sorted(sizes, key=lambda s: expected_variation_price(pp, s, color))
    for size in dict.fromkeys([by_price[0], by_price[-1]]):  # cheapest and most expensive size
        pp.select_variation(size, color)
        base = pp.get_product_price()
        pp.enter_player_number(PLAYER_NUMBER_VALUE)
        expected_total = base + PLAYER_NUMBER_FEE
        pp.wait_for_subtotal(expected_total, f"Subtotal for size {size} (product {money(base)} + player number)")
        line_items = parse_price(pp.page.locator("#product-addons-total li .wc-pao-col2 .amount").first.text_content())
        assert_price_equal(line_items + pp.get_player_number_charge(), pp.get_subtotal(), "Line items sum:")
        pp.clear_player_number()


def test_YG_029_clear_resets_variation(product_page: ProductPage):
    """Observed: Clear resets Size, Color, price display and Add to cart state; link hides itself."""
    pp = product_page
    original_range = pp.get_price_range()
    expect(pp.clear_link, "Clear is hidden before any selection").to_be_hidden()

    pp.select_variation(pp.get_available_options("size")[-1], first_color(pp))
    expect(pp.clear_link, "Clear appears once a variation is chosen").to_be_visible()
    pp.click_clear()

    expect(pp.size_select, "Size should be reset").to_have_value("")
    expect(pp.color_select, "Color should be reset").to_have_value("")
    expect(pp.variation_id, "variation_id should be reset").to_have_value("")
    expect(pp.add_to_cart_button, "Add to cart should be disabled again").to_have_class(DISABLED)
    expect(pp.clear_link, "Clear hides itself after use").to_be_hidden()
    assert pp.get_price_range() == original_range, "Top price should show the full range again"


def test_YG_030_clear_and_player_number(product_page: ProductPage):
    """Documents what Clear does to the Player Number field/subtotal (spec is ambiguous) and checks consistency."""
    pp = product_page
    size, color = pp.get_available_options("size")[-1], first_color(pp)
    pp.select_variation(size, color)
    pp.enter_player_number(PLAYER_NUMBER_VALUE)
    pp.wait_for_subtotal(pp.get_product_price() + PLAYER_NUMBER_FEE)

    pp.click_clear()
    expect(pp.size_select).to_have_value("")
    expect(pp.add_to_cart_button).to_have_class(DISABLED)
    retained = pp.player_number.input_value()
    log_finding("YG_030", f"OBSERVED: after Clear the Player Number field is "
                          f"{'RETAINED (' + retained + ')' if retained else 'EMPTIED'}; size/color/price are reset.")

    # Consistency check independent of which behaviour the product owner wants:
    pp.select_variation(size, color)
    base = pp.get_product_price()
    if retained:
        expect(pp.addon_line_value, "Retained number must still be charged").to_have_text(retained)
        pp.wait_for_subtotal(base + PLAYER_NUMBER_FEE)
    else:
        poll_until(pp.page, pp.addon_line_amount.count, lambda n: n == 0,
                   message="Emptied Player Number must not be charged")


# =============================================================================================
# YG_031: add-to-cart alert
# =============================================================================================
def test_YG_031_alert_on_adding_to_cart(product_page: ProductPage, clean_cart):
    pp = product_page
    size, color = pp.get_available_options("size")[0], first_color(pp)
    pp.select_variation(size, color)
    before = pp.cart_count()
    pp.add_to_cart()
    pp.expect_added_notice(PRIMARY_PRODUCT)
    pp.expect_cart_count(before + 1)


# =============================================================================================
# YG_032 - YG_034: categories, tabs
# =============================================================================================
def test_YG_032_product_categories_listing(product_page: ProductPage):
    pp = product_page
    categories = pp.category_links()
    assert categories, "Product should list at least one category"
    for category in categories:
        assert category["text"], "Category link has no text"
        assert "/product-category/" in category["href"], f"Unexpected category URL: {category['href']}"

    for category in categories:
        pp.goto(category["href"])
        path = re.sub(r"^https?://[^/]+", "", category["href"])
        pp.expect_path(path, f"Category '{category['text']}' should open {path}")
        heading = normalize(pp.page.locator("h1").first.text_content())
        assert category["text"].casefold() in (heading + " " + pp.page.title()).casefold(), (
            f"Category page for '{category['text']}' shows heading {heading!r}"
        )
        names = ShopPage(pp.page).get_product_names()
        assert PRIMARY_PRODUCT in names, f"'{PRIMARY_PRODUCT}' should be listed in category '{category['text']}'"


def test_YG_033_description_tab(product_page: ProductPage):
    pp = product_page
    expect(pp.tab_description, "Description tab should be visible").to_be_visible()
    pp.open_tab(pp.tab_additional, pp.panel_additional)  # leave the tab...
    expect(pp.panel_description).to_be_hidden()
    pp.open_tab(pp.tab_description, pp.panel_description)  # ...and come back by clicking it
    assert len(normalize(pp.panel_description.text_content())) > 20, "Description tab content is empty"


def test_YG_034_additional_information(product_page: ProductPage):
    pp = product_page
    pp.open_tab(pp.tab_additional, pp.panel_additional)
    expect(pp.attributes_table, "Attributes table should be visible").to_be_visible()
    rows = pp.attributes_table.locator("tr").evaluate_all(
        "rows => rows.map(r => [r.querySelector('th')?.textContent.trim(), r.querySelector('td')?.textContent.trim()])"
    )
    assert rows, "Attributes table has no rows"
    table = {normalize(label).lower(): normalize(value) for label, value in rows}
    for label, value in table.items():
        assert label and value, f"Attribute row has an empty label/value: {label!r}={value!r}"
    # The listed values must match the options really offered by the variation selects.
    for attribute in ("size", "color"):
        assert attribute in table, f"Attribute '{attribute}' missing from Additional information: {list(table)}"
        listed = {v.strip() for v in table[attribute].split(",")}
        assert listed == set(pp.get_available_options(attribute)), (
            f"{attribute}: table lists {listed} but the dropdown offers {pp.get_available_options(attribute)}"
        )


# =============================================================================================
# YG_035 - YG_037: related products / slider
# =============================================================================================
def test_YG_035_related_products(product_page: ProductPage):
    pp, page = product_page, product_page.page
    expect(pp.related_section, "Related products section should be visible").to_be_visible()
    expect(pp.related_section.locator("h2").first).to_have_text(re.compile("related products", re.I))
    count = pp.related_cards.count()
    assert count >= 1, "No related products found"

    related = pp.related_cards.evaluate_all(
        """cards => cards.map(li => ({
            name: li.querySelector('h2')?.textContent.trim(),
            href: li.querySelector('a.woocommerce-LoopProduct-link')?.getAttribute('href'),
            price: li.querySelector('.price .woocommerce-Price-amount')?.textContent.trim()}))"""
    )
    for i, item in enumerate(related):
        assert item["name"], f"Related product #{i + 1} has no name"
        assert item["name"] != PRIMARY_PRODUCT, "A product must not be related to itself"
        assert item["href"] and "/product/" in item["href"], f"Related '{item['name']}' has a bad link {item['href']}"
        assert parse_price(item["price"]) > 0, f"Related '{item['name']}' has no valid price"
        assert_image_loaded(page, pp.related_cards.nth(i).locator("img").first, f"Related image '{item['name']}'")

    for item in related:  # click each one by NAME and verify the destination
        card = pp.related_cards.filter(has=page.locator("h2", has_text=re.compile(rf"^\s*{re.escape(item['name'])}\s*$")))
        with page.expect_navigation(wait_until="domcontentloaded"):
            card.locator("a.woocommerce-LoopProduct-link").click()
        pp.expect_path(re.sub(r"^https?://[^/]+", "", item["href"]))
        assert ProductPage(page).wait_loaded().title_text() == item["name"]
        page.go_back(wait_until="domcontentloaded")
        expect(pp.related_section).to_be_visible()


def _assert_no_slider(pp: ProductPage, test_id: str) -> None:
    found = pp.page.locator("main").locator(SLIDER_SELECTORS).count()
    if found:
        pytest.fail(f"{test_id}: a slider/carousel ({found} element(s)) now exists - implement this test.")
    pytest.skip(
        f"{NOT_AUTOMATABLE}: product page has no slider/carousel; 'Related products' is a static list "
        f"and the only prev/next controls are product-to-product arrows (see YG_036_ALT / YG_037_ALT)."
    )


@pytest.mark.not_automatable
def test_YG_036_product_slider(product_page: ProductPage):
    _assert_no_slider(product_page, "YG_036")


@pytest.mark.not_automatable
def test_YG_037_redirection_from_slider(product_page: ProductPage):
    _assert_no_slider(product_page, "YG_037")


def test_YG_036_ALT_previous_next_product_arrows(product_page: ProductPage):
    """Supplementary: the closest existing 'previous/next' control is the theme's product navigation."""
    pp = product_page
    for arrow, label in ((pp.nav_prev, "Previous"), (pp.nav_next, "Next")):
        expect(arrow, f"{label} product arrow should be visible").to_be_visible()
        assert "/product/" in (arrow.get_attribute("href") or ""), f"{label} arrow does not link to a product"
        assert normalize(arrow.text_content()), f"{label} arrow has no product name"
        if arrow.locator("img").count():
            assert_image_loaded(pp.page, arrow.locator("img").first, f"{label} arrow image")


def test_YG_037_ALT_next_arrow_opens_matching_product(product_page: ProductPage):
    pp, page = product_page, product_page.page
    href = pp.nav_next.get_attribute("href")
    expected_name = normalize(pp.nav_next.text_content())
    with page.expect_navigation(wait_until="domcontentloaded"):
        pp.nav_next.click()
    pp.expect_path(re.sub(r"^https?://[^/]+", "", href))
    assert ProductPage(page).wait_loaded().title_text() == expected_name, "Next arrow opened a different product"


# =============================================================================================
# YG_038: reviews
# =============================================================================================
def test_YG_038_reviews(product_page: ProductPage):
    pp = product_page
    expect(pp.tab_reviews, "Reviews tab should be visible").to_be_visible()
    declared = re.search(r"\((\d+)\)", normalize(pp.tab_reviews.text_content()))
    assert declared, f"Reviews tab should show a count, got {pp.tab_reviews.text_content()!r}"
    pp.open_tab(pp.tab_reviews, pp.panel_reviews)

    shown = pp.review_items.count()
    assert shown == int(declared.group(1)), f"Tab says {declared.group(1)} review(s) but {shown} are listed"
    for i in range(shown):
        item = pp.review_items.nth(i)
        text = normalize(item.text_content())
        assert re.search(r"\b(19|20)\d{2}\b", text), f"Review #{i + 1} shows no date: {text!r}"
        assert normalize(item.locator(".description").first.text_content()), f"Review #{i + 1} has no comment text"
        stars = item.locator(".star-rating")
        if stars.count():
            assert re.search(r"[1-5]", stars.first.get_attribute("aria-label") or stars.first.text_content() or ""), (
                f"Review #{i + 1} rating is unreadable"
            )
        else:
            log_finding("YG_038", f"Review #{i + 1} has no star rating (site shows reviews without ratings).")

    # Review form: NEVER submitted. Guests only get a login notice on this site.
    if pp.page.locator("#commentform").count():
        form = pp.page.locator("#commentform")
        expect(form.locator("textarea#comment")).to_be_visible()
        expect(form.locator("input[type=submit], button[type=submit]").first).to_be_visible()
    else:
        expect(pp.review_login_message, "Guests should see the 'must be logged in' notice").to_be_visible()


# =============================================================================================
# YG_039: end-to-end add to cart (no checkout, no order)
# =============================================================================================
def test_YG_039_add_to_cart(product_page: ProductPage, clean_cart):
    pp, page = product_page, product_page.page
    size = pp.get_available_options("size")[-1]
    colors = pp.get_available_options("color")
    color = colors[1] if len(colors) > 1 else colors[0]

    # Required variations must be selected before the button works.
    expect(pp.add_to_cart_button, "Add to cart must be blocked until variations are selected").to_have_class(DISABLED)
    pp.select_variation(size, color)
    unit_price = expected_variation_price(pp, size, color)
    pp.wait_for_variation_price(unit_price)

    pp.enter_player_number(PLAYER_NUMBER_VALUE)
    expected_total = unit_price + PLAYER_NUMBER_FEE
    pp.wait_for_subtotal(expected_total, "Subtotal before adding to cart")

    count_before = pp.cart_count()
    pp.add_to_cart()
    pp.expect_added_notice(PRIMARY_PRODUCT)
    pp.expect_cart_count(count_before + 1)

    pp.goto("/cart/")
    pp.expect_cart_count(count_before + 1)
    row = pp.read_cart_row(PRIMARY_PRODUCT)
    assert size in row["name"], f"Cart line should show size {size}: {row['name']!r}"
    assert row["attributes"].get("Color") == color, f"Cart color should be {color}: {row['attributes']}"
    player_values = [v for k, v in row["attributes"].items() if "player number" in k.lower()]
    assert player_values == [PLAYER_NUMBER_VALUE], f"Player number not retained in cart: {row['attributes']}"
    assert row["quantity"] == 1, f"Quantity should be 1, got {row['quantity']}"
    assert_cart_price(row["unit_price"], expected_total, row["includes_tax"])
