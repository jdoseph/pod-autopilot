# CLAUDE.md

Context for Claude Code working in this repo. Read this fully before making changes.

## What this project is

`pod-autopilot` — an AI pipeline that turns a trend signal into a published, self-fulfilling
print-on-demand Etsy t-shirt listing:

```
seed niche → trends → Claude ideation → image gen → trademark gate → Printify (upload+publish to Etsy) → automatic fulfillment
```

The order→print→pack→ship loop is handled by Printify's Etsy integration once a listing is
published; there is no code to write for fulfillment.

## Two hard constraints (do not "solve" by working around them)

1. **Etsy has NO trending/marketplace-discovery API.** The Open API v3 only exposes the
   seller's own shop (listings/orders/shop). Never add code that scrapes Etsy search — it
   violates their ToS and hits anti-bot walls. Trend signal comes from proxies only
   (Google Trends via `trends.from_google`, or a keyword-tool CSV via `trends.from_csv`).
2. **IP risk is the #1 way this shop gets banned.** Generate ORIGINAL art. Never reference
   trademarked brands/characters/lyrics in prompts or copy. `screening.py` is the guardrail.
   When in doubt, make the gate stricter, not looser. Etsy also requires disclosing Printify
   as the production partner in each listing.

## Module map

| File | Responsibility | Status |
|------|----------------|--------|
| `config.py` | Env/config loader | done |
| `trends.py` | Trend proxy (Google Trends + CSV) → `Trend` list | done |
| `ideation.py` | Claude → original concepts + Etsy copy as JSON `Concept`s | done |
| `design.py` | Prompt → print-ready PNG. **Provider is a stub — needs a real impl.** | STUB |
| `screening.py` | Trademark/keyword gate. Blocklist is a seed; USPTO check unverified. | partial |
| `printify_client.py` | upload_image → create_product → publish_product; catalog helpers | done, unhardened |
| `pipeline.py` | Orchestrates all stages; review-first default, `--auto-publish` flag | done |

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                   # fill in keys

python -m pod_autopilot.printify_client --catalog      # find blueprint id
python -m pod_autopilot.printify_client --blueprint N  # find provider + variant ids
python -m pod_autopilot.pipeline --seed "cottagecore" --count 3               # review-first
python -m pod_autopilot.pipeline --seed "cottagecore" --count 3 --auto-publish
```

## Conventions

- Python 3.11+, standard library + `requests`/`anthropic`/`pytrends`/`Pillow` only unless justified.
- Keep modules single-responsibility and independently runnable (`if __name__ == "__main__"`).
- **Never** hardcode secrets — everything through `config.py`/`.env`.
- Every external API call needs a timeout; network-facing code needs retry/backoff.
- Prefer adding tests (pytest) alongside changes; the pipeline must be runnable offline in a
  mock/paper mode without spending money or publishing anything.
- Work on a branch, commit in small logical units, run tests before declaring done.

## Definition of done, per open workstream

- **design.py**: real provider call, output is transparent-background PNG, ≥4500px long edge
  (≈300 DPI full-front), validated (alpha channel present, dimensions checked).
- **screening.py**: expanded per-niche blocklist, working USPTO live-mark check (verify the
  current endpoint before coding it), fuzzy match, logged rejections.
- **printify_client.py**: idempotent publish (no dupes), retry/backoff on 429/5xx, clear errors.
- **pipeline.py**: run ledger (SQLite) so topics/titles aren't repeated; disclosure line added;
  never publishes below a configured margin floor.
