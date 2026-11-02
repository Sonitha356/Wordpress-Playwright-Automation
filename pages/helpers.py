"""Reusable, framework-agnostic helpers (price parsing, polling, image checks, logging)."""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

ROOT_DIR = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT_DIR / "screenshots"
REPORT_DIR = ROOT_DIR / "reports"
FINDINGS_FILE = REPORT_DIR / "findings.log"

BASE_URL = "https://3.15.3.216"

# --- Test data (verified on the live site during inspection) -----------------
# Located by visible name, never by position. Product pages are reached by
# clicking through the shop, so no slug is hard-coded (note: on this site the
# "Crewneck" product has the slug 'premium-hockey-hooded-sweatshirt').
PRIMARY_PRODUCT = "Carhartt ® Midweight Hooded Sweatshirt"
PLAYER_NUMBER_LABEL = "Add Your Player Number"
PLAYER_NUMBER_FEE = 3.00
PLAYER_NUMBER_VALUE = "23"

NOT_AUTOMATABLE = "NOT AUTOMATABLE – Feature not available on current implementation"

_AMOUNT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


# --- Text / price helpers -------------------------------------------------------
def normalize(text: str | None) -> str:
    """Collapse whitespace (incl. nbsp) so DOM text can be compared reliably."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_price(price_text: str) -> float:
    """'$1,234.50' -> 1234.5. Uses the FIRST amount found in the text."""
    match = _AMOUNT_RE.search(price_text or "")
    if not match:
        raise ValueError(f"No numeric price found in {price_text!r}")
    return float(match.group(0).replace(",", ""))


def parse_all_prices(price_text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in _AMOUNT_RE.findall(price_text or "")]


def parse_price_range(price_text: str) -> tuple[float, float]:
    """'$42.00 – $46.00' -> (42.0, 46.0); a single price -> (p, p)."""
    prices = parse_all_prices(price_text)
    if not prices:
        raise ValueError(f"No numeric price found in {price_text!r}")
    return min(prices), max(prices)


def money(value: float) -> str:
    return f"${value:,.2f}"


def prices_equal(a: float, b: float, tolerance: float = 0.005) -> bool:
    return abs(a - b) <= tolerance


def assert_price_equal(actual: float, expected: float, message: str = "") -> None:
    assert prices_equal(actual, expected), (
        f"{message} expected {money(expected)} but found {money(actual)}".strip()
    )


# --- Ordering helpers -------------------------------------------------------------
def detect_order(values: Sequence) -> str:
    """Return 'flat', 'asc', 'desc' or 'unordered' (ties allowed)."""
    pairs = list(zip(values, values[1:]))
    asc = all(a <= b for a, b in pairs)
    desc = all(a >= b for a, b in pairs)
    if asc and desc:
        return "flat"
    if asc:
        return "asc"
    if desc:
        return "desc"
    return "unordered"


def find_duplicates(items: Iterable[str]) -> list[str]:
    seen, dupes = set(), []
    for item in items:
        if item in seen:
            dupes.append(item)
        seen.add(item)
    return dupes


# --- Polling (Playwright-Python has no expect.poll) -----------------------------------
def poll_until(page, getter: Callable, predicate: Callable[[object], bool],
               timeout_ms: int = 10_000, interval_ms: int = 150, message: str = ""):
    """Poll `getter()` until `predicate(value)` is truthy; raise AssertionError otherwise.

    Uses page.wait_for_timeout between attempts (no time.sleep), and keeps the last
    value/error so the failure message is meaningful.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    last, last_error = None, None
    while True:
        try:
            last = getter()
            if predicate(last):
                return last
            last_error = None
        except Exception as exc:  # element not ready yet; retry until the deadline
            last_error = exc
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"{message or 'Condition not met'} (last value={last!r}, last error={last_error!r})"
            )
        page.wait_for_timeout(interval_ms)


def assert_image_loaded(page, image_locator, description: str = "image", timeout_ms: int = 10_000):
    """Image is visible and really decoded (not a broken <img>)."""
    from playwright.sync_api import expect

    image_locator.scroll_into_view_if_needed(timeout=timeout_ms)
    expect(image_locator, f"{description} should be visible").to_be_visible(timeout=timeout_ms)
    poll_until(
        page,
        lambda: image_locator.evaluate(
            "img => img.complete && img.naturalWidth > 0 && img.naturalHeight > 0", timeout=2000
        ),
        lambda ok: ok is True,
        timeout_ms=timeout_ms,
        message=f"{description} is broken or failed to load (naturalWidth == 0)",
    )


def image_stem(src: str) -> str:
    """'.../Carhartt-hood5-450x450.jpg' -> 'carhartt-hood5' (drops WP size suffix)."""
    name = (src or "").split("?")[0].rsplit("/", 1)[-1]
    name = re.sub(r"\.\w+$", "", name)
    name = re.sub(r"-\d+x\d+$", "", name)
    return name.lower()


# --- Reporting ------------------------------------------------------------------------------
def extract_test_id(name: str) -> str:
    match = re.search(r"(YG_\d+)", name)
    return match.group(1) if match else "UNKNOWN"


def screenshot_name(test_name: str) -> str:
    """'test_YG_026_price_by_size' -> 'YG_026_price_by_size.png'."""
    base = re.sub(r"\[.*\]$", "", test_name)  # drop pytest parametrization suffix such as [chromium]
    return re.sub(r"^test_", "", base) + ".png"


def log_finding(test_id: str, message: str) -> None:
    """Record an observation (not a failure) to reports/findings.log and stdout."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {test_id}: {message}"
    print(f"FINDING {line}")
    with FINDINGS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
