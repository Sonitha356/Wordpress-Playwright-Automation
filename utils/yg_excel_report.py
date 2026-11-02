
"""Excel report for the YG_001 - YG_010 requirement tests.

Registered as a pytest plugin from conftest.py with:

    pytest_plugins = ["utils.yg_excel_report"]
pytest tests/test_yg_requirements.py -v
It listens to pytest's own results (nothing is invented), and after the session ends it writes
``YG_test_results.xlsx`` using openpyxl, even when tests fail. The existing pytest-html report and
screenshot hook in conftest.py are not touched; this is an additional output.

Status rules
    PASS     test body ran and every assertion held
    FAIL     an assertion / locator check in the test body did not hold
    BLOCKED  the test could not be completed: error while setting up (fixtures, adding products to
             the cart), a page that would not load (BlockedError), or the pytest session aborted
    SKIPPED  the test was skipped, or was not part of this pytest run (e.g. deselected with -k)

Override the output path with the environment variable YG_EXCEL_REPORT.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from utils.helpers import BASE_URL, ROOT_DIR, SCREENSHOT_DIR, extract_test_id, screenshot_name

DEFAULT_REPORT_PATH = ROOT_DIR / "YG_test_results.xlsx"

PASS, FAIL, BLOCKED, SKIPPED = "PASS", "FAIL", "BLOCKED", "SKIPPED"

# Test ID -> (Requirement, Expected Result). Exactly as specified in the requirement table.
REQUIREMENTS: dict[str, tuple[str, str]] = {
    "YG_001": ("Logo Verification",
               "The website logo is visible and redirects to the correct page when clicked."),
    "YG_002": ("Search Apparel",
               "Searching for apparel displays relevant search results."),
    "YG_003": ("View Products in Your Items",
               "Products are displayed correctly in the Your Items section."),
    "YG_004": ("Click on Product Link",
               "Clicking a product link redirects to the correct product details page."),
    "YG_005": ("Product Image",
               "Product images are visible, load successfully, and correspond to the correct products."),
    "YG_006": ("Attribute & Quantity Listing",
               "Product attributes and quantity are displayed correctly."),
    "YG_007": ("Price Listing",
               "Product prices are displayed correctly."),
    "YG_008": ("Sub-total",
               "The subtotal is displayed and calculated correctly from the applicable product prices "
               "and quantities."),
    "YG_009": ("View Cart",
               "Clicking View Cart redirects to the Cart page."),
    "YG_010": ("Checkout",
               "Clicking Checkout redirects to the Checkout page."),
}


class BlockedError(Exception):
    """Raise from a test/fixture when an environmental or prerequisite problem stops the test
    (page will not load, product could not be added to the cart, ...). Reported as BLOCKED."""


# --- collected results (filled by the hooks below) -----------------------------------------------
_RESULTS: dict[str, dict] = {}
_REPORT_FILE: Path | None = None


def _short_error(excinfo, limit: int = 900) -> str:
    """Exception type + the first meaningful lines of its message (Playwright call logs trimmed)."""
    if excinfo is None:
        return ""
    text = str(excinfo.value).strip()
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    cut = []
    for ln in lines:
        low = ln.strip().lower()
        if low.startswith(("call log", "locator resolved", "waiting for")):
            break
        if low.startswith(("assert ", "+ ", "where ", "+  where")):
            continue  # pytest's assertion-rewrite detail repeats what the message already says
        cut.append(ln)
    message = " | ".join(cut) or text
    if len(message) > limit:
        message = message[: limit - 3] + "..."
    return f"{excinfo.typename}: {message}"


def _record(item, status: str, detail: str, page_url: str = "") -> None:
    tid = extract_test_id(item.name)
    _RESULTS[tid] = {
        "status": status,
        "detail": detail,
        "url": page_url,
        "screenshot": screenshot_name(item.name),
        "nodeid": item.nodeid,
    }


def _page_url(item) -> str:
    try:
        page = item.funcargs.get("page")
        return page.url if page else ""
    except Exception:
        return ""


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    tid = extract_test_id(item.name)
    if tid not in REQUIREMENTS:
        return  # only the ten YG_001 - YG_010 requirements are reported here

    if report.when == "setup":
        if report.failed:
            _record(item, BLOCKED, "Test could not start (setup/fixture error). "
                    + _short_error(call.excinfo), _page_url(item))
        elif report.skipped:
            _record(item, SKIPPED, _skip_reason(report), "")
    elif report.when == "call":
        if report.passed:
            _record(item, PASS, "", "")
        elif report.skipped:
            _record(item, SKIPPED, _skip_reason(report), "")
        elif report.failed:
            if call.excinfo is not None and call.excinfo.errisinstance(BlockedError):
                _record(item, BLOCKED, _short_error(call.excinfo), _page_url(item))
            else:
                _record(item, FAIL, _short_error(call.excinfo), _page_url(item))
    elif report.when == "teardown" and report.failed:
        existing = _RESULTS.get(tid)
        if existing and existing["status"] == PASS:
            # Test body passed; keep PASS but make the clean-up problem visible in the report.
            existing["note"] = "Clean-up after the test failed: " + _short_error(call.excinfo)


def _skip_reason(report) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2]).replace("Skipped: ", "")
    return str(longrepr) if longrepr else "Skipped"


# --- build the workbook --------------------------------------------------------------------------
def _failed_case_text(tid: str, rec: dict) -> str:
    """Text for the 'Description for Failed Case' column (blank for PASS)."""
    if rec["status"] == PASS:
        return ""
    _, expected = REQUIREMENTS[tid]
    parts = [f"Expected: {expected}"]
    if rec["status"] == FAIL:
        parts.append(f"Actual / error: {rec['detail']}")
    elif rec["status"] == BLOCKED:
        parts.append(f"Blocked (could not complete): {rec['detail']}")
    else:
        parts.append(f"Not executed: {rec['detail']}")
    if rec.get("url"):
        parts.append(f"Page URL at failure: {rec['url']}")
    shot = rec.get("screenshot")
    if rec["status"] in (FAIL, BLOCKED) and shot:
        if (SCREENSHOT_DIR / shot).exists():
            parts.append(f"Screenshot: {SCREENSHOT_DIR.name}/{shot}")
        else:
            parts.append("Screenshot: not captured")
    return "\n".join(parts)


def _final_rows(exitstatus: int) -> list[dict]:
    rows = []
    for tid, (requirement, expected) in REQUIREMENTS.items():
        rec = _RESULTS.get(tid)
        if rec is None:
            if exitstatus in (2, 3, 4):
                rec = {"status": BLOCKED, "url": "", "screenshot": "",
                       "detail": f"pytest did not run this test (session exit status {exitstatus}: "
                                 "interrupted, internal error or usage error)."}
            else:
                rec = {"status": SKIPPED, "url": "", "screenshot": "",
                       "detail": "Not part of this pytest run (not selected, deselected or not collected)."}
        rows.append({"id": tid, "requirement": requirement, "expected": expected,
                     "status": rec["status"], "description": _failed_case_text(tid, rec)})
    return rows


def write_workbook(rows: list[dict], path: Path, exitstatus: int) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Test Results"

    headers = ["Test ID", "Requirement", "Expected Result", "Test Status", "Description for Failed Case"]
    ws.append(headers)

    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="1F3864")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    palette = {
        PASS: ("C6EFCE", "006100"),
        FAIL: ("FFC7CE", "9C0006"),
        BLOCKED: ("FFEB9C", "9C5700"),
        SKIPPED: ("D9D9D9", "404040"),
    }
    for row in rows:
        ws.append([row["id"], row["requirement"], row["expected"], row["status"], row["description"]])
        r = ws.max_row
        for col in range(1, 6):
            cell = ws.cell(row=r, column=col)
            cell.alignment = Alignment(wrap_text=True, vertical="top",
                                       horizontal="center" if col in (1, 4) else "left")
            cell.border = border
        fill, font = palette[row["status"]]
        status_cell = ws.cell(row=r, column=4)
        status_cell.fill = PatternFill("solid", fgColor=fill)
        status_cell.font = Font(bold=True, color=font)

    for letter, width in zip("ABCDE", (11, 28, 48, 14, 85)):
        ws.column_dimensions[letter].width = width
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:E{ws.max_row}"

    # --- summary sheet
    summary = wb.create_sheet("Summary")
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in (PASS, FAIL, BLOCKED, SKIPPED)}
    summary.append(["Metric", "Count"])
    summary.append(["Total tests", len(rows)])
    summary.append(["Passed", counts[PASS]])
    summary.append(["Failed", counts[FAIL]])
    summary.append(["Blocked", counts[BLOCKED]])
    summary.append(["Skipped", counts[SKIPPED]])
    summary.append([])
    summary.append(["Run date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    summary.append(["Website under test", BASE_URL])
    summary.append(["pytest exit status", exitstatus])
    for cell in summary[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center")
    for row_idx, status in zip(range(3, 7), (PASS, FAIL, BLOCKED, SKIPPED)):
        fill, font = palette[status]
        summary.cell(row=row_idx, column=1).fill = PatternFill("solid", fgColor=fill)
        summary.cell(row=row_idx, column=1).font = Font(bold=True, color=font)
    summary.cell(row=2, column=1).font = Font(bold=True)
    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 30
    for r in range(2, 11):
        summary.cell(row=r, column=2).alignment = Alignment(horizontal="left")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(path)
    except PermissionError:
        # Usually the file is open in Excel on Windows: save beside it instead of losing the run.
        path = path.with_name(f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
        wb.save(path)
    return path


def pytest_sessionfinish(session, exitstatus):
    """Runs after every pytest session, whether tests passed, failed or the run was interrupted."""
    global _REPORT_FILE
    try:
        target = Path(os.environ.get("YG_EXCEL_REPORT") or DEFAULT_REPORT_PATH)
        _REPORT_FILE = write_workbook(_final_rows(int(exitstatus)), target, int(exitstatus))
    except Exception as exc:  # reporting must never hide the real test outcome
        _REPORT_FILE = None
        print(f"\n[yg_excel_report] Could not write the Excel report: {exc!r}")


def pytest_terminal_summary(terminalreporter):
    if _REPORT_FILE:
        terminalreporter.write_sep("-", f"Excel report: {_REPORT_FILE}")
```

Save it as `utils/yg_excel_report.py` in your project.