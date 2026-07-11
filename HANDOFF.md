# Claude Code handoff prompts

Paste these into Claude Code one at a time, in order, from inside the `pod-autopilot/` repo.
Each is scoped to roughly one session. Review the diff and let tests pass before moving on.

---

## Prompt 0 — Orient & set up the repo

```
Read every file in this repo including CLAUDE.md so you understand the pipeline end to end.
Then:
1. git init, add a sensible .gitignore for a Python project (.venv, .env, output/, __pycache__).
2. Create and activate a venv and install requirements.txt; confirm all modules import.
3. Confirm my understanding of the architecture and the two hard constraints back to me in
   3-4 bullets, and list the open workstreams from CLAUDE.md in the order you'd tackle them.
Do NOT change any logic yet — this is orientation only. Stop and wait for my go-ahead.
```

## Prompt 1 — Offline mock/paper mode + tests (do this before touching real APIs)

```
Before we integrate any paid API, make the whole pipeline runnable offline so we can develop
without spending money or publishing anything.

- Add a --dry-run/mock mode (env flag MOCK=1) where trends, ideation, design, and Printify
  are replaced by deterministic fakes: canned trend topics, a canned Concept, a locally
  generated solid-color PNG for art, and a no-op Printify client that logs what it WOULD do.
- Set up pytest with tests covering: trend parsing, ideation JSON parsing (including a
  malformed-response case), the screening gate (a clean concept passes, an infringing one is
  blocked), and a full mock pipeline run that produces output/ files and never hits the network.
- Add a Makefile or a couple of scripts: `make test`, `make run-mock`.
Run the tests and show me they pass.
```

## Prompt 2 — Real image generation + print-ready output

```
Implement design.py against a real text-to-image provider. I'll use <PROVIDER — e.g. Ideogram
/ Recraft / Flux via Replicate>; here are its docs: <URL>. Requirements:
- Output a transparent-background PNG (remove background if the provider doesn't return alpha).
- Upscale/validate to >=4500px on the long edge (~300 DPI for a full-front tee).
- Validate the result: assert an alpha channel exists and dimensions meet the threshold;
  raise a clear error otherwise.
- Add a retry with backoff and a timeout. Keep it behind the same generate_design() signature
  so the pipeline and mock mode are unaffected.
Add a unit test using a small recorded/fixture response (don't call the live API in tests).
```

## Prompt 3 — Harden the Printify client

```
Make printify_client.py production-safe:
- Add retry with exponential backoff on 429 and 5xx, respecting Retry-After.
- Make publishing idempotent: persist a mapping of design-slug -> printify product_id so a
  re-run never creates or publishes a duplicate. Skip if already published.
- After create_product, fetch and save the generated mockup image URLs into the design folder.
- Surface API errors with the response body, not just the status code.
- Add a `--dry-run` path consistent with the mock mode from Prompt 1.
Add tests using mocked HTTP responses (responses/respx or monkeypatched requests).
```

## Prompt 4 — Strengthen the trademark gate

```
Harden screening.py — this is our ban-prevention layer, so bias toward strictness.
- Restructure the blocklist into categories and load it from a data file (e.g. blocklist.yaml)
  so it's easy to extend per niche. Seed it heavily for the niches in my seed list.
- Add fuzzy/substring matching for obvious evasions (spacing, leetspeak, plurals).
- Verify the CURRENT USPTO trademark search endpoint before coding it (the one in the file is
  a guess). Implement a best-effort live-mark check on the title's key phrase; fail closed on a
  positive match, fail open on network errors, and log every decision.
- Log all rejections with reasons to a file so I can audit what's being filtered.
Add tests for the fuzzy matcher and the fail-open/fail-closed behavior.
```

## Prompt 5 — Run ledger, dedupe, Etsy compliance, margin floor

```
Add persistence and compliance to pipeline.py:
- SQLite ledger recording every topic, title, slug, screening result, and publish status, so
  future runs skip already-used topics/titles and never repeat a design.
- Inject the Printify production-partner disclosure line into every description automatically
  (Etsy requires it) and confirm it survives publishing.
- Add a margin floor: compute retail vs Printify base+shipping cost and refuse to publish any
  variant below a configurable minimum margin; log skips.
Add tests for dedupe and the margin-floor guard.
```

## Prompt 6 — Autonomous scheduling & deployment

```
Make it run on a cadence without me. I'm comfortable on AWS.
- Wrap the pipeline in a runner entrypoint that takes a list of seed niches and a per-run cap.
- Provide two deployment options and implement the one I pick: (a) a cron + systemd unit for a
  small box, or (b) an AWS Lambda + EventBridge schedule, secrets via SSM Parameter Store,
  logs to CloudWatch, and a failure alarm to SNS.
- Add structured logging and a run summary (counts published/staged/skipped) emitted at the end.
- Default the scheduled runs to review-first; require an explicit env flag to auto-publish.
Give me the deploy steps and a Dockerfile if it helps.
```

---

## Tips for driving Claude Code well here

- Let it explore and plan before editing; for the bigger prompts (2, 6) ask it to outline its
  plan first, approve, then implement.
- Keep it on a branch per workstream and commit in small units; review each diff.
- Insist tests stay green and mock mode stays offline after every change.
- If it proposes loosening the trademark gate or scraping Etsy, push back — those are the two
  constraints in CLAUDE.md.
