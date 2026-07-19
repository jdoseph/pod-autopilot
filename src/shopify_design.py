"""Storefront design for Joseph's Shirts — quirky products, minimalist look.
Automates everything the granted scopes allow:
  - smart collections (auto-populate by product title rules)  [write_products]
  - homepage template: hero + featured collections + values    [write_themes]
  - About page brand copy                                      [content]
Store NAME can only be changed in admin (Settings -> General) — the API
returns 406 for shop mutations from custom apps.
Run: python -m src.shopify_design
"""
import copy
import json
import os
from pathlib import Path

import requests

from . import shopify_auth

STORE = os.environ["SHOPIFY_STORE"]
BRAND = "Joseph's Shirts"
TAGLINE = "Quirky prints for particular people."
ACCENT = "#E64400"  # electric orange — the one loud note on a monochrome page

# Horizon settings overrides (keys verified against the live settings_data
# dump). Archivo Black display type + uppercase headings + pill buttons.
STYLE = {
    "type_heading_font": "archivo_black_n4",
    "type_accent_font": "archivo_black_n4",
    "type_size_h1": "64",
    "type_case_h1": "uppercase",
    "type_case_h2": "uppercase",
    "palette_primary_button_background": ACCENT,
    "palette_primary_button_text": "#ffffff",
    "palette_primary_button_border": ACCENT,
    "button_border_radius_primary": 100,
    "button_border_radius_secondary": 100,
    "badge_sale_background_color": ACCENT,
    "badge_sale_text_color": "#ffffff",
    "color_palette": {"background": "#ffffff", "foreground": "#111111",
                      "color1": "#444444", "color2": "#E6E6E6"},
}

# handle -> (title, disjunctive, [(column, relation, condition), ...])
# The store sells exactly three product families (owner decision, July 2026).
SMART_COLLECTIONS = {
    "t-shirts": ("T-Shirts", True, [("title", "contains", "shirt"),
                                    ("title", "contains", "tee")]),
    "mugs": ("Mugs", False, [("title", "contains", "mug")]),
    "totes": ("Totes", False, [("title", "contains", "tote")]),
}

ABOUT_HTML = f"""<p>{BRAND} makes original, slightly odd designs for people
whose taste doesn't fit the default settings. Every piece starts as an idea
we actually like — botanical diagrams, weird typography, things your favorite
coworker would point at — and gets printed on demand, one at a time.</p>
<p>No warehouse, no landfill of unsold inventory: your order is printed and
shipped by our production partner when you place it.</p>"""


def api(method: str, path: str, data: dict | None = None,
        params: dict | None = None) -> dict:
    auth = shopify_auth.headers()
    if not auth:
        raise RuntimeError("Shopify auth failed")
    url = f"https://{STORE}/admin/api/2025-07{path}"
    r = requests.request(method, url, headers=auth, json=data, params=params,
                         timeout=30)
    if not r.ok:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:300]}")
    return r.json() if r.text else {}


def graphql(query: str, variables: dict) -> dict:
    auth = shopify_auth.headers()
    r = requests.post(f"https://{STORE}/admin/api/2025-07/graphql.json",
                      headers=auth, json={"query": query, "variables": variables},
                      timeout=30)
    r.raise_for_status()
    out = r.json()
    if out.get("errors"):
        raise RuntimeError(str(out["errors"])[:300])
    return out["data"]


def setup_collections() -> None:
    existing = {c["handle"] for c in
                api("GET", "/smart_collections.json").get("smart_collections", [])}
    for handle, (title, disjunctive, rules) in SMART_COLLECTIONS.items():
        if handle in existing:
            print(f"  - collection {title} (exists)")
            continue
        api("POST", "/smart_collections.json", {"smart_collection": {
            "title": title, "handle": handle, "disjunctive": disjunctive,
            "rules": [{"column": c, "relation": r, "condition": v}
                      for c, r, v in rules],
        }})
        print(f"  + collection {title} (auto-fills from product titles)")


def setup_about_page() -> None:
    pages = api("GET", "/pages.json").get("pages", [])
    about = next((p for p in pages if p["handle"] == "about"), None)
    if about:
        api("PUT", f"/pages/{about['id']}.json",
            {"page": {"id": about["id"], "body_html": ABOUT_HTML}})
        print("  + About page: brand copy updated")
    else:
        api("POST", "/pages.json", {"page": {
            "title": "About", "handle": "about", "body_html": ABOUT_HTML,
            "published": True}})
        print("  + About page created")


def _active_theme() -> dict:
    themes = api("GET", "/themes.json").get("themes", [])
    theme = next((t for t in themes if t.get("role") == "main"), None)
    if not theme:
        raise RuntimeError("no active theme")
    return theme


def _write_theme_file(theme_id: int, filename: str, value: str) -> None:
    """REST asset write, falling back to GraphQL themeFilesUpsert."""
    try:
        api("PUT", f"/themes/{theme_id}/assets.json",
            {"asset": {"key": filename, "value": value}})
        return
    except RuntimeError as rest_err:
        data = graphql(
            """mutation up($files: [OnlineStoreThemeFilesUpsertFileInput!]!,
                           $themeId: ID!) {
                 themeFilesUpsert(files: $files, themeId: $themeId) {
                   upsertedThemeFiles { filename }
                   userErrors { field message }
                 }}""",
            {"themeId": f"gid://shopify/OnlineStoreTheme/{theme_id}",
             "files": [{"filename": filename,
                        "body": {"type": "TEXT", "value": value}}]})
        errs = data["themeFilesUpsert"]["userErrors"]
        if errs:
            raise RuntimeError(f"REST: {rest_err} | GraphQL: {errs}")


THEME_DIR = Path(__file__).resolve().parent.parent / "theme"


def sync_theme_dir() -> None:
    """Upload the repo's theme/ sources (custom sections, brand CSS, page
    templates) to the live theme — the implementation of the Claude Design
    handoff. Native Horizon header/footer/PDP/cart stay untouched; sorted
    upload order puts sections/ before templates/ so JSON templates never
    reference a section that has not landed yet."""
    theme = _active_theme()
    print(f"  · active theme: {theme['name']} (id {theme['id']})")
    for path in sorted(THEME_DIR.rglob("*")):
        if not path.is_file():
            continue
        key = path.relative_to(THEME_DIR).as_posix()
        _write_theme_file(theme["id"], key, path.read_text(encoding="utf-8"))
        print(f"  + {key}")


CSS_TAG = "{{ 'joes-brand.css' | asset_url | stylesheet_tag }}"


def ensure_css_link() -> None:
    """Make sure layout/theme.liquid loads the brand stylesheet."""
    theme = _active_theme()
    layout = api("GET", f"/themes/{theme['id']}/assets.json",
                 params={"asset[key]": "layout/theme.liquid"})["asset"]["value"]
    if "joes-brand.css" not in layout:
        if "</head>" not in layout:
            print("  ! theme.liquid has no </head> — stylesheet not linked")
            return
        layout = layout.replace("</head>", f"    {CSS_TAG}\n  </head>", 1)
        _write_theme_file(theme["id"], "layout/theme.liquid", layout)
    print("  + brand stylesheet linked")


def setup_theme_style() -> None:
    """Apply the brand look to config/settings_data.json in place."""
    theme = _active_theme()
    asset = api("GET", f"/themes/{theme['id']}/assets.json",
                params={"asset[key]": "config/settings_data.json"})
    data = json.loads(asset["asset"]["value"])
    current = data.get("current")
    if isinstance(current, str):  # settings referencing a preset by name
        current = copy.deepcopy(data["presets"][current])
        data["current"] = current
    if not isinstance(current, dict):
        print("  ! settings_data has no editable 'current' — style skipped")
        return
    current.update(copy.deepcopy(STYLE))
    _write_theme_file(theme["id"], "config/settings_data.json",
                      json.dumps(data, indent=2))
    print("  + theme style: Archivo Black display, uppercase headings, "
          f"pill buttons, accent {ACCENT}")


# Owner PII to remove from all customer-facing resources — keep email only.
PHONE_PATTERNS = ["+1 912-224-2499", "912-224-2499", "(912) 224-2499"]
ADDRESS_PATTERNS = ["1464 Moonrise Ave, Carrollton TX 75006, United States",
                    "1464 Moonrise Ave, Carrollton TX 75006",
                    "1464 Moonrise Ave", "Carrollton TX 75006"]
CONTACT_EMAIL = "b56678588@gmail.com"


def _scrub_text(text: str) -> str:
    """Remove phone/address, keep email, tidy leftover connector phrases."""
    import re
    for p in PHONE_PATTERNS:
        text = re.sub(r"(?:please\s+)?call(?:\s+us)?(?:\s+at)?\s*" + re.escape(p)
                      + r"\s*(?:,|or)?\s*", "", text, flags=re.I)
        text = text.replace(p, "")
    for a in ADDRESS_PATTERNS:
        text = re.sub(r"(?:,|or)?\s*(?:contact|visit|write)(?:\s+us)?(?:\s+at)?\s*"
                      + re.escape(a) + r"\.?", "", text, flags=re.I)
        text = text.replace(a, "")
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.])", r"\1", text)
    return text


def _mentions_pii(text: str) -> bool:
    return any(p in text for p in PHONE_PATTERNS + ADDRESS_PATTERNS)


def scrub_contact_info() -> None:
    """Strip phone + street address from storefront resources; email stays."""
    found_any = False

    for page in api("GET", "/pages.json").get("pages", []):
        body = page.get("body_html") or ""
        if _mentions_pii(body):
            found_any = True
            api("PUT", f"/pages/{page['id']}.json",
                {"page": {"id": page["id"], "body_html": _scrub_text(body)}})
            print(f"  + page '{page['title']}': phone/address removed")

    try:
        policies = api("GET", "/policies.json").get("policies", [])
    except RuntimeError as e:
        policies = []
        print(f"  ! policies unreadable ({str(e)[:80]}) — check Settings → Policies manually")
    for pol in policies:
        body = pol.get("body") or ""
        if _mentions_pii(body):
            found_any = True
            print(f"  ⚠ policy '{pol.get('title')}' contains phone/address — "
                  "policies are admin-only: Settings → Policies, delete the "
                  f"phone/address lines (keep {CONTACT_EMAIL})")

    try:
        shop = api("GET", "/shop.json").get("shop", {})
        if shop.get("phone"):
            found_any = True
            print("  ⚠ store phone is set in Settings → General (admin-only) — "
                  "clear the phone field there")
        if any("Moonrise" in str(shop.get(k, "")) for k in
               ("address1", "address2", "city")):
            print("  · note: the Settings → General business address is used for "
                  "billing/labels; it is not shown on the storefront unless a "
                  "template prints it")
    except RuntimeError:
        pass

    if not found_any:
        print("  - no phone/address found in API-visible resources")
    print(f"  · contact stays email-only: {CONTACT_EMAIL}")


def dump_homepage() -> None:
    """Print the live homepage template + theme settings for faithful edits."""
    theme = _active_theme()
    print(f"THEME: {theme['name']} (id {theme['id']})")
    for key in ("templates/index.json", "config/settings_data.json"):
        asset = api("GET", f"/themes/{theme['id']}/assets.json",
                    params={"asset[key]": key})
        print(f"----- {key} -----")
        print(asset["asset"]["value"])


if __name__ == "__main__":
    import sys
    if "dump" in sys.argv:
        dump_homepage()
        raise SystemExit(0)
    if "scrub" in sys.argv:
        print("[contact scrub]\n")
        scrub_contact_info()
        raise SystemExit(0)
    print("[storefront design]\n")
    failures = 0
    for step in (setup_collections, setup_about_page, setup_theme_style,
                 sync_theme_dir, ensure_css_link):
        try:
            step()
        except Exception as e:
            failures += 1
            print(f"  ! {step.__name__}: {e}")
    print("\nManual (admin-only, ~1 min): Settings -> General -> store name "
          f"= \"{BRAND}\". Menus need the write_online_store_navigation "
          "scope if you ever want them automated; the default menu works.")
    exit(1 if failures else 0)
