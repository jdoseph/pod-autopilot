"""Storefront design for Joseph's Shirts — quirky products, minimalist look.
Automates everything the granted scopes allow:
  - smart collections (auto-populate by product title rules)  [write_products]
  - homepage template: hero + featured collections + values    [write_themes]
  - About page brand copy                                      [content]
Store NAME can only be changed in admin (Settings -> General) — the API
returns 406 for shop mutations from custom apps.
Run: python -m src.shopify_design
"""
import json
import os

import requests

from . import shopify_auth

STORE = os.environ["SHOPIFY_STORE"]
BRAND = "Joseph's Shirts"
TAGLINE = "Quirky prints for particular people."

# handle -> (title, disjunctive, [(column, relation, condition), ...])
SMART_COLLECTIONS = {
    "t-shirts": ("T-Shirts", True, [("title", "contains", "shirt"),
                                    ("title", "contains", "tee")]),
    "mugs": ("Mugs", False, [("title", "contains", "mug")]),
    "totes": ("Totes", False, [("title", "contains", "tote")]),
    "posters": ("Posters", False, [("title", "contains", "poster")]),
}

ABOUT_HTML = f"""<p>{BRAND} makes original, slightly odd designs for people
whose taste doesn't fit the default settings. Every piece starts as an idea
we actually like — botanical diagrams, weird typography, things your favorite
coworker would point at — and gets printed on demand, one at a time.</p>
<p>No warehouse, no landfill of unsold inventory: your order is printed and
shipped by our production partner when you place it.</p>
<p>AI-assisted design, human-directed taste.</p>"""


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


def _theme_sections(theme_id: int) -> set[str]:
    assets = api("GET", f"/themes/{theme_id}/assets.json").get("assets", [])
    return {a["key"].removeprefix("sections/").removesuffix(".liquid")
            for a in assets if a["key"].startswith("sections/")}


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


def homepage_template() -> dict:
    """Dawn-style JSON template: hero, four featured collections, values."""
    sections = {
        "hero": {"type": "rich-text", "blocks": {
            "h": {"type": "heading", "settings": {"heading": BRAND}},
            "t": {"type": "text",
                  "settings": {"text": f"<p>{TAGLINE} Designed oddly, printed "
                                       "on demand, shipped to your door.</p>"}},
            "b": {"type": "button",
                  "settings": {"button_label": "Shop everything",
                               "button_link": "shopify://collections/all"}},
        }, "block_order": ["h", "t", "b"], "settings": {}},
    }
    order = ["hero"]
    for handle, (title, _, _) in SMART_COLLECTIONS.items():
        sid = f"featured-{handle}"
        sections[sid] = {"type": "featured-collection",
                         "settings": {"title": title, "collection": handle}}
        order.append(sid)
    sections["values"] = {"type": "multicolumn", "blocks": {
        "v1": {"type": "column", "settings": {
            "title": "Original designs",
            "text": "<p>Made here, found nowhere else.</p>"}},
        "v2": {"type": "column", "settings": {
            "title": "Printed just for you",
            "text": "<p>Each order is produced on demand.</p>"}},
        "v3": {"type": "column", "settings": {
            "title": "No waste",
            "text": "<p>Nothing sits unsold in a warehouse.</p>"}},
    }, "block_order": ["v1", "v2", "v3"], "settings": {}}
    order.append("values")
    return {"sections": sections, "order": order}


def setup_homepage() -> None:
    theme = _active_theme()
    print(f"  · active theme: {theme['name']} (id {theme['id']})")
    available = _theme_sections(theme["id"])
    needed = {"rich-text", "featured-collection", "multicolumn"}
    if not needed <= available:
        print(f"  ! theme lacks sections {needed - available} — homepage left "
              f"untouched. Available: {sorted(available)[:20]}")
        return
    _write_theme_file(theme["id"], "templates/index.json",
                      json.dumps(homepage_template(), indent=2))
    print("  + homepage: hero + 4 featured collections + values row")


if __name__ == "__main__":
    print("[storefront design]\n")
    failures = 0
    for step in (setup_collections, setup_about_page, setup_homepage):
        try:
            step()
        except Exception as e:
            failures += 1
            print(f"  ! {step.__name__}: {e}")
    print("\nManual (admin-only, ~1 min): Settings -> General -> store name "
          f"= \"{BRAND}\". Menus need the write_online_store_navigation "
          "scope if you ever want them automated; the default menu works.")
    exit(1 if failures else 0)
