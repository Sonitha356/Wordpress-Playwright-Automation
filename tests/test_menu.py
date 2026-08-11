from playwright.sync_api import Page, expect

def test_checkout_with_empty_cart(page: Page):
    # Open Cart page
    page.goto("/cart/", wait_until="networkidle")

    # Verify cart is empty
    expect(page.locator(".cart-empty")).to_be_visible()

    # Click Checkout
    page.get_by_role("link", name="Checkout").click()

    # Wait for page to load
    page.wait_for_load_state("networkidle")

    # Verify user remains on Cart page
    assert "/cart/" in page.url

    # Verify empty cart message is displayed
    expect(page.locator(".cart-empty")).to_be_visible()

    print("Current URL:", page.url)