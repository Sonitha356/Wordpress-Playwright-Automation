import os
from datetime import datetime
import pytest

print("conftest.py loaded")

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    print("ignore_https_errors=True applied")
    return {
        **browser_context_args,
        "ignore_https_errors": True,
    }

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item):
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        page = item.funcargs.get("page")

        if page:
            os.makedirs("screenshots", exist_ok=True)

            filename = os.path.join(
                "screenshots",
                f"{item.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            )

            page.screenshot(path=filename, full_page=True)
            print(f"Screenshot saved: {filename}")