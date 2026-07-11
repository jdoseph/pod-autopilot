# Deploying pod-autopilot (local, Windows)

This runs the whole pipeline on a cadence on your own Windows machine using the
built-in **Task Scheduler** — no cloud, no servers. Everything (the SQLite run
ledger, output art, logs) stays on disk under the repo.

Scheduled runs are **review-first by default**: they generate and stage designs
into `output/` but do **not** publish to Etsy. You opt into publishing explicitly.

---

## 1. One-time setup

```powershell
# from the repo root
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env      # then edit .env and fill in your keys
```

Fill in `.env`:

- `ANTHROPIC_API_KEY` (ideation), `IMAGE_API_KEY` + `IMAGE_PROVIDER=recraft` (art).
- `PRINTIFY_API_TOKEN`, `PRINTIFY_SHOP_ID`, and the blueprint / provider / variant
  ids (discover them with the catalog explorer below).
- `SEEDS` — comma-separated niches to process each run (e.g. `cottagecore,boho`).
- `PER_RUN_CAP` — max designs per seed per run.
- `AUTO_PUBLISH` — leave `0` for review-first; set `1` only when you're ready to
  let scheduled runs publish to Etsy.

Discover Printify ids:

```powershell
.\.venv\Scripts\python.exe -m pod_autopilot.printify_client --catalog
.\.venv\Scripts\python.exe -m pod_autopilot.printify_client --blueprint <id>
```

## 2. Try it by hand first

```powershell
# fully offline dry run — no keys, no network, no spend:
$env:MOCK=1; .\.venv\Scripts\python.exe -m pod_autopilot.runner --seeds "cottagecore" --cap 2

# real, review-first (needs keys; stages into output\, does not publish):
.\.venv\Scripts\python.exe -m pod_autopilot.runner
```

Inspect what's been generated / recorded:

```powershell
.\.venv\Scripts\python.exe -m pod_autopilot.ledger --path output\run_ledger.db --list
```

## 3. Schedule it

`install-task.ps1` registers a Task Scheduler job that runs `run-scheduled.ps1`
daily. The launcher uses the venv, reads `SEEDS`/`PER_RUN_CAP`/`AUTO_PUBLISH` from
`.env`, and appends output to `logs\run-<date>.log`.

```powershell
# daily at 09:00 (default), review-first:
.\scripts\install-task.ps1

# a different time:
.\scripts\install-task.ps1 -Time 07:30

# run it right now to test the scheduled path:
Start-ScheduledTask -TaskName PodAutopilotDaily

# remove the schedule:
.\scripts\install-task.ps1 -Uninstall
```

No admin rights are required; the task registers under your user account.

## 4. Turning on auto-publish

When you've reviewed enough staged designs and trust the gate:

1. Set `AUTO_PUBLISH=1` in `.env`.
2. Make sure `PRINTIFY_VARIANT_IDS` is set — each variant is checked against
   `MIN_MARGIN` and only profitable variants are published.
3. The next scheduled (or manual) run will publish. The run ledger prevents
   repeating topics/titles, and the Printify publish ledger prevents duplicate
   listings, so re-runs are safe.

## 5. Where things live

| Path | What |
|------|------|
| `output\<slug>\` | art PNG, `concept.json`, saved mockups per design |
| `output\run_ledger.db` | SQLite ledger of every topic/title/slug/publish status |
| `output\publish_ledger.json` | slug → Printify product id (publish idempotency) |
| `output\screening_rejections.log` | audit log of everything the gate blocked |
| `logs\run-<date>.log` | scheduler run output |

## Notes

- Keep the machine on (or set the task to wake it) for scheduled runs; the task is
  configured with `-StartWhenAvailable` so a missed run fires when the box is next up.
- To change seeds/cadence, edit `.env` (seeds) or re-run `install-task.ps1 -Time`.
- Everything remains runnable offline with `MOCK=1` for development.
