"""Home Page suite YG_001 to YG_030 for https://3.15.3.216 (Jryanonline "Your Own Gear").

Selectors come from dom_report.json (home page, 1440x900). The site is WooCommerce with the
Enfold theme. Nothing here submits a form other than the product search (a GET request),
registers a user, or changes site data.

Tests that need DOM from other pages (/shop/, a product page, cart, checkout, search results)
are explicit skips with the reason, so they show up in the run report instead of being faked.

Run:
    pytest tests/test_home_page_yg.py --base-url https://3.15.3.216 \
        --screenshot only-on-failure --output test-results-yg -v -s
"""
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

expect.set_options(timeout=15_000)  # auto-waiting assertions, no hard sleeps

DESKTOP = {"width": 1440, "height": 900}
MOBILE = {"width": 375, "height": 812}
SEARCH_KEYWORD = os.getenv("YG_SEARCH_KEYWORD", "shirt")
NO_RESULT_KEYWORD = "zzqxjvnoresult"
REPORT_DIR = Path("reports")

# Visible desktop menu items (label shown, path). Case comes from CSS, so match case-insensitively.
NAV_ITEMS = [
    ("HOME", "/"),
    ("SHOP", "/shop/"),
    ("CART", "/cart/"),
    ("CHECKOUT", "/checkout/"),
    ("MY ACCOUNT", "/my-account/"),
]

NEEDS_SHOP_DOM = (
    "Home page has no product cards (dom_report.json: prices=[], no product links or images). "
    "Run discover_dom.py on /shop/ and a product page to get real selectors."
)


# ----------------------------------------------------------------------------- fixtures
@pytest.fixture
def home_url(base_url):
    """Home page URL built from --base-url (falls back to the site IP)."""
    return (base_url or "https://3.15.3.216").rstrip("/") + "/"


@pytest.fixture
def home(page: Page, home_url):
    """Fresh desktop-size home page, ready to use (search field visible)."""
    page.set_viewport_size(DESKTOP)
    page.goto(home_url, wait_until="domcontentloaded")
    expect(search_field(page)).to_be_visible()
    return page


# ----------------------------------------------------------------------------- helpers
def logo_link(page: Page):
    """Header logo: a link whose only content is the logo image (accessible name = image alt)."""
    return page.get_by_role("banner").get_by_role("link", name="Your Own Gear :: Jryanonline.com")


def search_form(page: Page):
    return page.get_by_role("search")  # form.woocommerce-product-search


def search_field(page: Page):
    return search_form(page).locator("input[name='s']")


def search_button(page: Page):
    return search_form(page).get_by_role("button", name="Search")


def nav_link(page: Page, label: str):
    """Visible desktop menu link. Uses :visible because a hidden mobile copy of the menu exists."""
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*$", re.I)
    return page.locator("nav.main_menu a.mega-menu-link:visible").filter(has_text=pattern)


def cart_icon_link(page: Page):
    return page.locator("a.cart_dropdown_link")


def image_loaded(locator) -> bool:
    return locator.evaluate("img => img.complete && img.naturalWidth > 0")


def perform_search(page: Page, keyword: str, use_enter: bool = False):
    """Type a keyword and submit the search (GET). Returns the navigation response."""
    field = search_field(page)
    field.fill(keyword)
    expect(field).to_have_value(keyword)
    with page.expect_navigation(wait_until="domcontentloaded") as nav:
        if use_enter:
            field.press("Enter")
        else:
            search_button(page).click()
    response = nav.value
    assert response is not None, "Search did not trigger a navigation"
    return response


def assert_search_url(page: Page, keyword: str):
    query = parse_qs(urlparse(page.url).query)
    assert query.get("s") == [keyword], f"Expected s={keyword!r} in {page.url}"
    assert query.get("post_type") == ["product"], f"Expected post_type=product in {page.url}"


def visible_texts(page: Page, selector: str):
    return [t.strip() for t in page.locator(selector).all_inner_texts() if t.strip()]


def text_style(text: str) -> str:
    """Rough classification used only to compare items in the same group."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "n/a"
    if all(c.isupper() for c in letters):
        return "UPPERCASE"
    if all(c.islower() for c in letters):
        return "lowercase"
    words = re.findall(r"[A-Za-z][A-Za-z'\u2019]*", text)
    if all(w[0].isupper() for w in words):
        return "Title Case"
    if words[0][0].isupper() and all(w[0].islower() or w.isupper() for w in words[1:]):
        return "Sentence case"
    return "Mixed"


# ----------------------------------------------------------------------------- YG_001
def test_YG_001_logo_is_displayed_and_returns_home(home, home_url):
    """Logo is visible, its image loaded, and clicking it lands on the home page."""
    logo = logo_link(home)
    expect(logo).to_be_visible()
    img = logo.locator("img")
    expect(img).to_be_visible()
    assert image_loaded(img), "Logo image did not load"
    assert logo.evaluate("a => a.href") == home_url

    logo.click()
    expect(home).to_have_url(home_url)
    expect(home).to_have_title(re.compile("Your Own Gear", re.I))
    expect(home.get_by_role("heading", name=re.compile(r"^apparel by jryan & associates$", re.I))).to_be_visible()


def test_YG_001_logo_from_inner_page_navigates_home(page: Page, home_url):
    """From /cart/ (read-only page), clicking the logo goes back to the home page.
    Assumes the shared theme header (same logo link) is used on /cart/."""
    page.set_viewport_size(DESKTOP)
    page.goto(home_url + "cart/", wait_until="domcontentloaded")
    logo = logo_link(page)
    expect(logo).to_be_visible()
    logo.click()
    expect(page).to_have_url(home_url)
    expect(page.get_by_role("heading", name=re.compile(r"^your items$", re.I))).to_be_visible()


# ----------------------------------------------------------------------------- YG_002
def test_YG_002_search_apparel_submits_and_shows_results_page(home):
    """Search field + submit button work and the search results URL is reached.
    Result-card assertions need the results-page DOM (see YG_016)."""
    expect(search_form(home)).to_be_visible()
    expect(search_field(home)).to_have_attribute("placeholder", re.compile("Search products", re.I))
    response = perform_search(home, SEARCH_KEYWORD)
    assert response.ok, f"Search results page returned HTTP {response.status}"
    assert_search_url(home, SEARCH_KEYWORD)
    expect(home).not_to_have_title(re.compile("not found", re.I))


# ----------------------------------------------------------------------------- YG_003 to YG_010
def test_YG_003_your_items_widget_is_displayed(home):
    """The 'YOUR ITEMS' block on the home page is the mini-cart widget (widget_shopping_cart),
    not a product listing. Verify that it is there."""
    expect(home.get_by_role("heading", name=re.compile(r"^your items$", re.I))).to_be_visible()
    expect(home.locator(".widget_shopping_cart").first).to_be_attached()


@pytest.mark.skip(reason=NEEDS_SHOP_DOM)
def test_YG_003_product_cards_have_image_name_price():
    ...


@pytest.mark.skip(reason=NEEDS_SHOP_DOM)
def test_YG_004_product_link_opens_product_details():
    ...


@pytest.mark.skip(reason=NEEDS_SHOP_DOM)
def test_YG_005_product_image_loaded_and_matches_product():
    ...


@pytest.mark.skip(reason=NEEDS_SHOP_DOM)
def test_YG_006_attributes_and_quantity_controls():
    ...


@pytest.mark.skip(reason=NEEDS_SHOP_DOM)
def test_YG_007_price_listing_regular_and_sale():
    ...


@pytest.mark.skip(reason="Needs add-to-cart selectors from a product page and the cart page DOM.")
def test_YG_008_subtotal_matches_quantity_and_price():
    ...


@pytest.mark.skip(reason="Needs add-to-cart selectors from a product page and the cart page DOM.")
def test_YG_009_view_cart_shows_added_product():
    ...


@pytest.mark.skip(reason="Needs a product in the cart first (an empty cart may redirect away from /checkout/).")
def test_YG_010_checkout_page_sections_displayed():
    ...


# ----------------------------------------------------------------------------- YG_011 to YG_013
def test_YG_011_navigation_menu_items_and_links(home, home_url):
    """Five visible menu items, in order, each pointing at the expected page."""
    links = home.locator("nav.main_menu a.mega-menu-link:visible")
    expect(links).to_have_count(len(NAV_ITEMS))
    for label, path in NAV_ITEMS:
        link = nav_link(home, label)
        expect(link).to_have_count(1)
        expect(link).to_be_visible()
        assert link.evaluate("a => a.href") == home_url.rstrip("/") + path, label


def test_YG_012_home_menu_item_stays_on_home_page(home, home_url):
    """HOME is the current item, and it leads to the home page from another page."""
    home.goto(home_url + "shop/", wait_until="domcontentloaded")
    nav_link(home, "HOME").click()
    expect(home).to_have_url(home_url)
    expect(home.get_by_role("heading", name=re.compile(r"^search apparel$", re.I))).to_be_visible()


def test_YG_013_shop_menu_item_opens_shop_page(home, home_url):
    """SHOP navigates to /shop/. Category links on /shop/ need that page's DOM."""
    with home.expect_navigation(wait_until="domcontentloaded") as nav:
        nav_link(home, "SHOP").click()
    assert nav.value is not None and nav.value.ok
    expect(home).to_have_url(home_url + "shop/")


# ----------------------------------------------------------------------------- YG_014 to YG_016
def test_YG_014_search_with_valid_keyword_using_enter_key(home):
    """Pressing Enter in the search field submits the same GET search."""
    response = perform_search(home, "jacket", use_enter=True)
    assert response.ok
    assert_search_url(home, "jacket")


def test_YG_015_search_with_no_result_keyword_still_loads(home):
    """A keyword that should match nothing still returns a valid page.
    The 'no results' message needs the results-page DOM to be asserted."""
    response = perform_search(home, NO_RESULT_KEYWORD)
    assert response.ok
    assert_search_url(home, NO_RESULT_KEYWORD)


@pytest.mark.skip(reason="Needs the search results page DOM: run discover_dom.py on /?s=shirt&post_type=product")
def test_YG_016_search_results_display():
    ...


# ----------------------------------------------------------------------------- YG_017 to YG_020
@pytest.mark.skip(reason=NEEDS_SHOP_DOM)
def test_YG_017_add_to_cart_from_home_page():
    ...


@pytest.mark.skip(reason=NEEDS_SHOP_DOM)
def test_YG_018_add_multiple_products_to_cart():
    ...


def test_YG_019_cart_icon_shows_item_count(home):
    """Cart icon in the header shows a numeric count. Count change after adding needs YG_017."""
    icon = cart_icon_link(home)
    expect(icon).to_be_visible()
    expect(icon).to_have_text(re.compile(r"^\s*\d+\s*$"))


def test_YG_020_cart_icon_opens_cart_page(home, home_url):
    cart_icon_link(home).click()
    expect(home).to_have_url(home_url + "cart/")


# ----------------------------------------------------------------------------- YG_021 to YG_026
def test_YG_021_my_account_menu_item_opens_account_page(home, home_url):
    """Navigation only. No login or registration is attempted."""
    nav_link(home, "MY ACCOUNT").click()
    expect(home).to_have_url(home_url + "my-account/")
    expect(home.locator("main")).to_be_visible()


def test_YG_022_wishlist_or_compare_if_available(home):
    extras = home.locator("[class*='wish' i], [class*='compare' i]")
    if extras.count() == 0:
        pytest.skip("No wishlist/compare elements on the home page (none in dom_report.json).")
    expect(extras.first).to_be_visible()


def test_YG_023_promotional_link_points_to_jryanonline(home):
    """The only promo element is the 'Apparel by JRyan & Associates' image link (external site)."""
    promo = home.locator("a.widget_sp_image-image-link")
    expect(promo).to_be_visible()
    expect(promo).to_have_attribute("href", re.compile(r"^https?://(www\.)?jryanonline\.com/?$"))
    img = promo.locator("img")
    expect(img).to_have_attribute("alt", "Apparel by JRyan & Associates")
    assert image_loaded(img), "Promo image did not load"


@pytest.mark.skip(reason="No category or featured-product links exist on the home page (dom_report.json).")
def test_YG_024_category_and_featured_product_links():
    ...


def test_YG_025_footer_links(home):
    footer = home.get_by_role("contentinfo")
    expect(footer).to_be_visible()
    copyright_link = footer.get_by_role("link", name=re.compile(r"jryanonline\.com", re.I))
    expect(copyright_link).to_be_visible()
    expect(copyright_link).to_have_attribute("href", re.compile(r"^https?://(www\.)?jryanonline\.com/?$"))
    expect(footer).to_contain_text(re.compile(r"all rights reserved", re.I))


def test_YG_026_social_links_if_available(home):
    social = home.locator(
        "a[href*='facebook.com'], a[href*='twitter.com'], a[href*='x.com'], a[href*='instagram.com'], "
        "a[href*='linkedin.com'], a[href*='youtube.com'], a[href*='pinterest.com']"
    )
    if social.count() == 0:
        pytest.skip("No social media links on the home page (none in dom_report.json).")
    for i in range(social.count()):
        expect(social.nth(i)).to_be_visible()


# ----------------------------------------------------------------------------- YG_027
def assert_no_horizontal_overflow(page: Page):
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), \
        "Page scrolls horizontally"


def test_YG_027_responsive_layout_desktop(home):
    assert_no_horizontal_overflow(home)
    expect(home.locator("nav.main_menu a.mega-menu-link:visible")).to_have_count(len(NAV_ITEMS))
    expect(logo_link(home)).to_be_visible()


def test_YG_027_responsive_layout_mobile(page: Page, home_url):
    """375px wide: no sideways scroll, logo and search usable, menu collapsed behind a toggle button.
    The toggle check follows the Max Mega Menu markup; confirm it on the first run."""
    page.set_viewport_size(MOBILE)
    page.goto(home_url, wait_until="domcontentloaded")
    expect(search_field(page)).to_be_visible()
    expect(logo_link(page)).to_be_visible()
    assert_no_horizontal_overflow(page)
    expect(page.locator("button[aria-label='Toggle Menu']:visible").first).to_be_visible()


# ----------------------------------------------------------------------------- YG_028
def test_YG_028_no_broken_images_or_internal_links(home, home_url, record_property):
    # Images: every <img> on the page loaded (complete and non-zero natural width).
    images = home.locator("img")
    broken_images = [
        images.nth(i).get_attribute("src")
        for i in range(images.count())
        if not image_loaded(images.nth(i))
    ]
    assert not broken_images, f"Broken images: {broken_images}"

    # Links: GET each unique http(s) link once. Internal failures fail the test; external ones
    # are only reported, because third-party availability is outside this site's control.
    hrefs = home.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    unique = sorted({h.split("#")[0] for h in hrefs if h.startswith(("http://", "https://")) and h.split("#")[0]})
    internal_bad, external_bad = [], []
    for href in unique:
        try:
            status = home.request.get(href, timeout=20_000).status
        except Exception as exc:  # network error, timeout
            status = f"error: {exc}"
        if isinstance(status, int) and status < 400:
            continue
        (internal_bad if href.startswith(home_url.rstrip("/")) else external_bad).append((href, status))
    record_property("external_link_problems", json.dumps(external_bad))
    print(f"\nLinks checked: {len(unique)}; external problems (not failing): {external_bad}")
    assert not internal_bad, f"Broken internal links: {internal_bad}"


# ----------------------------------------------------------------------------- YG_029
def test_YG_029_text_capitalization_report(home, record_property):
    """Records the visible text and its capitalization style per location. It fails only if items
    inside the same group (menu, headings) use different styles, because the site's own style is
    the reference. Nothing here assumes 'Issues of Aging' style strings exist on this site."""
    groups = {
        "menu (header nav.main_menu)": visible_texts(home, "nav.main_menu a.mega-menu-link:visible"),
        "headings (main h3.widgettitle)": visible_texts(home, "main h1:visible, main h2:visible, main h3:visible, main h4:visible"),
        "footer (footer#socket)": visible_texts(home, "footer#socket a:visible"),
        "search button": visible_texts(home, "form.woocommerce-product-search button:visible"),
    }
    report = [
        {"location": loc, "text": text, "style": text_style(text)}
        for loc, texts in groups.items() for text in texts
    ]
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "yg_029_capitalization.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    record_property("capitalization_report", json.dumps(report, ensure_ascii=False))
    print("\nYG_029 observed text:")
    for row in report:
        print(f"  [{row['location']}] {row['text']!r} -> {row['style']}")

    assert report, "No visible text collected"
    for loc in ("menu (header nav.main_menu)", "headings (main h3.widgettitle)"):
        styles = {r["style"] for r in report if r["location"] == loc}
        assert len(styles) <= 1, f"Inconsistent capitalization in {loc}: {styles}"


# ----------------------------------------------------------------------------- YG_030
def test_YG_030_home_page_load_time_recorded(page: Page, home_url, record_property):
    """Measures time until the home page is usable (search field visible and enabled).
    Recorded for reference only; there is no pass/fail threshold."""
    page.set_viewport_size(DESKTOP)
    start = time.perf_counter()
    response = page.goto(home_url, wait_until="domcontentloaded")
    expect(search_field(page)).to_be_visible()
    expect(search_field(page)).to_be_enabled()
    usable_seconds = time.perf_counter() - start

    timing = page.evaluate(
        "() => { const n = performance.getEntriesByType('navigation')[0];"
        " return n ? {dcl_ms: Math.round(n.domContentLoadedEventEnd), load_ms: Math.round(n.loadEventEnd)} : null; }"
    )
    record_property("home_usable_seconds", round(usable_seconds, 2))
    record_property("navigation_timing", json.dumps(timing))
    print(f"\nYG_030 home page usable after {usable_seconds:.2f}s; navigation timing: {timing}")
    assert response is not None and response.ok
    assert usable_seconds 