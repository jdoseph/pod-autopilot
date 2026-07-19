# POD Autopilot

Automated print-on-demand pipeline: Claude researches concepts → Flux renders
art → two-gate IP screen → Printify product → publish to Shopify/Etsy →
Printify auto-fulfills orders. Runs unattended on GitHub Actions
(`.github/workflows/pipeline.yml`).

## Layout

- `src/orchestrator.py` — daily entry point (`python -m src.orchestrator`)
- `src/research.py` → `design.py` → `ip_check.py` → `printify_client.py` → `listing.py` — the pipeline stages, in order
- `src/budget.py` — cost ledger (`runs/ledger.jsonl`) + net-gain governor gating every publish
- `src/claude_client.py` — tiered model wrapper (smart=Sonnet, cheap=Haiku), prompt caching, cost logging
- `src/analytics.py` / `digest.py` — weekly kill/scale loop + email report
- `src/support.py` / `marketing.py` — IMAP support agent, Pinterest pins
- `runs/` — ledger + per-design provenance JSON; committed back by CI on purpose (keep it)

## Commands

- Test: `py -3 -m pytest`
- Daily run: `py -3 -m src.orchestrator` (stages in review mode; `--approve` publishes staged)

## Invariants — do not weaken

- The IP gate fails closed (both gates must return approved + low risk). Never loosen to boost throughput.
- `listing.AI_DISCLOSURE` is appended to every description (Etsy AI-disclosure policy). Never remove.
- Every real cost is logged to the ledger; `budget.publishing_allowed()` must be checked before any publish.
- USPTO phrase search has no free public API — it stays disabled unless `USPTO_SEARCH_URL` is set, and fails open to the Claude-knowledge screen.
- Printify API is v1 (`api.printify.com/v1`).
