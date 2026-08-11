from playwright.sync_api import Page, expect

def test_search_bar_and_product_search(page: Page):
    # Open the homepage
    page.goto("/", wait_until="networkidle")

    # Locate the search bar
    search_bar = page.locator("input[type='search']")

    # Verify the search bar is visible
    expect(search_bar).to_be_visible()

    # Verify the search bar is enabled
    expect(search_bar).to_be_enabled()

    print("Search bar is visible and accessible.")

    # Enter a valid product name
    product_name = "TShirt"   # Replace with an actual product name available on your site
    search_bar.fill(product_name)

    # Press Enter to search
    search_bar.press("Enter")

    # Wait for search results to load
    page.wait_for_load_state("networkidle")

    # Verify the search URL contains the search query
    assert "?s=" in page.url

    # Verify at least one product is displayed
    products = page.locator(".products li")
    assert products.count() > 0

    print(f"Search for '{product_name}' returned {products.count()} product(s).")