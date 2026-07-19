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


def setup_homepage() -> None:
    """Rebrand the live Horizon homepage in place: edit the hero copy and
    clone the theme's own product-list section once per collection, so every
    setting comes from the theme itself and stays schema-valid."""
    theme = _active_theme()
    print(f"  · active theme: {theme['name']} (id {theme['id']})")
    asset = api("GET", f"/themes/{theme['id']}/assets.json",
                params={"asset[key]": "templates/index.json"})
    tpl = json.loads(asset["asset"]["value"])
    sections, order = tpl["sections"], tpl["order"]

    hero_id = next((s for s in order if sections[s].get("type") == "hero"), None)
    proto_id = next((s for s in order
                     if sections[s].get("type") == "product-list"), None)
    if not (hero_id and proto_id):
        print(f"  ! unexpected structure (types: "
              f"{[sections[s].get('type') for s in order]}) — left untouched")
        return

    hero = sections[hero_id]
    for blk in hero.get("blocks", {}).values():
        if blk.get("type") == "text":
            blk["settings"]["text"] = (
                f"<h1>{BRAND}</h1><p>{TAGLINE} Designed oddly, printed on "
                "demand, shipped to your door.</p>")
            break

    proto = sections[proto_id]
    new_sections, new_order = {hero_id: hero}, [hero_id]
    for handle in SMART_COLLECTIONS:
        sid = f"product_list_{handle.replace('-', '_')}"
        sec = copy.deepcopy(proto)
        sec["settings"]["collection"] = handle
        sec["settings"]["max_products"] = 4
        new_sections[sid] = sec
        new_order.append(sid)
    tpl["sections"], tpl["order"] = new_sections, new_order

    _write_theme_file(theme["id"], "templates/index.json",
                      json.dumps(tpl, indent=2))
    print("  + homepage: branded hero + 4 collection grids (Horizon-native)")


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
