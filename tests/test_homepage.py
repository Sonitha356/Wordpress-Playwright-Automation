from playwright.sync_api import Page, expect

def test_home_001_homepage_loads(page: Page):
    site_url = "https://3.15.3.216/"

    response = page.goto(site_url)

    assert response.ok, f"Homepage returned status {response.status}"
    expect(page.locator("body")).to_be_visible()


def test_base_url(page: Page):
    page.goto("/")
    print(page.url)
    assert "3.15.3.216" in page.url