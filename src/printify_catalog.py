"""Query Printify's live catalog to find current blueprint IDs.
Run: python -m src.printify_catalog
"""
import os

import requests

BASE = "https://api.printify.com/v1"
HEADERS = {"Authorization": f"Bearer {os.environ['PRINTIFY_API_KEY']}"}


def get_blueprints():
    """Fetch all available print blueprints from Printify catalog."""
    r = requests.get(f"{BASE}/catalog/blueprints.json", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["blueprints"]


if __name__ == "__main__":
    print("Printify Blueprints (current catalog)\n")
    blueprints = get_blueprints()

    # Group by title for easy scanning
    by_title = {}
    for b in blueprints:
        title = b.get("title", "").lower()
        if title not in by_title:
            by_title[title] = []
        by_title[title].append(b)

    # Print sorted by popularity/type
    targets = ["t-shirt", "tee", "shirt", "mug", "coffee", "tote", "bag", "poster"]
    found = set()

    for target in targets:
        for title, items in sorted(by_title.items()):
            if target in title and title not in found:
                for b in items:
                    print(f"{b['id']:3d}  {b['title'][:50]}")
                found.add(title)
                break

    print(f"\nTotal blueprints: {len(blueprints)}")
    print("\nTo use a blueprint, add to BLUEPRINTS in printify_client.py:")
    print('  "product-type": {"blueprint_id": <ID>, "preferred_provider": <provider_id>}')
