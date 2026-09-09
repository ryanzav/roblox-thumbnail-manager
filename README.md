# Roblox Thumbnail Manager

An automated Roblox Home Page thumbnail testing system.

The repository uses **GitHub Actions** to query Roblox thumbnail analytics every 6 hours, stores a permanent CSV history of thumbnail performance, publishes a static dashboard with **GitHub Pages**, removes clearly underperforming active thumbnails, and fills open active-thumbnail slots from a local queue of AI-generated thumbnail images.

The system is designed around Roblox's Home Page thumbnail personalization APIs and Analytics Query API.

---

## System Behavior

Every 6 hours, the GitHub Action performs the following sequence:

```text
Query current Roblox active thumbnails
                ↓
Query performance metrics for every tracked thumbnail
                ↓
Append a snapshot to CSV history
                ↓
Update thumbnail metadata/status
                ↓
Do all active thumbnails have >= 1,000 impressions?
        │
        ├── NO → Do not rank or deactivate thumbnails
        │        Update dashboard and exit evaluation
        │
        └── YES
                ↓
Rank active thumbnails by Qualified Play Through Rate
                ↓
Find highest active qPTR
                ↓
Deactivate every active thumbnail whose qPTR is
more than 0.5 percentage points below the best
                ↓
Fill active slots from local thumbnail queue
until either:
    • 5 thumbnails are active, or
    • no queued thumbnails remain
                ↓
Move activated images out of the queue
                ↓
Generate new AI thumbnail candidates to replenish queue
                ↓
Rebuild GitHub Pages dashboard data
                ↓
Commit CSV / metadata / dashboard changes
```

The script runs every 6 hours whether or not a thumbnail change occurs.

---

# Selection Algorithm

## 1. Impression Gate

No active thumbnails are ranked or removed until **every currently active thumbnail has at least 1,000 impressions**.

Example:

```text
Thumbnail A    8,400 impressions
Thumbnail B    7,200 impressions
Thumbnail C      923 impressions
Thumbnail D    6,100 impressions
```

Because Thumbnail C has fewer than 1,000 impressions:

```text
NO THUMBNAILS ARE DEACTIVATED
```

The script still records metrics and updates the dashboard.

This protects newly activated thumbnails from being judged before they have accumulated a minimum amount of traffic.

After a new thumbnail is activated, it normally begins below 1,000 impressions, so the gate automatically pauses further ranking until that new thumbnail reaches the threshold.

---

## 2. Rank by Qualified Play Through Rate

Once every active thumbnail has at least 1,000 impressions, rank the active thumbnails by:

```text
ThumbnailQualifiedPTR
```

Roblox displays this as **Qualified Play Through Rate**.

Example:

```text
Thumbnail A    8.4%
Thumbnail B    8.1%
Thumbnail C    7.8%
Thumbnail D    7.2%
Thumbnail E    8.3%
```

The best active thumbnail is:

```text
8.4%
```

---

## 3. Deactivation Threshold

The cutoff is:

```text
best Qualified Play Through Rate - 0.5 percentage points
```

For a best qPTR of:

```text
8.4%
```

the cutoff is:

```text
7.9%
```

Therefore:

```text
Thumbnail A    8.4%    KEEP
Thumbnail E    8.3%    KEEP
Thumbnail B    8.1%    KEEP
Thumbnail C    7.8%    DEACTIVATE
Thumbnail D    7.2%    DEACTIVATE
```

### Important unit convention

The `0.5` threshold means **0.5 percentage points**, not 50%.

If the Roblox API returns qPTR as a decimal:

```text
8.4% = 0.084
```

then the code should calculate:

```python
cutoff = best_qptr - 0.005
```

A thumbnail is deactivated when:

```python
thumbnail.qptr < cutoff
```

A thumbnail exactly at the cutoff remains active.

---

## 4. Refill Active Thumbnail Slots

After weak thumbnails are deactivated, the script fills available slots using images from the local thumbnail queue.

Roblox allows at most 5 thumbnails to be active at the same time, so the target is:

```text
5 active thumbnails
```

Example:

```text
Before evaluation:
5 active

After deactivation:
3 active

Queue:
candidate-014.png
candidate-015.png
candidate-016.png
```

The script uploads and activates:

```text
candidate-014.png
candidate-015.png
```

The result is:

```text
5 active thumbnails
```

If the queue contains only one image:

```text
4 active thumbnails
```

The script stops when either:

```text
active_count == 5
```

or:

```text
queue is empty
```

---

# AI Thumbnail Queue

New candidate images are generated with AI and stored locally in the repository until they are needed.

The queue lives in:

```text
thumbnails/queue/
```

Example:

```text
thumbnails/queue/
├── butterfly-closeup-001.png
├── butterfly-flight-002.png
├── flower-field-003.png
└── rainbow-flight-004.png
```

Each queued image also has metadata describing:

- generation timestamp
- AI prompt
- source active thumbnail
- source thumbnail description
- generation provider/model
- local filename
- queue status

---

## Generating New Thumbnail Ideas

Each generated image is based on the description of **one currently active thumbnail**.

For example, suppose an active thumbnail has this description:

```text
A colorful butterfly flying above green Roblox-style hills with
flowers, a rainbow in the background, and a bright blue sky.
```

The prompt builder may use that description as a creative seed:

```text
Create a new Roblox game thumbnail inspired by this existing
thumbnail concept:

"A colorful butterfly flying above green Roblox-style hills with
flowers, a rainbow in the background, and a bright blue sky."

Create a visually distinct variation rather than a duplicate.
Preserve the game's visual identity while changing composition,
camera angle, subject emphasis, background arrangement, or
supporting elements. Make it attractive at Roblox thumbnail size.
16:9 composition. No text unless specifically requested.
```

The exact prompt-generation strategy should live in code rather than being hardcoded into the GitHub workflow.

---

## Choosing the Source Thumbnail

When generating a candidate, the system selects one of the **top-performing**
active thumbnails that has a usable description.

Only the best active thumbnail and those within **0.5 percentage points** of it
are eligible as sources — the same cutoff the deactivation rule uses. New
creatives are therefore only ever bred from thumbnails good enough to keep:

```text
Thumbnail A    8.4%    SOURCE  (best)
Thumbnail E    8.3%    SOURCE
Thumbnail B    8.1%    SOURCE
Thumbnail C    7.8%    not eligible
Thumbnail D    7.2%    not eligible
```

A source must also clear the same **1,000-impression gate**. Below that its
qPTR is not trustworthy enough to call it a winner, so it cannot seed
candidates; a thumbnail with no metrics never qualifies either.

The best qPTR is measured among qualifying thumbnails only, so a thin-data
outlier cannot raise the bar and starve the pool:

```text
Thumbnail X    20.0%    120 impressions   ignored (below gate)
Thumbnail A     8.4%  9,000 impressions   SOURCE (best)
Thumbnail B     8.0%  9,000 impressions   SOURCE
```

Note the difference in scope from deactivation. Deactivation waits for *every*
active thumbnail to reach 1,000 impressions before ranking anything. Source
eligibility is per-thumbnail: proven winners keep breeding even while a newly
activated thumbnail is still accumulating traffic.

If no active thumbnail clears the gate with trustworthy metrics, generation is
skipped for that run rather than seeding from unproven creatives.

The generated candidate records the source thumbnail ID:

```text
source_thumbnail_id
```

This makes it possible to later answer questions such as:

```text
Which winning thumbnails produced the best descendants?
```

or:

```text
Do variations of Thumbnail A consistently outperform
variations of Thumbnail B?
```

The source-thumbnail selection strategy can later become more sophisticated.

For the initial implementation it can be:

```text
random active thumbnail
```

or:

```text
random active thumbnail weighted toward higher qPTR
```

The selection policy should be configurable.

---

## Thumbnail Descriptions

Every tracked thumbnail should have a description in:

```text
data/thumbnails.csv
```

For existing Roblox thumbnails, descriptions can initially be entered manually.

For AI-generated thumbnails, the description can be stored at generation time.

Example metadata:

```csv
thumbnail_key,roblox_asset_id,filename,description,source_thumbnail_id,prompt,status
thumb-001,123456789,thumb-001.png,"Large blue butterfly over rolling hills...",,,"active"
thumb-002,987654321,thumb-002.png,"Orange butterfly flying through flowers...",thumb-001,"Create a variation...","active"
```

The dashboard should expose the description and generation lineage for each thumbnail.

---

# Queue Lifecycle

A generated image moves through these states:

```text
GENERATED
    ↓
QUEUED
    ↓
UPLOADING
    ↓
ROBLOX PROCESSING / MODERATION
    ↓
ACTIVATED
    ↓
TRACKED
    ↓
ACTIVE or INACTIVE
```

When a queued image is successfully activated:

1. Remove it from `thumbnails/queue/`.
2. Move the image into a permanent tracked-image directory.
3. Record its Roblox thumbnail/asset identifier.
4. Record its activation timestamp.
5. Mark its status as `active`.
6. Keep its image, prompt, description, source thumbnail, and future performance history.

Recommended destination:

```text
docs/images/thumbnails/
```

This removes the file from the queue while preserving it so GitHub Pages can display the actual thumbnail alongside its historical performance.

Never delete the only local copy of a thumbnail simply because it was removed from the queue.

---

# Queue Replenishment

After the thumbnail-management portion of each run, the script checks the queue.

Generation is **demand-driven**: a candidate is only generated when there is an
open active slot for it. The script generates enough images to fill the open
slots, counting candidates already waiting in the queue:

```text
generate = (target_active_thumbnails - active count) - queued count
```

Examples:

```text
5 active, 0 queued   ->  generate 0   (no slot to fill)
4 active, 0 queued   ->  generate 1
3 active, 1 queued   ->  generate 1
3 active, 2 queued   ->  generate 0   (already covered)
```

This keeps AI image generation cost proportional to actual need and keeps
candidates fresh, since each one is bred from whichever thumbnails are winning
at the time it is generated rather than sitting in a buffer while the leaders
change.

Note the ordering consequence: queued candidates are activated earlier in the
same run, before replenishment. When an evaluation deactivates several
thumbnails at once, the queue may not cover every slot immediately, so the
newly opened slots are filled over the following runs rather than all at once.

Generation should not block metric collection. If AI image generation fails, the metrics/history/dashboard portion of the scheduled run should still succeed whenever possible.

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
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── roblox_api.py
│   ├── analytics.py
│   ├── selector.py
│   ├── queue.py
│   ├── prompt_builder.py
│   ├── image_generator.py
│   ├── history.py
│   └── dashboard.py
│
├── data/
│   ├── metrics.csv
│   ├── thumbnails.csv
│   └── state.json
│
├── thumbnails/
│   └── queue/
│       ├── candidate-001.png
│       ├── candidate-002.png
│       └── ...
│
├── docs/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   ├── data/
│   │   ├── metrics.csv
│   │   └── thumbnails.csv
│   └── images/
│       └── thumbnails/
│           ├── thumb-001.png
│           ├── thumb-002.png
│           └── ...
│
├── tests/
│   ├── test_selector.py
│   ├── test_history.py
│   ├── test_queue.py
│   └── test_dashboard.py
│
└── .github/
    └── workflows/
        └── thumbnail-manager.yml
```

---

# Module Responsibilities

## `src/main.py`

Coordinates one complete scheduled run.

Suggested order:

```text
load config
load secrets
lock / prevent overlapping run
fetch Roblox thumbnail state
query metrics
write metrics history
refresh metadata
evaluate active thumbnails if eligible
deactivate weak thumbnails
activate queued replacements
replenish AI image queue
build dashboard data
commit generated state
```

---

## `src/roblox_api.py`

Contains all Roblox-specific HTTP operations.

Responsibilities:

- authentication headers
- list Home Page thumbnails
- retrieve personalization configuration
- update active thumbnails
- upload candidate images
- poll upload processing status
- query upload failures
- retry transient API errors
- avoid leaking credentials into logs

Keep API details isolated here because Roblox currently marks the thumbnail-personalization API as Experimental.

---

## `src/analytics.py`

Queries Roblox Analytics and normalizes results.

Primary metrics:

```text
ThumbnailImpressions
ThumbnailQualifiedPTR
ThumbnailQualifiedPlays
ThumbnailAverageSessionLengthMinutes
ThumbnailL7QualifiedPTR
ThumbnailWinningSegments
```

Individual thumbnails should be queried using the:

```text
ThumbnailAsset
```

dimension.

The **selection algorithm uses `ThumbnailQualifiedPTR`**.

Other metrics are stored for analysis and dashboard display but do not affect the initial automated removal rule.

---

## `src/selector.py`

Implements the exact automated decision policy.

Pseudo-code:

```python
def choose_changes(active_thumbnails):
    if not active_thumbnails:
        return no_changes()

    if any(t.impressions < 1000 for t in active_thumbnails):
        return no_changes(reason="waiting for 1000 impressions")

    best_qptr = max(t.qualified_ptr for t in active_thumbnails)
    cutoff = best_qptr - 0.005

    deactivate = [
        t for t in active_thumbnails
        if t.qualified_ptr < cutoff
    ]

    return deactivate
```

The selector does **not** decide which local image file to upload. That belongs to the queue module.

---

## `src/queue.py`

Manages:

```text
thumbnails/queue/
```

Responsibilities:

- list available candidates
- choose the next candidate
- attach candidate metadata
- mark candidate as being uploaded
- remove/move candidate after successful activation
- avoid activating the same candidate twice
- detect missing/corrupt queue files

The queue ordering can initially be FIFO:

```text
oldest generated image first
```

This makes the behavior deterministic.

---

## `src/prompt_builder.py`

Builds AI generation prompts.

Inputs:

```text
source thumbnail description
source thumbnail performance metadata
game-level prompt instructions
generation history
```

Outputs:

```text
generation prompt
```

The builder should encourage meaningful variation rather than generating near-identical copies.

---

## `src/image_generator.py`

Provides an abstraction around the selected AI image-generation API.

Responsibilities:

- send generated prompt
- request a 16:9 image suitable for a Roblox thumbnail
- save the result into `thumbnails/queue/`
- create metadata
- return generated filename
- handle generation failures safely

The image-generation provider should be configurable instead of spreading provider-specific code throughout the project.

---

## `src/history.py`

Maintains:

```text
data/metrics.csv
data/thumbnails.csv
data/state.json
```

It should make writes atomic whenever possible to avoid corrupting history if a scheduled run fails.

---

## `src/dashboard.py`

Prepares the data consumed by the GitHub Pages site.

It can:

- copy/update CSV files under `docs/data/`
- calculate current leaderboard information
- calculate lifetime summary statistics
- produce a small `latest.json` if useful
- ensure image references resolve correctly

The dashboard itself remains static HTML/CSS/JavaScript.

---

# Performance History

## `data/metrics.csv`

Append one row per thumbnail per scheduled analytics snapshot.

Recommended schema:

```csv
timestamp,thumbnail_key,roblox_asset_id,status,impressions,qualified_plays,qualified_ptr,l7_qualified_ptr,average_session_minutes,winning_segments
2026-09-08T00:17:00Z,thumb-001,123456789,active,8421,707,0.08396,0.08250,14.7,12
2026-09-08T00:17:00Z,thumb-002,987654321,active,7340,571,0.07779,0.07810,13.9,5
```

The file is append-only except for deliberate repair/migration.

This gives the project a permanent history even after Roblox's current active set changes.

---

## `data/thumbnails.csv`

One row per unique creative.

Recommended schema:

```csv
thumbnail_key,roblox_asset_id,filename,description,prompt,source_thumbnail_id,generated_at,activated_at,deactivated_at,status
```

Example:

```csv
thumb-001,123456789,thumb-001.png,"Blue butterfly above green hills","",,2026-09-01T12:00:00Z,2026-09-01T13:00:00Z,,active
thumb-002,987654321,thumb-002.png,"Butterfly close-up with flowers","Create a variation...",thumb-001,2026-09-03T18:00:00Z,2026-09-04T00:00:00Z,2026-09-08T00:17:00Z,inactive
```

This is the canonical creative registry.

---

## `data/state.json`

Stores small pieces of workflow state that should not be reconstructed from CSV on every run.

Example:

```json
{
  "last_successful_run": "2026-09-08T00:17:00Z",
  "last_personalization_change": "2026-09-08T00:17:00Z",
  "next_thumbnail_sequence": 27
}
```

Do not store secrets here.

---

# GitHub Pages Dashboard

The repository publishes a static site from:

```text
docs/
```

The dashboard reads:

```text
docs/data/metrics.csv
docs/data/thumbnails.csv
```

and thumbnail images from:

```text
docs/images/thumbnails/
```

No backend server is required.

---

## Dashboard Overview

The top of the dashboard should show:

```text
Roblox Thumbnail Performance

Last analytics update
Current active thumbnail count
Queue size
Best current qPTR
Next evaluation status
```

Example:

```text
Last update:          Sep 8, 2026 8:17 PM
Active thumbnails:   5 / 5
Queue:                8 candidates
Best current qPTR:    8.4%
Evaluation:           Waiting for Thumbnail 27 to reach 1,000 impressions
```

---

## Active Thumbnail Cards

Each active thumbnail should display:

- image
- description
- Roblox thumbnail ID
- impressions
- qualified plays
- Qualified Play Through Rate
- 7-day Qualified Play Through Rate
- average playtime
- winning segments
- activation date
- source thumbnail lineage if AI generated

Example:

```text
┌──────────────────────────────────────────┐
│ [thumbnail image]                        │
│                                          │
│ Butterfly over green hills               │
│                                          │
│ ACTIVE                                   │
│ Impressions                 8,421         │
│ Qualified Plays               707         │
│ Qualified PTR                8.40%        │
│ 7-day qPTR                   8.25%        │
│ Average Playtime             14.7 min     │
│                                          │
│ Source: thumb-003                         │
└──────────────────────────────────────────┘
```

---

## Leaderboard

Show current active thumbnails ranked by qPTR:

```text
Rank  Thumbnail   Impressions   Qualified PTR
1     thumb-014       8,421          8.40%
2     thumb-009       9,106          8.31%
3     thumb-021       1,821          8.05%
4     thumb-017       6,012          7.94%
5     thumb-022         642          7.81%
```

If one or more active thumbnails have fewer than 1,000 impressions, display:

```text
Evaluation paused:
All active thumbnails must reach 1,000 impressions.
```

Do not show a removal recommendation as final while the gate is closed.

---

## Performance Charts

The dashboard should chart:

### Qualified Play Through Rate over time

```text
qPTR
 │
 │    thumb-014 ─────────╮
 │        thumb-009 ─────┼────
 │                       ╰────
 │  thumb-017 ───────────────
 └────────────────────────────── time
```

### Impressions over time

This helps show how Roblox personalization distributes traffic.

### Qualified Plays over time

This makes it easier to compare raw outcome volume with rates.

---

## Full Creative History

Inactive thumbnails remain visible in the dashboard.

For every creative, retain:

- image
- description
- AI prompt
- source thumbnail
- generated date
- activation date
- deactivation date
- lifetime impressions
- best qPTR
- most recent qPTR
- qualified plays
- average playtime
- active/inactive status

This prevents performance data from disappearing when a thumbnail is retired.

---

## Generation Lineage

Because each AI candidate records the active thumbnail used as its source, the dashboard can display creative ancestry.

Example:

```text
thumb-003
   ├── thumb-009
   │      ├── thumb-017
   │      └── thumb-021
   └── thumb-014
          └── thumb-025
```

Over time this can help identify which creative concepts repeatedly produce successful variants.

---

# GitHub Actions

Create:

```text
.github/workflows/thumbnail-manager.yml
```

Recommended workflow:

```yaml
name: Roblox Thumbnail Manager

on:
  schedule:
    # GitHub scheduled workflows use UTC.
    # Run every 6 hours, away from the top of the hour.
    - cron: "17 */6 * * *"

  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: roblox-thumbnail-manager
  cancel-in-progress: false

jobs:
  manage-thumbnails:
    runs-on: ubuntu-latest

    steps:
      - name: Check out repository
        uses: actions/checkout@v6

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run thumbnail manager
        env:
          ROBLOX_API_KEY: ${{ secrets.ROBLOX_API_KEY }}
          ROBLOX_UNIVERSE_ID: ${{ secrets.ROBLOX_UNIVERSE_ID }}
          AI_IMAGE_API_KEY: ${{ secrets.AI_IMAGE_API_KEY }}
        run: python -m src.main

      - name: Commit updated history, dashboard, and queue
        run: |
          git config user.name "roblox-thumbnail-bot"
          git config user.email "roblox-thumbnail-bot@users.noreply.github.com"

          git add data thumbnails/queue docs

          if git diff --cached --quiet; then
            echo "No repository changes to commit."
            exit 0
          fi

          git commit -m "Update thumbnail metrics and queue"
          git push
```

This runs at:

```text
00:17 UTC
06:17 UTC
12:17 UTC
18:17 UTC
```

every day.

Using minute `17` avoids scheduling exactly at the top of the hour, when scheduled GitHub Actions runs can experience heavier load.

---

# GitHub Pages Setup

The simplest configuration is to publish directly from the `docs/` directory on the default branch.

In GitHub:

```text
Repository
→ Settings
→ Pages
→ Build and deployment
→ Deploy from a branch
→ Branch: main
→ Folder: /docs
```

The scheduled job updates the dashboard files automatically.

The flow becomes:

```text
GitHub Action
      ↓
data/*.csv updated
      ↓
docs/data/*.csv updated
      ↓
dashboard assets updated
      ↓
commit + push
      ↓
GitHub Pages automatically republishes
```

No separate web server is required.

If the repository or dashboard must remain private, verify that the GitHub account/organization plan supports the desired Pages visibility before relying on Pages for private metrics.

---

# Roblox Open Cloud Access

Create a Roblox Open Cloud API key that is restricted to the target experience/universe.

Required scopes:

```text
universe.analytics:read
universe.thumbnail:write
```

`universe.analytics:read` is used for analytics retrieval.

`universe.thumbnail:write` is used to upload thumbnails and manage Home Page thumbnail personalization.

Do not use Roblox account cookies for this project.

---

## Relevant Roblox Endpoints

Base URL:

```text
https://apis.roblox.com
```

Get personalization configuration:

```http
GET /thumbnail-personalization-api/v1/universes/{universeId}/personalization
```

Create a new active personalization configuration:

```http
POST /thumbnail-personalization-api/v1/universes/{universeId}/personalization/create
```

Update the currently active personalization configuration:

```http
POST /thumbnail-personalization-api/v1/universes/{universeId}/personalization/update
```

List Home Page thumbnails:

```http
GET /thumbnail-personalization-api/v1/universes/{universeId}/thumbnails
```

This returns **every uploaded homepage thumbnail**, not just the active
rotation — often more than 5 entries. Roblox only serves up to 5 at a
time: an entry is in the current rotation only when its
`personalizedConfigStatus` is `Active`. Entries with
`personalizedConfigStatus: Inactive` are uploaded and approved but not
currently shown, and must not be treated as active by the selection
algorithm.

Upload Home Page thumbnails:

```http
POST /thumbnail-personalization-api/v1/universes/{universeId}/thumbnails/uploads
```

Check upload processing status:

```http
GET /thumbnail-personalization-api/v1/universes/{universeId}/thumbnails/uploads/status
```

Query analytics:

```http
POST /analytics-query-api/v1/universes/{universeId}/metrics
```

Roblox currently documents the thumbnail-personalization APIs as Experimental, so keep all endpoint-specific logic isolated in `roblox_api.py`.

---

# Secrets

Create GitHub Actions secrets under:

```text
Repository
→ Settings
→ Secrets and variables
→ Actions
```

Required:

```text
ROBLOX_API_KEY
ROBLOX_UNIVERSE_ID
AI_IMAGE_API_KEY
```

Depending on the AI provider, additional configuration may be stored as repository variables rather than secrets.

Never commit:

- Roblox API keys
- AI API keys
- Roblox account cookies
- private authentication headers

---

# Example `config.json`

```json
{
  "minimum_impressions": 1000,
  "qptr_deactivation_gap_percentage_points": 0.5,
  "target_active_thumbnails": 5,
  "queue_order": "fifo",
  "source_thumbnail_selection": "weighted_random",
  "allow_thumbnail_deactivation": true,
  "allow_thumbnail_uploads": true,
  "allow_ai_generation": true
}
```

The key automated rules are intentionally explicit:

```text
minimum_impressions = 1000
qPTR gap = 0.5 percentage points
target active = 5
```

---

# Python Dependencies

A starting `requirements.txt` might include:

```text
requests>=2.32,<3
python-dotenv>=1.0,<2
pytest>=8,<9
```

Add the SDK required by the selected AI image-generation provider if one is used.

The project does not require Flask, Django, FastAPI, or an always-running web server.

---

# Failure Safety

Automation that changes public thumbnails should fail conservatively.

## Analytics failure

If analytics cannot be retrieved:

```text
DO NOT DEACTIVATE ANYTHING
DO NOT MAKE A PERFORMANCE-BASED DECISION
```

The run should log the error and preserve the current active set.

---

## Missing metrics

If one active thumbnail does not have a trustworthy impression/qPTR result:

```text
TREAT THE EVALUATION GATE AS CLOSED
```

Do not assume zero.

---

## Upload failure

If a candidate upload fails:

- leave existing active thumbnails alone
- leave the candidate in or return it to the queue
- record the error
- try again on a later run

---

## Roblox processing/moderation delay

Do not remove the candidate from the queue permanently until Roblox confirms the uploaded thumbnail is usable and the activation update succeeds.

A safe implementation can:

```text
queue file
    ↓
upload
    ↓
wait/poll for successful processing
    ↓
activate
    ↓
verify active configuration
    ↓
move file out of queue
```

---

## AI generation failure

AI generation is queue maintenance, not a prerequisite for analytics.

If generation fails:

```text
keep metrics/history
keep current active thumbnails
publish dashboard
record generation failure
```

---

## Prevent overlapping workflow runs

Use GitHub Actions concurrency:

```yaml
concurrency:
  group: roblox-thumbnail-manager
  cancel-in-progress: false
```

This avoids two jobs simultaneously editing CSV files or changing the active thumbnail configuration.

---

# Testing

The selection rules should be thoroughly unit tested because they can automatically change the experience's public thumbnails.

Essential tests:

```text
all active >= 1000 impressions
    → evaluation allowed

one active = 999 impressions
    → no deactivation

best = 8.4%, thumbnail = 7.91%
    → keep

best = 8.4%, thumbnail = 7.90%
    → keep

best = 8.4%, thumbnail = 7.89%
    → deactivate

two weak thumbnails removed
    + three candidates available
    → activate first two queue candidates

three open slots
    + one candidate available
    → activate one and stop at three active

candidate activation succeeds
    → remove candidate from queue and archive image

candidate upload fails
    → leave candidate queued

analytics failure
    → no thumbnail mutation

missing active thumbnail metrics
    → gate closed

AI generation failure
    → analytics history still written
```

---

# Local Development

Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a local `.env`:

```dotenv
ROBLOX_API_KEY=your-development-key
ROBLOX_UNIVERSE_ID=1234567890
AI_IMAGE_API_KEY=your-image-provider-key
```

Run:

```bash
python -m src.main
```

---

# `.gitignore`

At minimum:

```gitignore
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
.DS_Store
```

Do **not** ignore:

```text
data/
thumbnails/queue/
docs/
```

Those directories are intentionally persisted through Git.

---

# Initial Repository Setup

1. Create the GitHub repository.
2. Add the repository structure above.
3. Create a Roblox Open Cloud API key.
4. Restrict it to the correct universe.
5. Enable:
   - `universe.analytics:read`
   - `universe.thumbnail:write`
6. Add the Roblox credentials as GitHub Actions secrets.
7. Configure the AI image-generation provider.
8. Add the AI provider key as a GitHub Actions secret.
9. Populate `data/thumbnails.csv` with the currently active Roblox thumbnails.
10. Add a description for each existing active thumbnail.
11. Run the project manually with `workflow_dispatch`.
12. Confirm that the script can identify the exact active thumbnails.
13. Confirm that analytics values match Creator Dashboard.
14. Confirm that `data/metrics.csv` receives one row per tracked thumbnail.
15. Configure GitHub Pages to publish `/docs`.
16. Confirm the dashboard displays correctly.
17. Test queue uploads with mutation disabled or against a controlled test configuration.
18. Enable automatic deactivation/upload behavior only after the read-only path is verified.

---

# Recommended First Deployment

Before allowing the repository to make automatic changes, deploy it in three stages.

## Stage 1 — Metrics only

```text
query Roblox
write CSV
publish dashboard
```

No deactivation, upload, activation, or AI generation.

---

## Stage 2 — Queue + AI generation

```text
query Roblox
write CSV
publish dashboard
generate candidates
populate queue
```

Still no Roblox thumbnail mutations.

---

## Stage 3 — Full automation

Enable:

```text
1000-impression gate
0.5 percentage-point deactivation threshold
automatic deactivation
automatic queue upload
automatic activation
queue replenishment
```

---

# Example Full Run

Starting state:

```text
ACTIVE

A    8,900 impressions    8.4% qPTR
B    7,400 impressions    8.0% qPTR
C    5,800 impressions    7.6% qPTR
D    3,400 impressions    7.7% qPTR
E    1,200 impressions    8.2% qPTR
```

All active thumbnails have at least 1,000 impressions.

Best:

```text
A = 8.4%
```

Cutoff:

```text
8.4% - 0.5 percentage points = 7.9%
```

Actions:

```text
A    KEEP
B    KEEP
C    DEACTIVATE
D    DEACTIVATE
E    KEEP
```

Active count becomes:

```text
3
```

Queue contains:

```text
candidate-027.png
candidate-028.png
candidate-029.png
```

The script:

```text
uploads candidate-027
waits for successful processing
activates candidate-027
moves its local image out of queue

uploads candidate-028
waits for successful processing
activates candidate-028
moves its local image out of queue
```

Final active count:

```text
5
```

On the next 6-hour run, the two new thumbnails will probably have fewer than 1,000 impressions.

Therefore:

```text
metrics are collected
dashboard is updated
NO ranking/deactivation occurs
```

Once **all five** active thumbnails reach at least 1,000 impressions, another evaluation becomes eligible.

---

# Design Principle

The system is intentionally evolutionary:

```text
ACTIVE THUMBNAILS
        ↓
measure
        ↓
remove clearly weaker creatives
        ↓
generate descendants / variations
        ↓
test new creatives
        ↓
retain performance history
        ↓
repeat
```

The CSV history and generation lineage make it possible to analyze not just which individual image won, but which visual concepts repeatedly produce successful thumbnail descendants.

---

# Documentation

Roblox:

- Open Cloud  
  https://create.roblox.com/docs/cloud

- Open Cloud API domains  
  https://create.roblox.com/docs/cloud/reference/domains/apis

- Open Cloud scopes  
  https://create.roblox.com/docs/cloud/reference/scopes

- Supported analytics metrics  
  https://create.roblox.com/docs/cloud/guides/analytics/metrics

- Home Page thumbnails and personalization  
  https://create.roblox.com/docs/production/publishing/thumbnails

GitHub:

- GitHub Actions workflow syntax  
  https://docs.github.com/actions/reference/workflows-and-actions/workflow-syntax

- Scheduled workflows  
  https://docs.github.com/actions/reference/workflows-and-actions/events-that-trigger-workflows

- GitHub Pages  
  https://docs.github.com/pages

---

# License

A license is optional for a private personal automation repository.

If the project is later shared publicly, choose an appropriate open-source license.
