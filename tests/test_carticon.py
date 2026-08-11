from playwright.sync_api import Page, expect


BASE_URL = "https://3.15.3.216/"


def test_cart_icon_is_displayed(page: Page):
    # Open homepage
    page.goto(BASE_URL, wait_until="networkidle")

    # Locate cart icon
    cart_icon = page.locator(
        "a.cart-contents, a[href*='cart'], .cart-icon"
    ).first

    # Verify cart icon is visible
    expect(cart_icon).to_be_visible()

    # Verify cart icon is enabled
    expect(cart_icon).to_be_enabled()py