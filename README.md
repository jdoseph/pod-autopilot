# POD Autopilot — fully automated print-on-demand pipeline

Claude finds product opportunities → an image model renders the art → an IP
gate screens it → Printify creates the product → Claude writes the listing →
it publishes to your store → **Printify auto-fulfill prints and ships every
order directly to the customer with zero involvement from you.**

## Architecture

```
cron (daily)                                cron (weekly)
     │                                            │
     ▼                                            ▼
orchestrator.py                              analytics.py
  1. research.py   → ranked concepts (Claude)  pull Shopify sales
  2. design.py     → image prompt (Claude)     kill 30-day zero-sale listings
                   → PNG (Replicate/Flux)      queue variants of winners
  3. ip_check.py   → USPTO + Claude gate            │
  4. printify_client.py → product + mockups         └─→ feeds next research run
  5. listing.py    → SEO copy + pricing (Claude)
  6. publish       → Shopify/Etsy
                        │
                        ▼
              customer orders (untouched)
                        │
              Printify auto-fulfill → prints → ships to customer
```

## One-time setup (~1 hour, the only manual part)

1. **Printify account** → connect your Shopify or Etsy store → Settings →
   turn ON **auto-fulfillment** (orders produce & ship automatically).
2. API keys into env (or a `.env` you export):
   ```
   ANTHROPIC_API_KEY=...
   PRINTIFY_API_KEY=...
   REPLICATE_API_TOKEN=...
   SHOPIFY_STORE=yourstore.myshopify.com
   SHOPIFY_ACCESS_TOKEN=...        # custom app, read/write products+orders
   APPROVAL_MODE=review            # switch to "auto" once you trust it
   MAX_PUBLISHES_PER_DAY=5
   ```
3. `pip install -r requirements.txt`
4. Schedule it (crontab or GitHub Actions):
   ```
   0 9 * * *   cd pod-autopilot && python -m src.orchestrator
   0 10 * * 1  cd pod-autopilot && python -m src.analytics
   ```

## Running

```bash
python -m src.orchestrator            # daily run (stages products in review mode)
python -m src.orchestrator --approve  # publish today's staged products
python -m src.analytics               # weekly kill/scale loop
```

## Honest operating notes

- **Start in review mode.** Glance at `runs/<date>/*.json` + PNGs for two
  weeks. When rejects are consistently correct and designs look right, flip
  `APPROVAL_MODE=auto` and it's hands-off.
- **The IP gate fails closed on purpose.** A discarded design costs ~$0.05 in
  API calls; a trademark strike can end the store. Never loosen it to boost
  throughput.
- **What stays manual forever:** payment disputes/chargebacks (platforms
  require a human response), tax/legal setup, and platform policy emails.
  Expect ~15 min/week, not zero — but fulfillment truly is zero.
- **Traffic is the real bottleneck.** This pipeline automates supply.
  Marketplace SEO (Etsy) gives organic discovery; Shopify needs external
  traffic. A natural next module: auto-generate Pinterest/TikTok posts per
  published product.
- **Cost engineering (v2):** model tiering (Haiku for copy, Sonnet only for
  research + IP judgment), prompt caching on all system prompts, one bulk
  Haiku call for the day's listings, Flux Schnell for test images (pro model
  reserved for proven winners), and IP screening BEFORE any image is rendered
  so rejected concepts cost ~$0.003 instead of $0.05. Net: ~$0.10/day of LLM
  spend at 5 products/day — Etsy's $0.20 listing fees are now ~90% of total
  cost, so the budget governor manages those, not tokens.
- **Net-gain enforcement:** every LLM call, image render, and listing fee is
  logged to `runs/ledger.jsonl` at actual token cost. Before every publish,
  the governor checks: MTD spend <= MTD revenue x SPEND_RATIO (default 25%)
  + GRACE_BUDGET (default $30). Under the cap, it publishes; over it, it
  pauses until revenue catches up — so the worst possible month is
  -$GRACE_BUDGET, and any month past cold-start is structurally net-positive.
- **Next lever if scaling past ~20 products/day:** migrate `ask()` to the
  Message Batches API for a further 50% off all tokens (the daily cron is
  already async-tolerant).

## Hands-off handoff (v4 — final)

Everything runs unattended on GitHub Actions — no server, no laptop:
daily 9am ET: pipeline + support agent; Monday: analytics + digest email.
`runs/` (ledger, provenance, flagged emails) is committed back to the repo
so state survives between runs.

ONE-TIME SETUP (the only time you touch it, ~90 min total):
1. Create accounts + connect: Printify -> Shopify (auto-fulfill ON, payment
   method saved so Printify can charge production costs per order).
2. Push this repo to GitHub (private) and add all secrets from
   .github/workflows/pipeline.yml (Settings -> Secrets -> Actions).
3. Shop settings: production partner declared, "Designed by" attribution,
   refund/return policy page published, support email address created.
4. Recommended before flipping the switch: LLC + business bank account.
Then enable the workflow. After that the system publishes, pins, fulfills,
answers routine support, kills losers, scales winners, enforces the budget,
and emails you a weekly report.

WHAT "ZERO-TOUCH" STILL CANNOT ABSORB (by platform/legal design, not code):
- Chargebacks & disputes: auto-quarantined to the weekly digest, never
  auto-answered. Ignoring them forfeits them and enough forfeits kill payment
  processing — budget ~10 min when the digest flags one.
- Platform policy emails (Etsy/Shopify/Printify) go to you, not the bot.
- Taxes: the ledger is your expense record; filing is yours.
- Full-auto on Etsy is policy-fragile (see compliance section) — the
  default target for auto mode is Shopify + Pinterest traffic. If you point
  it at Etsy, human curation is what satisfies "seller-directed" AI use.

## Legal & platform compliance (v3 — built in)

- **Etsy AI disclosure (enforced since Jan 14, 2026):** every description gets
  an auto-appended factual AI-disclosure line (`listing.AI_DISCLOSURE`). Do
  not remove it — Etsy removed ~12K listings in Q1 2026 for missing
  disclosure. ONE-TIME MANUAL STEPS in Etsy shop settings: add Printify as a
  named production partner; on listings use "Designed by [you]" attribution,
  who_made = "I did", when_made = "Made to order".
- **Two-gate IP screen:** gate 1 (text/USPTO) before any spend; gate 2
  (Claude vision on the rendered PNG) catches logo likeness, character
  resemblance, and artist-style drift the text gate can't see. Both verdicts
  are archived per product in `runs/` — keep them; documented good-faith
  screening rebuts willfulness in any infringement dispute.
- **Provenance archive:** `runs/<date>/<tag>.json` stores concept, prompt,
  model, and verdicts per design — this is the "prove you originated the
  design" evidence Etsy's Creativity Standards expect.
- **Listing copy guardrails:** hard bans on "handmade", delivery promises,
  fake scarcity, and health claims are frozen in the listing system prompt.
- **Human creative direction:** review mode isn't just QA — a human curating
  niches and approving staged designs is what keeps this inside Etsy's
  "AI as a tool the seller directs" allowance. Fully-auto publishing to Etsy
  is policy-fragile; auto mode is safer aimed at Shopify.
- **Not automated (talk to professionals):** LLC formation before auto mode
  (Printify/Etsy ToS put IP liability on you), sales-tax registration for
  your home state if selling via your own Shopify store, and never
  auto-respond to chargebacks/disputes.

## Extending

- `research.gather_signals()` — wire in pytrends, Reddit, Etsy autosuggest.
- `design.render()` — swap Flux for Ideogram when designs are text-heavy.
- Add `support.py` — poll the store inbox, let Claude answer tracking/sizing
  questions, escalate disputes only.
