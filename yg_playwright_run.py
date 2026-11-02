"""Standalone Playwright (Python) script for YG_001 to YG_010 on https://3.15.3.216. No pytest needed.

Each test runs in its own fresh browser context (empty cart, not logged in), so tests are independent.
Results are printed as a table and saved to reports/yg_results.csv. A full-page screenshot is saved to
yg_screenshots/ when a test fails. The exit code is 1 if any test failed.

Locator status
- Home page locators (logo, search form, cart icon, "YOUR ITEMS" heading) come from dom_report.json.
- Shop, product, cart and checkout locators in LOC are the standard WooCommerce ones and are not yet
  confirmed on this site. Run "--only YG_000" first: it lists every LOC entry that matches nothing.

Safety: read-only navigation, product search (GET) and session cart actions only. The order is never
placed and no customer data is typed into any form (YG_010 stops at the checkout page).

Usage
    python yg_playwright_run.py                      run everything, headless
    python yg_playwright_run.py --headed             watch the browser
    python yg_playwright_run.py --only YG_000        locator check only
    python yg_playwright_run.py --only YG_003,YG_008 selected tests
    python yg_playwright_run.py --list               list tests without running
Options: --base-url, --keyword (search term, default shirt), --product-url (pin one product page), --slowmo MS
"""
import argparse
import csv
import re
import sys
import time
from decimal import Decimal
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

DESKTOP = {"width": 1440, "height": 900}
MAX_PRODUCTS_SCANNED = 12
CFG = {"keyword": "shirt", "product_url": None}
SCREENSHOT_DIR = Path("yg_screenshots")
REPORT_DIR = Path("reports")

expect.set_options(timeout=15_000)  # auto-waiting assertions, no hard sleeps

LOC = {
    # shop listing (standard WooCommerce, unverified on this site)
    "card": "ul.products li.product",
    "card_name": ".woocommerce-loop-product__title, h2, h3",
    "card_price": ".price",
    # product details page
    "title": "h1.product_title",
    "detail_price": ".summary .price, p.price",
    "variation_price": ".woocommerce-variation-price .price",
    "gallery_image": ".woocommerce-product-gallery img, .images img",
    "variations_form": "form.variations_form",
    "variation_selects": "form.variations_form select",
    "qty": "form.cart input.qty",
    "add_btn": "form.cart button.single_add_to_cart_button",
    "added_msg": ".woocommerce-message",
    "view_cart_link": ".woocommerce-message a.wc-forward",
    # cart page
    "cart_row": "tr.cart_item",
    "cart_name": "td.product-name a",
    "cart_unit_price": "td.product-price",
    "cart_qty": "td.product-quantity input.qty",
    "cart_line_total": "td.product-subtotal",
    "cart_subtotal": ".cart_totals .cart-subtotal td",
    "update_btn": "button[name='update_cart']",
    "checkout_btn": "a.checkout-button",
    # checkout page
    "checkout_form": "form.checkout",
    "checkout_details": "#customer_details",
    "checkout_review": "#order_review",
    "checkout_payment": "#payment",
    "place_order": "#place_order",
    # home page mini cart widget ("YOUR ITEMS")
    "home_cart_widget": "main .widget_shopping_cart",
    "mini_item": "li.woocommerce-mini-cart-item",
}


# ------------------------------------------------------------------------------------------ mini runner
class Skip(Exception):
    """Raised when a test cannot run on this site (for example no variable product exists)."""


REGISTRY = []  # (test id, title, function)


def case(test_id, title):
    def register(fn):
        REGISTRY.append((test_id, title, fn))
        return fn
    return register


# ------------------------------------------------------------------------------------------ helpers
def logo_link(page: Page):
    return page.get_by_role("banner").get_by_role("link", name="Your Own Gear :: Jryanonline.com")


def search_form(page: Page):
    return page.get_by_role("search")


def cart_icon_link(page: Page):
    return page.locator("a.cart_dropdown_link")  # text is the item count


def to_decimal(text: str) -> Decimal:
    """First amount in a text such as '$1,299.00' -> Decimal('1299.00'). Assumes '.' decimals."""
    match = re.search(r"\d[\d,]*\.?\d*", text.replace("\u00a0", " "))
    assert match, f"No amount found in {text!r}"
    return Decimal(match.group(0).replace(",", ""))


def price_of(locator) -> Decimal:
    """Price of an element; on sale items (del + ins) the sale price (ins) is returned."""
    sale = locator.locator("ins")
    return to_decimal((sale.first if sale.count() else locator).inner_text())


def image_loaded(page: Page, img):
    """Wait until an image has finished loading successfully (no sleeps)."""
    img.scroll_into_view_if_needed()
    page.wait_for_function("el => el.complete && el.naturalWidth > 0", arg=img.element_handle())


def assert_money_equal(actual: Decimal, expected: Decimal, what: str):
    assert abs(actual - expected) <= Decimal("0.01"), f"{what}: expected {expected}, got {actual}"


def open_shop(page: Page, home_url: str):
    page.goto(home_url + "shop/", wait_until="domcontentloaded")
    expect(page.locator(LOC["card"]).first).to_be_visible()


def shop_products(page: Page, limit: int = MAX_PRODUCTS_SCANNED):
    """Name, href and card index of the first products (page must already be on /shop/)."""
    cards = page.locator(LOC["card"])
    products = []
    for i in range(min(cards.count(), limit)):
        card = cards.nth(i)
        products.append({
            "index": i,
            "name": card.locator(LOC["card_name"]).first.inner_text().strip(),
            "href": card.locator("a[href]").first.get_attribute("href"),
        })
    return products


def is_variable(page: Page) -> bool:
    return page.locator(LOC["variations_form"]).count() > 0


def pick_simple_product_href(page: Page, home_url: str, exclude: str = "") -> str:
    """Href of the first product without attribute selectors (keeps price maths simple)."""
    if CFG["product_url"] and not exclude:
        return CFG["product_url"]
    open_shop(page, home_url)
    products = [p for p in shop_products(page) if not exclude or p["href"].rstrip("/") != exclude.rstrip("/")]
    for product in products:
        page.goto(product["href"], wait_until="domcontentloaded")
        if not is_variable(page):
            return product["href"]
    raise Skip(f"No simple product among the first {len(products)} products (use --product-url).")


def find_variable_product_href(page: Page, home_url: str):
    open_shop(page, home_url)
    for product in shop_products(page):
        page.goto(product["href"], wait_until="domcontentloaded")
        if is_variable(page):
            return product["href"]
    return None


def select_first_options(page: Page):
    """Choose the first real option of every attribute drop-down (variable products only)."""
    selects = page.locator(LOC["variation_selects"])
    for i in range(selects.count()):
        select = selects.nth(i)
        values = [v for v in select.locator("option").evaluate_all("os => os.map(o => o.value)") if v]
        if values:
            select.select_option(values[0])


def product_price_on_page(page: Page) -> Decimal:
    variation = page.locator(LOC["variation_price"])
    if variation.count() and variation.first.is_visible():
        return price_of(variation.first)
    return price_of(page.locator(LOC["detail_price"]).first)


def add_to_cart(page: Page, href: str, qty: int = 1) -> dict:
    """Open a product page and add it to the session cart. Returns name, unit price and href."""
    page.goto(href, wait_until="domcontentloaded")
    name = page.locator(LOC["title"]).first.inner_text().strip()
    select_first_options(page)
    price = product_price_on_page(page)
    if qty != 1:
        page.locator(LOC["qty"]).first.fill(str(qty))
    button = page.locator(LOC["add_btn"]).first
    expect(button).to_be_enabled()
    button.click()
    expect(page.locator(LOC["added_msg"]).first).to_be_visible()
    return {"name": name, "price": price, "href": href}


def open_cart(page: Page, home_url: str):
    page.goto(home_url + "cart/", wait_until="domcontentloaded")
    expect(page.locator(LOC["cart_row"]).first).to_be_visible()


def cart_subtotal(page: Page) -> Decimal:
    return to_decimal(page.locator(LOC["cart_subtotal"]).first.inner_text())


# ------------------------------------------------------------------------------------------ YG_000
@case("YG_000", "Locator check (shop, product, cart, checkout, mini cart)")
def locator_check(page: Page, home_url: str):
    missing = []

    def check(keys):
        missing.extend(k for k in keys if page.locator(LOC[k]).count() == 0)

    open_shop(page, home_url)
    check(["card", "card_price"])
    if page.locator(LOC["card"]).first.locator(LOC["card_name"]).count() == 0:
        missing.append("card_name")
    href = pick_simple_product_href(page, home_url)
    page.goto(href, wait_until="domcontentloaded")
    check(["title", "detail_price", "gallery_image", "qty", "add_btn"])
    add_to_cart(page, href)
    check(["view_cart_link"])
    open_cart(page, home_url)
    check(["cart_row", "cart_name", "cart_unit_price", "cart_qty", "cart_line_total", "cart_subtotal",
           "update_btn", "checkout_btn"])
    page.goto(home_url + "checkout/", wait_until="domcontentloaded")
    check(["checkout_form", "checkout_details", "checkout_review", "checkout_payment", "place_order"])
    page.goto(home_url, wait_until="domcontentloaded")
    check(["home_cart_widget", "mini_item"])
    assert not missing, f"These LOC entries match nothing on this site, please correct them: {missing}"


# ------------------------------------------------------------------------------------------ YG_001
@case("YG_001", "Logo is displayed and returns to the home page")
def logo_displayed_returns_home(page: Page, home_url: str):
    page.goto(home_url, wait_until="domcontentloaded")
    logo = logo_link(page)
    expect(logo).to_be_visible()
    img = logo.locator("img")
    expect(img).to_have_attribute("alt", "Your Own Gear :: Jryanonline.com")
    image_loaded(page, img)
    logo.click()
    expect(page).to_have_url(home_url)
    expect(page).to_have_title(re.compile("Your Own Gear", re.I))
    expect(page.get_by_role("heading", name=re.compile(r"^apparel by jryan & associates$", re.I))).to_be_visible()


@case("YG_001", "Logo from the cart page returns to the home page")
def logo_from_cart_returns_home(page: Page, home_url: str):
    page.goto(home_url + "cart/", wait_until="domcontentloaded")
    logo_link(page).click()
    expect(page).to_have_url(home_url)


# ------------------------------------------------------------------------------------------ YG_002
def search_and_check(page: Page, home_url: str, use_enter: bool):
    keyword = CFG["keyword"]
    page.goto(home_url, wait_until="domcontentloaded")
    field = search_form(page).locator("input[name='s']")
    expect(field).to_have_attribute("placeholder", re.compile("Search products", re.I))
    field.fill(keyword)
    with page.expect_navigation(wait_until="domcontentloaded") as nav:
        if use_enter:
            field.press("Enter")
        else:
            search_form(page).get_by_role("button", name="Search").click()
    assert nav.value is not None and nav.value.ok
    expect(page).to_have_url(re.compile(rf"[?&]s={re.escape(keyword)}(&|$)"))
    expect(page).to_have_url(re.compile(r"post_type=product"))
    # If this fails, pass --keyword with a term that exists in the shop
    expect(page.locator(LOC["card"]).first).to_be_visible()


@case("YG_002", "Search apparel using the Search button")
def search_click(page: Page, home_url: str):
    search_and_check(page, home_url, use_enter=False)


@case("YG_002", "Search apparel using the Enter key")
def search_enter(page: Page, home_url: str):
    search_and_check(page, home_url, use_enter=True)


# ------------------------------------------------------------------------------------------ YG_003
@case("YG_003", "'YOUR ITEMS' section lists the added product")
def your_items_lists_added_product(page: Page, home_url: str):
    href = pick_simple_product_href(page, home_url)
    item = add_to_cart(page, href)
    page.goto(home_url, wait_until="domcontentloaded")
    widget = page.locator(LOC["home_cart_widget"]).first
    expect(widget.get_by_role("heading", name=re.compile(r"^your items$", re.I))).to_be_visible()
    row = widget.locator(LOC["mini_item"]).first
    expect(row).to_be_visible()
    expect(row).to_contain_text(re.compile(re.escape(item["name"]), re.I))
    image_loaded(page, row.locator("img").first)
    expect(row).to_contain_text(re.compile(r"\d"))  # price / quantity text present
    link = row.locator("a[href]:not(.remove)").first
    expect(link).to_be_visible()
    link.click()
    expect(page).to_have_url(re.compile(re.escape(item["href"].rstrip("/"))))


# ------------------------------------------------------------------------------------------ YG_004
@case("YG_004", "Product link opens the product details page")
def product_link_opens_details(page: Page, home_url: str):
    open_shop(page, home_url)
    product = shop_products(page, 1)[0]
    card = page.locator(LOC["card"]).first
    expect(card.locator(LOC["card_price"]).first).to_be_visible()
    card.locator(LOC["card_name"]).first.click()
    expect(page).not_to_have_url(re.compile(r"/shop/?(\?.*)?$"))
    expect(page).to_have_url(re.compile(re.escape(product["href"].rstrip("/"))))
    expect(page.locator(LOC["title"]).first).to_have_text(re.compile(re.escape(product["name"]), re.I))
    expect(page.locator(LOC["detail_price"]).first).to_be_visible()
    expect(page.locator(LOC["gallery_image"]).first).to_be_visible()
    page.go_back()
    expect(page).to_have_url(re.compile(r"/shop/"))


# ------------------------------------------------------------------------------------------ YG_005
@case("YG_005", "Product images load and match their product")
def product_images(page: Page, home_url: str):
    open_shop(page, home_url)
    cards = page.locator(LOC["card"])
    checked = min(cards.count(), 6)
    assert checked >= 1, "No product cards found"
    for i in range(checked):
        card = cards.nth(i)
        img = card.locator("img").first
        expect(img).to_be_attached()
        image_loaded(page, img)
        hrefs = card.locator("a[href]").evaluate_all("as => as.map(a => a.href)")
        product_hrefs = {h for h in hrefs if "add-to-cart" not in h}  # image and name must share one product page
        assert len(product_hrefs) == 1, f"Card {i} links to several pages: {product_hrefs}"
    first_href = next(iter({h for h in cards.first.locator("a[href]").evaluate_all("as => as.map(a => a.href)")
                            if "add-to-cart" not in h}))
    cards.first.locator("img").first.click()
    expect(page).to_have_url(re.compile(re.escape(first_href.rstrip("/"))))
    image_loaded(page, page.locator(LOC["gallery_image"]).first)


# ------------------------------------------------------------------------------------------ YG_006
@case("YG_006", "Attributes and quantity control (invalid quantities not tested)")
def attributes_and_quantity(page: Page, home_url: str):
    href = find_variable_product_href(page, home_url)
    if href is None:
        raise Skip("No product with attributes among the first products on /shop/.")
    page.goto(href, wait_until="domcontentloaded")
    selects = page.locator(LOC["variation_selects"])
    expect(selects.first).to_be_visible()
    for i in range(selects.count()):
        assert selects.nth(i).locator("option").count() >= 2, "Attribute has no selectable options"
    qty = page.locator(LOC["qty"]).first
    expect(qty).to_be_visible()
    expect(qty).to_have_value("1")
    qty.fill("3")
    expect(qty).to_have_value("3")
    # Add to cart without choosing attributes: WooCommerce shows a browser alert and adds nothing
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(LOC["add_btn"]).first.click(force=True)
    expect(page.locator(LOC["added_msg"])).to_have_count(0)
    expect(cart_icon_link(page)).to_have_text(re.compile(r"^\s*0\s*$"))


# ------------------------------------------------------------------------------------------ YG_007
@case("YG_007", "Listing price matches the product details page")
def price_matches_details(page: Page, home_url: str):
    open_shop(page, home_url)
    products = shop_products(page)
    compared = 0
    for product in products:
        listing = page.locator(LOC["card"]).nth(product["index"]).locator(LOC["card_price"]).first
        expect(listing).to_be_visible()
        listing_price = price_of(listing)
        page.goto(product["href"], wait_until="domcontentloaded")
        if not is_variable(page):  # variable products show a price range on the listing
            assert_money_equal(price_of(page.locator(LOC["detail_price"]).first), listing_price, product["name"])
            compared += 1
        if compared >= 3:
            break
        open_shop(page, home_url)
    assert compared >= 1, "No simple product to compare listing and details prices"


@case("YG_007", "Sale price shows regular and sale price")
def sale_price(page: Page, home_url: str):
    open_shop(page, home_url)
    on_sale = page.locator(f"{LOC['card']}:has({LOC['card_price']} del)")
    if on_sale.count() == 0:
        raise Skip("No product on sale in the first shop page.")
    price = on_sale.first.locator(LOC["card_price"]).first
    regular = to_decimal(price.locator("del").first.inner_text())
    sale = to_decimal(price.locator("ins").first.inner_text())
    assert sale < regular, f"Sale price {sale} is not below regular price {regular}"


# ------------------------------------------------------------------------------------------ YG_008
@case("YG_008", "Subtotal matches quantity and price")
def subtotal(page: Page, home_url: str):
    href = pick_simple_product_href(page, home_url)
    item = add_to_cart(page, href)
    open_cart(page, home_url)
    row = page.locator(LOC["cart_row"]).first
    assert_money_equal(to_decimal(row.locator(LOC["cart_unit_price"]).inner_text()), item["price"], "unit price")
    assert_money_equal(cart_subtotal(page), item["price"], "subtotal for quantity 1")

    old_total = row.locator(LOC["cart_line_total"]).inner_text()
    row.locator(LOC["cart_qty"]).fill("2")
    expect(page.locator(LOC["update_btn"])).to_be_enabled()
    page.locator(LOC["update_btn"]).click()
    expect(page.locator(LOC["cart_row"]).first.locator(LOC["cart_line_total"])).not_to_have_text(old_total)
    assert_money_equal(cart_subtotal(page), item["price"] * 2, "subtotal for quantity 2")

    second_href = pick_simple_product_href(page, home_url, exclude=href)  # skips if there is no second one
    second = add_to_cart(page, second_href)
    open_cart(page, home_url)
    assert page.locator(LOC["cart_row"]).count() == 2, "Expected two products in the cart"
    assert_money_equal(cart_subtotal(page), item["price"] * 2 + second["price"], "subtotal for two products")


# ------------------------------------------------------------------------------------------ YG_009
@case("YG_009", "View cart shows the added product")
def view_cart(page: Page, home_url: str):
    href = pick_simple_product_href(page, home_url)
    item = add_to_cart(page, href)
    view_cart_link = page.locator(LOC["view_cart_link"]).first
    if view_cart_link.count() and "/cart" not in page.url:
        view_cart_link.click()
    else:
        cart_icon_link(page).click()
    expect(page).to_have_url(home_url + "cart/")
    row = page.locator(LOC["cart_row"]).first
    expect(row.locator(LOC["cart_name"]).first).to_have_text(re.compile(re.escape(item["name"]), re.I))
    expect(row.locator(LOC["cart_qty"])).to_have_value("1")
    assert_money_equal(to_decimal(row.locator(LOC["cart_unit_price"]).inner_text()), item["price"], "unit price")
    assert_money_equal(to_decimal(row.locator(LOC["cart_line_total"]).inner_text()), item["price"], "line total")
    assert_money_equal(cart_subtotal(page), item["price"], "cart subtotal")
    expect(cart_icon_link(page)).to_have_text(re.compile(r"^\s*1\s*$"))
    page.goto(home_url, wait_until="domcontentloaded")  # header cart icon also opens the cart
    cart_icon_link(page).click()
    expect(page).to_have_url(home_url + "cart/")


# ------------------------------------------------------------------------------------------ YG_010
@case("YG_010", "Checkout page sections are displayed (order is never placed)")
def checkout_sections(page: Page, home_url: str):
    href = pick_simple_product_href(page, home_url)
    add_to_cart(page, href)
    open_cart(page, home_url)
    page.locator(LOC["checkout_btn"]).first.click()
    expect(page).to_have_url(home_url + "checkout/")
    expect(page.locator(LOC["checkout_form"])).to_be_visible()
    expect(page.locator(LOC["checkout_details"])).to_be_visible()   # billing / shipping details
    expect(page.locator(LOC["checkout_review"])).to_be_visible()    # order summary
    expect(page.locator(LOC["checkout_payment"])).to_be_visible()   # payment options
    expect(page.locator(LOC["place_order"])).to_be_visible()        # present, but never clicked


# ------------------------------------------------------------------------------------------ runner
def slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")[:60]


def main():
    parser = argparse.ArgumentParser(description="Run the YG_001 to YG_010 Playwright checks.")
    parser.add_argument("--base-url", default="https://3.15.3.216")
    parser.add_argument("--keyword", default="shirt", help="search term that exists in the shop")
    parser.add_argument("--product-url", default=None, help="pin one simple product page for cart tests")
    parser.add_argument("--only", default="", help="comma separated ids, for example YG_000,YG_003")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--slowmo", type=int, default=0, help="milliseconds between actions (for watching)")
    parser.add_argument("--list", action="store_true", help="list tests and exit")
    args = parser.parse_args()

    CFG["keyword"], CFG["product_url"] = args.keyword, args.product_url
    home_url = args.base_url.rstrip("/") + "/"
    wanted = {t.strip().upper() for t in args.only.split(",") if t.strip()}
    selected = [c for c in REGISTRY if not wanted or c[0] in wanted]

    if args.list:
        for test_id, title, _ in selected:
            print(f"{test_id}  {title}")
        return 0
    if not selected:
        print("No tests match --only.")
        return 2

    SCREENSHOT_DIR.mkdir(exist_ok=True)
    REPORT_DIR.mkdir(exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, slow_mo=args.slowmo)
        for number, (test_id, title, fn) in enumerate(selected, 1):
            context = browser.new_context(ignore_https_errors=True, viewport=DESKTOP)  # fresh session per test
            page = context.new_page()
            page.set_default_timeout(20_000)
            status, message, shot = "PASS", "", ""
            start = time.perf_counter()
            try:
                fn(page, home_url)
            except Skip as skip:
                status, message = "SKIP", str(skip)
            except Exception as exc:  # assertion or Playwright error
                status, message = "FAIL", str(exc).strip()
                shot = str(SCREENSHOT_DIR / f"{number:02d}_{test_id}_{slug(title)}.png")
                try:
                    page.screenshot(path=shot, full_page=True)
                except Exception:
                    shot = ""
            finally:
                context.close()
            seconds = round(time.perf_counter() - start, 1)
            results.append({"id": test_id, "title": title, "status": status, "seconds": seconds,
                            "message": message, "screenshot": shot})
            first_line = message.splitlines()[0][:110] if message else ""
            print(f"{status:<5} {test_id}  {title}  ({seconds}s) {first_line}")
        browser.close()

    with open(REPORT_DIR / "yg_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "title", "status", "seconds", "message", "screenshot"])
        writer.writeheader()
        writer.writerows(results)

    counts = {s: sum(r["status"] == s for r in results) for s in ("PASS", "FAIL", "SKIP")}
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped. "
          f"Details: {REPORT_DIR / 'yg_results.csv'}")
    for r in results:
        if r["status"] == "FAIL":
            print(f"\nFAILED {r['id']} {r['title']}\n{r['message']}\nScreenshot: {r['screenshot']}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())