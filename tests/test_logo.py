from playwright.sync_api import Page, expect

def test_logo_redirects_to_homepage(page: Page):
    # Navigate to the Shop page
    page.goto("/shop/", wait_until="networkidle")

    # Verify we're not already on the homepage
    expect(page).not_to_have_url("https://3.15.3.216/")

    # Print URL before click
    print("Before click:", page.url)

    # Click the logo
    page.get_by_role("link", name="Your Own Gear :: Jryanonline.").click()

    # Print URL after click
    print("After click:", page.url)

    # Verify we're redirected to the homepage
    expect(page).to_have_url("https://3.15.3.216/")