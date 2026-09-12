# Roblox Thumbnail Manager

An automated Roblox Home Page thumbnail testing system.

A scheduled **GitHub Action** queries Roblox thumbnail analytics every 6 hours,
appends a permanent CSV history, retires clearly weaker thumbnails, fills the
open slots with AI-generated candidates, and publishes a static dashboard with
**GitHub Pages**.

The system is built on Roblox's Home Page thumbnail personalization APIs and
its Analytics Query API. Both are Experimental, and several of their behaviours
below are undocumented and were established by probing the live API — those are
called out where they matter.

---

## System Behavior

Each run performs this sequence:

```text
Fetch the current active set from Roblox
                ↓
Query analytics for every tracked thumbnail
                ↓
Append a snapshot for the active set
                ↓
Evaluate the active set, if eligible
                ↓
Deactivate weaker thumbnails
                ↓
Activate any queued candidate
                ↓
Generate candidates for the open slots
                ↓
Activate what was just generated
                ↓
Resolve thumbnail image URLs
                ↓
Describe any creative that lacks a description
                ↓
Rebuild the dashboard data and commit
```

The run happens whether or not a thumbnail changes. Every mutating step is
individually gated by config, so the system can be run read-only.

---

# Selection Algorithm

## 1. Eligibility

Nothing is ranked or retired unless **both** conditions hold:

- Every active thumbnail has trustworthy metrics. Roblox returns no analytics
  rows at all for a thumbnail that has served no traffic, which is
  indistinguishable from a lookup failure, so this is treated as unknown rather
  than as zero.
- Every active thumbnail has at least `minimum_impressions` (1,000).

A newly activated thumbnail normally starts below the threshold, so the gate
pauses further ranking until it accumulates traffic. When the gate is closed the
run still records metrics and updates the dashboard, and the dashboard names the
thumbnails holding it shut.

## 2. Rank by Qualified Play Through Rate

Active thumbnails are ranked by **Qualified Play Through Rate**, derived as:

```text
qualified plays / impressions
```

over the queried window. This matches Roblox's own definition — its CSV export
reports 243 qualified plays against 7,302 impressions as `0.033279`.

The API's own `ThumbnailQualifiedPTR` metric is deliberately **not** used for
ranking. It is a *per-bucket* rate, so its newest bucket can describe a trivial
sample: one thumbnail reported 6.78% from a 59-impression day against 2.66%
across 7.35M impressions. Ranking on that retires the wrong creatives.

A rate derived from fewer than 50 impressions is left unset, so a quiet creative
reads as unknown rather than as a genuine 0% performer.

## 3. Deactivation

Two rules apply together, and their union is retired:

**Range criterion.** Every thumbnail whose qPTR is more than
`qptr_deactivation_gap_percentage_points` below the best. A thumbnail exactly at
the cutoff stays active.

```text
best 8.4%, gap 0.2 points -> cutoff 8.2%

Thumbnail A    8.40%    KEEP
Thumbnail B    8.25%    KEEP
Thumbnail C    8.20%    KEEP   (exactly at the cutoff)
Thumbnail D    8.19%    DEACTIVATE
```

**Bottom-N criterion.** The lowest `deactivate_bottom_n` performers (default 3),
applied only when more than that many are active so the set is never emptied.

Note what this means in practice: with 5 active thumbnails, **three are retired
every evaluation regardless of how close they are**. Five thumbnails within 0.05
points of each other still lose three. The bottom-N rule is the broader net at
this scale, and the range criterion rarely adds to it.

### Unit convention

The gap is in **percentage points**, not percent. Roblox returns qPTR as a
decimal, so `0.2` points is compared as `0.002`.

## 4. Refill

Roblox serves at most **5** thumbnails at a time, so `target_active_thumbnails`
is 5. Open slots are filled from the queue, then from candidates generated
during the same run.

---

# AI Thumbnail Queue

Candidates live in `thumbnails/queue/` as an image plus a JSON sidecar holding
its generation timestamp, prompt, source thumbnail, source description, provider
and model.

The queue is **not committed**. A candidate is normally uploaded and activated
in the same run, and the copy that matters afterwards is the creative registry
plus the image Roblox now hosts. A candidate that is generated but not activated
— because moderation is still pending, say — does not survive to the next run
and is simply regenerated.

## Generation is demand-driven

Candidates are generated only when there is a slot for one:

```text
generate = (target_active_thumbnails - active count) - queued count
```

```text
5 active, 0 queued   ->  generate 0   (no slot to fill)
4 active, 0 queued   ->  generate 1
3 active, 1 queued   ->  generate 1
3 active, 2 queued   ->  generate 0   (already covered)
```

This keeps cost proportional to need and keeps candidates fresh, since each is
bred from whichever thumbnails are winning when the slot appears rather than
sitting in a buffer while the leaders change.

A slot is refilled within the same run: queued candidates are activated before
replenishment, and anything generated afterwards is activated in a second fill
pass. The consequence is that a generated image can go live seconds after it is
created, with no opportunity to review it. Set `allow_thumbnail_uploads` to
`false` to hold candidates in the queue for inspection.

## Choosing the source thumbnail

A candidate is bred from one of the **top-performing** active thumbnails that
has a usable description. Eligible sources are the best active qPTR and everyone
within the same gap the deactivation rule uses, so new creatives only ever
descend from thumbnails good enough to keep:

```text
Thumbnail A    8.40%    SOURCE  (best)
Thumbnail B    8.25%    SOURCE
Thumbnail C    8.10%    not eligible
```

A source must also clear the 1,000-impression gate; below that its rate is not
trustworthy enough to call it a winner, and a thumbnail with no metrics never
qualifies. The best qPTR is measured among qualifying thumbnails only, so a
thin-data outlier cannot raise the bar and starve the pool.

This differs in scope from deactivation: that waits for *every* active thumbnail
to clear the gate before ranking anything, whereas source eligibility is
per-thumbnail, so proven winners keep breeding while a new thumbnail accumulates
traffic. If nothing qualifies, generation is skipped for that run.

`source_thumbnail_selection` chooses between `weighted_random` (weighted by
qPTR) and `random`.

## Prompts and descriptions

`prompt_builder.py` composes the generation prompt from the source thumbnail's
description. The generated image then gets **its own** description from Gemini
vision once it is archived — the seed text is recorded separately as
`source_description` and never copied onto the new creative. Copying it forward
previously left whole lineages sharing a single ancestor's description, which
then re-seeded every later prompt.

Descriptions are filled in for any creative that lacks one, so existing Roblox
thumbnails are described automatically rather than by hand.

---

# Queue Lifecycle

```text
GENERATED -> QUEUED -> UPLOADING -> MODERATION -> ACTIVATED -> TRACKED
```

On successful activation the candidate is removed from the queue, its image is
archived locally, and the creative registry records its Roblox asset id,
activation timestamp, prompt, source thumbnail and status.

An upload in flight is recorded in `data/state.json` as `pending_upload`. If a
run ends before moderation finishes, the next run resumes that operation rather
than uploading the same image again and creating a duplicate asset.

---

# Repository Layout

```text
roblox-thumbnail-manager/
├── README.md
├── requirements.txt
├── .gitignore
├── .env.example
├── config.json
│
├── src/
│   ├── main.py              # one complete run
│   ├── config.py            # config.json + environment secrets
│   ├── models.py            # ThumbnailMetrics, ThumbnailRecord, SelectionResult
│   ├── roblox_api.py        # every Roblox HTTP call
│   ├── analytics.py         # analytics queries and normalisation
│   ├── selector.py          # the deactivation policy
│   ├── queue.py             # thumbnails/queue/ management and sizing
│   ├── prompt_builder.py    # prompt composition, source selection
│   ├── image_generator.py   # provider abstraction, model discovery, retries
│   ├── image_moderation.py  # pre-queue safety check
│   ├── describer.py         # Gemini vision descriptions
│   ├── imaging.py           # image format detection
│   ├── notify.py            # email notification
│   ├── history.py           # data/ persistence
│   └── dashboard.py         # docs/ data publication
│
├── data/                    # committed: the only state between runs
│   ├── metrics.csv
│   ├── thumbnails.csv
│   └── state.json
│
├── thumbnails/queue/        # not committed
│
├── docs/                    # GitHub Pages
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   ├── data/
│   │   ├── metrics.csv
│   │   ├── thumbnails.csv
│   │   ├── latest.json
│   │   ├── queue.json
│   │   └── images.json
│   └── images/thumbnails/   # local copies, not committed
│
├── tests/
└── .github/workflows/thumbnail-manager.yml
```

`data/` must stay committed. GitHub Actions runners are wiped after every job,
so the repository is the only place state survives: without `thumbnails.csv`
every run would re-register the active set as new creatives and lose all
prompts, lineage and descriptions; without `metrics.csv` there would be no
history beyond Roblox's rolling 30-day window; without `state.json` the sequence
numbering restarts and in-flight uploads are repeated.

---

# Module Notes

## `src/roblox_api.py`

Every Roblox-specific HTTP call, isolated because these APIs are Experimental.
Retries transient errors, and never logs credentials.

Behaviours established against the live API:

- **Uploads require the multipart field `files`** (plural). With any other name
  Roblox still answers `200` but registers nothing, returning an empty
  `fileToOperationIdDict`.
- **Upload status needs the operation id.** `GET .../uploads/status` is
  meaningless without `operationIds`; with it, `uploadStatus` is `1` while
  processing and `2` once finished, and the result — `assetId`,
  `homepageThumbnailId`, `moderationStatus` — arrives in
  `uploadThumbnailStatusDict`, keyed by operation id.
- **Activation takes `homepageThumbnailIds`, not asset ids.** Asset ids are
  rejected with "no homepage thumbnail ids provided".
- **`/personalization/update` returns 500; `/personalization/create` works.** It
  replaces the active set and returns the new config id.
- **The thumbnails list returns every uploaded thumbnail**, not just the serving
  set. Only entries whose `personalizedConfigStatus` is `Active` are live.

## `src/analytics.py`

Queries and normalises:

```text
ThumbnailImpressions          ThumbnailQualifiedPTR
ThumbnailQualifiedPlays       ThumbnailAverageSessionLengthMinutes
ThumbnailL7QualifiedPTR       ThumbnailWinningSegments
```

broken down by the `ThumbnailAsset` dimension.

- Responses arrive as a long-running **operation envelope** (`path`, `done`,
  `response`) and are polled until complete.
- Buckets are **per-day, not cumulative** — values rise and fall — so counts are
  summed across the window. Taking the newest bucket records only a partial day.
- The window **must end at tomorrow 00:00**. Day buckets are half-open, so an
  `endTime` of today 00:00 excludes today entirely, and any thumbnail whose
  traffic began today returns no rows at all and looks unmeasured.

## `src/image_generator.py`

Wraps the image provider. Google renames and retires image models often, so the
configured model is a preference: if the key cannot use it, an available
image-capable model is discovered from the API instead. Both the Imagen
`predict` path and Gemini inline-image responses are supported.

A model that answers with no image is usually transient — a safety filter or
capacity — so that case is retried with backoff up to `generation_retries`,
while permanent failures (missing key, unusable model) fail immediately.

The file extension is taken from the returned bytes rather than assumed;
providers differ, and `gemini-3-pro-image` returns JPEG.

## `src/image_moderation.py`

Checks a generated image with Gemini vision before it is queued, and rejects it
if it is flagged in a category Roblox is likely to refuse. It **fails open**: if
the check itself errors, the image proceeds, so a moderation outage cannot stall
generation.

## `src/selector.py`

The deactivation policy, as pure logic with no I/O, and the source-eligibility
rule. This is the most heavily tested module because it changes public
thumbnails automatically.

## `src/history.py`

Maintains `data/`. Writes are atomic (temp file plus `os.replace`) so an
interrupted run cannot corrupt history.

---

# Performance History

## `data/metrics.csv`

One row per active thumbnail per run:

```csv
timestamp,thumbnail_key,roblox_asset_id,status,impressions,qualified_plays,qualified_ptr,l7_qualified_ptr,average_session_minutes,winning_segments
```

Only the **serving set** is recorded. A retired creative's numbers are a rolling
30-day window that keeps drifting after it stopped serving, so further snapshots
add no information while growing the file without bound. Deactivation happens
after the metrics step, so a creative retired during a run still has its final
snapshot captured.

Append-only, except for deliberate repair.

## `data/thumbnails.csv`

The canonical creative registry, one row per creative:

```csv
thumbnail_key,roblox_asset_id,filename,description,prompt,source_thumbnail_id,generated_at,activated_at,deactivated_at,status
```

## `data/state.json`

```json
{
  "next_thumbnail_sequence": 26,
  "next_candidate_sequence": 43,
  "last_successful_run": "2026-09-12T01:14:51Z",
  "pending_upload": null
}
```

No secrets belong here.

---

# GitHub Pages Dashboard

Published from `docs/` on the default branch. The dashboard is static
HTML/CSS/JavaScript reading `docs/data/`.

**Thumbnail images are not committed.** Each run resolves every tracked creative
to a Roblox CDN URL and publishes the map as `docs/data/images.json`, which the
cards and chart tooltips read. Those URLs are 180-day tokens refreshed every
run, so the dashboard is self-healing while the workflow runs — but if runs stop
for six months the images go dead. `keep_local_images` still saves a copy under
`docs/images/thumbnails/`, gitignored, which is then the only backup.

The page shows:

- **A generated-at timestamp** with its age, flagged in red once the data is
  older than 8 hours — runs are scheduled every 6, so that means a stalled
  workflow.
- **Overview**: active count, queue size, best current qPTR, and the evaluation
  status, which names the thumbnails holding the gate shut.
- **Active thumbnail cards**: image, description, ids, impressions, qualified
  plays, qPTR, 7-day qPTR, average playtime, winning segments, activation date,
  lineage, and the prompt that produced it.
- **Queue**: pending candidates with their prompt and lineage. No image — a
  candidate has not been uploaded to Roblox yet, so no CDN URL exists for it.
- **Leaderboard**: the active set ranked by qPTR.
- **Charts**: qPTR, impressions and qualified plays over time, on a real time
  axis so points sit under the date they were recorded. Blank cells are gaps,
  not zeros. Each series is bounded to its creative's serving lifespan, so a
  retired thumbnail's line ends when it stopped serving. Hovering a trace
  previews that thumbnail's image.
- **Full creative history**: every creative ever tracked, each with a "Show in
  charts" checkbox that adds it to the graphs. The selection is remembered per
  browser.
- **Generation lineage**: the ancestry tree built from `source_thumbnail_id`.

---

# GitHub Actions

`.github/workflows/thumbnail-manager.yml` runs on a `17 */6 * * *` schedule
(00:17, 06:17, 12:17, 18:17 UTC) and on `workflow_dispatch`. Minute 17 avoids
the top-of-hour crush. Concurrency is limited to one run at a time, without
cancelling in progress, so two jobs cannot edit the CSVs or the active
configuration simultaneously.

The commit step stages `data` and `docs` only.

---

# Secrets and Configuration

Repository secrets:

```text
ROBLOX_API_KEY        Open Cloud key, restricted to the target universe
ROBLOX_UNIVERSE_ID    the experience's universe id
AI_IMAGE_API_KEY      Gemini API key, used for images and descriptions
NOTIFY_EMAIL          where candidate notifications are sent
SMTP_USER             sending account
SMTP_PASSWORD         app password for that account
```

Optional repository *variables* `SMTP_HOST` and `SMTP_PORT` override the Gmail
defaults. An unset variable arrives as an empty string, which the config treats
as absent.

Email notification is skipped when SMTP credentials are missing, and never fails
a run. One message is sent per run, carrying every candidate it generated with
each image attached alongside its model, lineage, description and prompt.

## Roblox Open Cloud access

Create an Open Cloud API key restricted to the target universe, with both:

```text
universe.analytics:read
universe.thumbnail:write
```

Each API system needs the experience attached to it individually — granting it
under one does not carry to the other. Accepted IPs must include `0.0.0.0/0`,
since Actions runners have no fixed address. Do not use account cookies.

Note that saving permission changes may regenerate the key string, in which case
the stored secret must be updated too.

## `config.json`

```json
{
  "minimum_impressions": 1000,
  "qptr_deactivation_gap_percentage_points": 0.2,
  "target_active_thumbnails": 5,
  "queue_order": "fifo",
  "source_thumbnail_selection": "weighted_random",
  "allow_thumbnail_deactivation": true,
  "allow_thumbnail_uploads": true,
  "allow_ai_generation": true,
  "image_provider": "gemini",
  "image_model": "gemini-3-pro-image",
  "allow_ai_descriptions": true,
  "description_model": "gemini-3.6-flash",
  "generation_retries": 3,
  "keep_local_images": true
}
```

The three `allow_*` flags gate every outward-facing action independently, which
is what makes staged rollout possible.

---

# Failure Safety

Automation that changes public thumbnails fails conservatively.

**Analytics unavailable** — no ranking, no deactivation, no
performance-based decision. The active set is preserved and the error logged.

**Missing metrics for an active thumbnail** — the gate is treated as closed. A
thumbnail with no analytics rows is never assumed to be at zero.

**Upload failure** — the active set is left alone, the candidate stays queued,
and the attempt is retried on a later run. An operation already accepted by
Roblox is resumed rather than repeated.

**Moderation pending** — the candidate is not removed from the queue until
Roblox confirms the thumbnail is usable and activation succeeds.

**AI generation failure** — generation is queue maintenance, not a prerequisite
for analytics. Metrics, history and the dashboard still complete.

**Notification or image-lookup failure** — logged and ignored; neither is worth
failing a run over.

---

# Testing

```bash
.venv/bin/python -m pytest tests -q
```

The suite covers the selection rules in both isolation and combination, the
analytics merge semantics (summed counts, derived rates, the impression floor,
the window including today), queue sizing and lifecycle, image format detection,
the upload handshake, email batching, and dashboard data.

Cases worth keeping as the system evolves:

```text
a thumbnail exactly at the cutoff                  -> keep
bottom-N retires close performers                  -> retire
bottom-N never empties a small active set          -> no change
an active thumbnail with no analytics              -> gate closed
a noisy final bucket                               -> cannot inflate the rate
counts summed, not taken from the newest bucket    -> window totals
a JPEG named .png                                  -> uploaded as image/jpeg
uploads use the plural `files` field               -> registered
generation never writes to the real queue          -> no stub images escape
```

---

# Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env`:

```dotenv
ROBLOX_API_KEY=your-development-key
ROBLOX_UNIVERSE_ID=1234567890
AI_IMAGE_API_KEY=your-gemini-key
```

Run:

```bash
python -m src.main
```

A local run writes to the working tree rather than committing; `git checkout
data docs` resets whatever it produced. The Action always uses the config
committed to the default branch, so config changes must be pushed before a
scheduled run picks them up.

To preview the dashboard:

```bash
python -m http.server 8000 -d docs
```

## Generating images by hand

`scripts/generate.py` runs the same generation pipeline as a scheduled run -
prompt building, model resolution, retries, moderation - but writes to
`generated/` by default, so nothing reaches the game.

```bash
scripts/generate.py --list-sources              # creatives usable as a seed
scripts/generate.py --list-models               # image models your key can use
scripts/generate.py --source thumb-001 --count 3
scripts/generate.py --describe "A stone lighthouse at dusk"
scripts/generate.py --prompt "..." --model gemini-3.1-flash-image
scripts/generate.py --source thumb-001 --dry-run   # print the prompt only
```

`--queue` writes into `thumbnails/queue/` instead, which means the next run
uploads and activates the image on the live game. Everything else is local:
`generated/` is gitignored and never read by a run.

---

# Staged Rollout

The `allow_*` flags exist so the system can be brought up in stages.

**Stage 1 — read only.** Query Roblox, write history, publish the dashboard. All
three flags `false`.

**Stage 2 — generation.** Enable `allow_ai_generation`. Candidates accumulate in
the queue and can be reviewed before anything reaches the game.

**Stage 3 — full automation.** Enable `allow_thumbnail_deactivation` and
`allow_thumbnail_uploads`. Deactivation and activation now change live
thumbnails.

Verify the read-only path first: that the run identifies exactly the right
active thumbnails, and that its numbers match the Creator Dashboard.

---

# Design Principle

```text
ACTIVE THUMBNAILS -> measure -> retire the weaker
        ^                            |
        |                            v
    test descendants  <-  generate variations
```

The CSV history and the generation lineage make it possible to ask not only
which image won, but which visual concepts repeatedly produce successful
descendants.

One caveat on that ambition: how much the system explores depends entirely on
the prompt. A prompt that asks for a faithful rendering of the source
description produces near-duplicates of the current leader, which tells you
little in an A/B test. A prompt that asks for a visually distinct variation
explores more but drifts further from what is already working.

---

# Documentation

Roblox:

- Open Cloud — https://create.roblox.com/docs/cloud
- API domains — https://create.roblox.com/docs/cloud/reference/domains/apis
- Scopes — https://create.roblox.com/docs/cloud/reference/scopes
- Analytics metrics — https://create.roblox.com/docs/cloud/guides/analytics/metrics
- Home Page thumbnails — https://create.roblox.com/docs/production/publishing/thumbnails

GitHub:

- Workflow syntax — https://docs.github.com/actions/reference/workflows-and-actions/workflow-syntax
- Scheduled workflows — https://docs.github.com/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Pages — https://docs.github.com/pages
