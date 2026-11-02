"""Read-only DOM discovery for the YG Home Page suite.

Only performs GET navigation and DOM reads. It never clicks, types or submits.

Usage:
    python discover_dom.py https://3.15.3.216/
    python discover_dom.py https://3.15.3.216/ <product-url> <cart-url> <checkout-url> <search-results-url>

Output: dom_report.json plus one full-page screenshot per URL in discovery/.
"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

JS = r"""
() => {
  const txt = e => (e.innerText || e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 120);
  const cls = e => (typeof e.className === 'string' ? e.className : '').slice(0, 160);
  const q = s => [...document.querySelectorAll(s)];
  const pick = (e, names) => Object.fromEntries(
    names.map(n => [n, e.getAttribute(n)]).filter(([, v]) => v !== null && v !== ''));
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);

  const classCounts = {};
  q('[class]').forEach(e => (typeof e.className === 'string' ? e.className : '').split(/\s+/)
    .filter(c => /product|cart|price|woocommerce|search|logo|menu|nav|wish|compare|account|checkout|qty|quantity|sale|social|banner|hero/i.test(c))
    .forEach(c => classCounts[c] = (classCounts[c] || 0) + 1));

  return {
    url: location.href,
    title: document.title,
    generator: (document.querySelector('meta[name=generator]') || {}).content || null,
    bodyClass: document.body.className,
    headings: q('h1,h2,h3,h4').map(e => ({tag: e.tagName, text: txt(e), cls: cls(e), visible: vis(e)})),
    landmarks: q('header,nav,main,footer,aside,[role=banner],[role=navigation],[role=main],[role=contentinfo],[role=search]')
      .map(e => ({tag: e.tagName.toLowerCase(), id: e.id, cls: cls(e), role: e.getAttribute('role'), aria: e.getAttribute('aria-label')})),
    links: q('a[href]').map(e => ({text: txt(e), href: e.href, cls: cls(e), aria: e.getAttribute('aria-label'),
      inHeader: !!e.closest('header'), inNav: !!e.closest('nav'), inFooter: !!e.closest('footer'),
      hasImg: !!e.querySelector('img'), visible: vis(e)})),
    images: q('img').map(e => ({src: e.currentSrc || e.src, alt: e.alt, cls: cls(e), w: e.naturalWidth, h: e.naturalHeight,
      complete: e.complete, loading: e.getAttribute('loading'), inLink: e.closest('a') ? e.closest('a').href : null,
      inHeader: !!e.closest('header')})),
    forms: q('form').map(e => ({id: e.id, cls: cls(e), action: e.action, method: e.method, role: e.getAttribute('role'),
      fields: [...e.querySelectorAll('input,select,textarea,button')].map(f => ({tag: f.tagName.toLowerCase(), ...pick(f, ['type','name','id','placeholder','aria-label','value','min','max','step','required'])}))})),
    inputs: q('input,select,textarea').map(e => ({tag: e.tagName.toLowerCase(), cls: cls(e),
      ...pick(e, ['type','name','id','placeholder','aria-label','min','max','step','value']), visible: vis(e),
      label: e.labels && e.labels[0] ? txt(e.labels[0]) : null})),
    buttons: q('button,[role=button],input[type=submit],input[type=button]').map(e => ({text: txt(e) || e.value || '',
      cls: cls(e), ...pick(e, ['type','name','id','aria-label','href']), visible: vis(e)})),
    prices: q('[class*=price],[itemprop=price]').slice(0, 40).map(e => ({text: txt(e), cls: cls(e)})),
    classCounts,
    social: q('a[href]').filter(a => /facebook|twitter|x\.com|instagram|linkedin|youtube|pinterest|tiktok/i.test(a.href))
      .map(a => ({href: a.href, text: txt(a), aria: a.getAttribute('aria-label'), inFooter: !!a.closest('footer')})),
  };
}
"""


def slug(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", url).strip("_")[:80]


def main(urls):
    out = Path("discovery")
    out.mkdir(exist_ok=True)
    report = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
        for url in urls:
            page = ctx.new_page()
            resp = page.goto(url, wait_until="load")
            data = page.evaluate(JS)
            data["status"] = resp.status if resp else None
            page.screenshot(path=str(out / f"{slug(url)}.png"), full_page=True)
            report.append(data)
            page.close()
        browser.close()
    Path("dom_report.json").write_text(json.dumps(report, indent=2))
    print(f"Wrote dom_report.json and {len(report)} screenshot(s) in {out}/")


if __name__ == "__main__":
    main(sys.argv[1:] or ["https://3.15.3.216/"])