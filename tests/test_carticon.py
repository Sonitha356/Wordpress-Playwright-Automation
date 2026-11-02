import re

from playwright.sync_api import Page, expect

BASE_URL = "https://3.15.3.216/"


def test_add_product_and_navigate_to_cart(page: Page):

    # Open Shop page
    page.goto(
        f"{BASE_URL}shop/",
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(2000)

    # Verify Shop page
    expect(page).to_have_url(f"{BASE_URL}shop/")

    # Locate Add to Cart button
    add_to_cart = page.locator(
        "a.add_to_cart_button, button.add_to_cart_button"
    ).first

    # Locate Select Options
    select_options = page.get_by_text(
        "Select options",
        exact=True
    ).first

    # If direct Add to Cart is available
    if add_to_cart.count() > 0 and add_to_cart.is_visible():

        print("Direct Add to Cart option found.")

        expect(add_to_cart).to_be_enabled()

        add_to_cart.click()

        page.wait_for_timeout(2000)

    # If Select Options is available
    else:

        print("Add to Cart not found. Selecting product options.")

        expect(select_options).to_be_visible()

        select_options.click()

        page.wait_for_load_state(
            "domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(2000)

        # Verify variation form
        variation_form = page.locator(
            "form.variations_form"
        )

        expect(variation_form).to_be_visible()

        # Find variation dropdowns
        variation_selects = variation_form.locator("select")

        assert variation_selects.count() > 0, \
            "No product variation dropdowns were found."

        # Select first available option from each dropdown
        for i in range(variation_selects.count()):

            variation_select = variation_selects.nth(i)

            options = variation_select.locator(
                "option"
            ).evaluate_all(
                """
                options => options
                    .filter(option => option.value !== '')
                    .map(option => option.value)
                """
            )

            assert options, \
                f"No selectable variation found in dropdown {i + 1}."

            variation_select.select_option(options[0])

        # Allow WooCommerce to update variation
        page.wait_for_timeout(2000)

        # Locate Add to Cart button
        add_to_cart = page.locator(
            "button.single_add_to_cart_button"
        ).first

        expect(add_to_cart).to_be_visible()
        expect(add_to_cart).to_be_enabled()

        add_to_cart.click()

        page.wait_for_timeout(2000)

    # Locate Cart link
    cart_link = page.locator(
        "a.cart_dropdown_link"
    ).first

    expect(cart_link).to_be_visible()

    # Get Cart URL
    cart_url = cart_link.get_attribute("href")

    assert cart_url is not None, \
        "Cart link does not contain an href."

    # Navigate to Cart
    page.goto(
        cart_url,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(2000)

    # Verify Cart URL using regex
    expect(page).to_have_url(
        re.compile(r".*/cart/?$")
    )

    # Verify Cart text
    expect(page.locator("body")).to_contain_text("Cart")

    # Verify cart is not empty
    expect(
        page.locator("body")
    ).not_to_contain_text(
        "No products in the cart."
    )

    print(
        "Product successfully added to cart "
        "and Cart page verified."
    )pytest