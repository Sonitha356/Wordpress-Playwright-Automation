from playwright.sync_api import Page, expect

BASE_URL = "https://3.15.3.216/"


def test_my_account_login_link(page: Page):

    # Open homepage
    page.goto(
        BASE_URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    # Locate My Account link
    my_account_link = page.get_by_role(
        "link",
        name="My Account"
    )

    # Verify My Account link is visible
    expect(my_account_link).to_be_visible()

    # Verify My Account link is enabled
    expect(my_account_link).to_be_enabled()

    # Click My Account link
    my_account_link.click()

    # Verify user is redirected to My Account/Login page
    expect(page).to_have_url(
        f"{BASE_URL}my-account/"
    )

    # Verify Login/My Account page is displayed
    expect(page.locator("body")).to_contain_text(
        "Login"
    )