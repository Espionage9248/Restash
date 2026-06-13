# Restash

A freshness-scoring plugin for [Stash](https://github.com/stashapp/stash). Restash reads
the behavioural log Stash already keeps for every Scene and Performer — plays, o-history
(with timestamps), how completely each scene was watched, when it entered the library —
and turns it into a personalised **0–100 "freshness" score**. The score answers *"what do
I want to see right now?"* and changes over time.

The score is written **only** into each entity's `custom_fields` (keys prefixed
`restash_`). The native `rating100` star rating is **never touched**.

> **Status:** 0.2.3. The scoring engine, the write path (`Recompute All`,
> `Clear Restash Data`), and `Quick Refresh` (a fast daily re-score from a cached taste
> model) are complete and validated end-to-end against a real ~5,900-scene library. The
> optional `rating100` mirror remains a separate future feature.

---

## What it does

Stash passively records a rich behavioural log but nobody hand-curates ratings at library
scale — yet the watch history *is* the rating, it just needs decoding. Restash builds the
score from four ideas:

1. **Taste, learned not declared.** It builds affinity weights for your tags, performers,
   and studios from time-decayed o-history and play-completion. A scene scores well if its
   *ingredients* score well — even if you've never played it.
2. **Freshness: cooldown then rediscovery.** Something you just watched is buried; a
   long-unwatched favourite slowly climbs back above baseline. The curve dips right after a
   watch, recovers over a few weeks, and peaks months later.
3. **Satiation.** If the last week's activity is dominated by one tag or performer, that
   whole category is temporarily damped so the feed steers toward variety instead of
   feeding a binge back to you.
4. **Controlled serendipity.** A deterministic daily jitter reshuffles near-ties so the top
   of the grid looks different each day, plus a small "wildcard" slot that surfaces
   low-confidence items to keep the model learning.

Final scores are **percentile-ranked** across the library and mapped to 0–100, so the full
range is always used and a descending sort produces a smooth feed rather than a wall of
50s.

### What gets written

Restash partial-merges four keys into each in-scope entity's `custom_fields` (your other
custom fields are preserved):

| Key | Type | Meaning |
|---|---|---|
| `restash_score` | int 1–100 | the headline percentile-ranked score |
| `restash_raw` | float | the pre-percentile raw score (for debugging/tuning) |
| `restash_components` | JSON string | itemised terms (base, fresh, novelty, jitter, …) |
| `restash_updated` | UTC ISO-8601 | when this entity was last scored |

`restash_score` is floored at 1, so an API consumer can treat absent/0 as "not scored".

---

## Requirements

- **Stash** with scene + performer `custom_fields` support. Performer custom fields landed
  in v0.28; scene custom fields and `CustomFieldsInput.remove` are in recent stable
  (v0.30+). Restash probes the schema on startup and fails with a clear message if your
  build is too old. Developed and validated against **Stash v0.31.1**.
- **Python 3.11+** available to the Stash host (this is what runs the plugin).
- **[`stashapp-tools`](https://pypi.org/project/stashapp-tools/)** (`stashapi`) ≥ 0.2.58,
  installed for that same Python.

---

## Install

### Via plugin source (recommended)

Add Restash as a Stash plugin source and install it from the UI — no manual file copying,
and updates show up in-app:

1. **Settings → Plugins → Available Plugins → Add Source**, then enter:
   - **Name:** `Restash`
   - **Source URL:** `https://espionage9248.github.io/Restash/index.yml`
   - **Local Path:** `restash` (or any folder name you like)
2. Find **Restash** in the Available Plugins list and click **Install**.
3. Install the runtime dependency for the Python that Stash uses (the source ships the
   plugin code, not its Python deps — standard for Stash plugins):
   ```bash
   pip install stashapp-tools
   ```
4. **Settings → Plugins → Reload Plugins.** Restash and its tasks appear under
   **Settings → Tasks**.

When a new version is published, Stash shows an update on the source — no reinstall needed.

> **Switching from a manual install?** Restash keeps a local cache (`restash_state.json`)
> inside its plugin folder. Installing to a new folder won't carry that cache over — which
> is harmless, since your scores already live in Stash's `custom_fields`; the next run just
> does a one-time full recompute to rebuild the cache (Quick Refresh self-heals to a full
> run). To skip even that, copy `restash_state.json` from the old plugin folder into the new
> one after installing. Then remove the old manual copy so you don't run two Restash plugins.

### Manual install

1. Copy the **`restash/`** folder from this repo into your Stash plugins directory (e.g.
   `~/.stash/plugins/restash/`), so that `restash.yml` sits at
   `…/plugins/restash/restash.yml`.
2. Install the dependency for the Python that Stash uses:
   ```bash
   pip install stashapp-tools
   ```
3. In Stash, go to **Settings → Plugins** and click **Reload Plugins**. "Restash" should
   appear with its tasks under **Settings → Tasks**.

### Docker / Alpine notes

- Stash's official Docker image runs the plugin with `python`. Install the dependency
  inside the container for that interpreter, e.g. `docker exec <container> pip install
  stashapp-tools` (Alpine images may need `apk add py3-pip` first, and a build toolchain if
  a wheel isn't available).
- If your environment only exposes `python3` (not `python`), either install a `python`
  shim or change the `exec:` line in `restash.yml` from `python` to `python3`.
- On externally-managed Python installs you may see a PEP 668 "externally-managed
  -environment" error from `pip`; use the interpreter Stash actually invokes (a venv, or
  `pip install --user`/`--break-system-packages` as appropriate for your setup).

---

## Usage

Run tasks from **Settings → Tasks** in the Stash UI. Recommended first run: **Dry Run
Report**, eyeball the breakdown, then **Recompute All**.

| Task | Mode | What it does |
|---|---|---|
| **Dry Run Report** | `dry` | Reads + scores everything, **writes nothing**, logs the top-30 scenes and performers with every term itemised. Safe to run anytime. |
| **Recompute All** | `full` | Reads, rebuilds the taste model, scores, and **writes** `restash_*` to scenes + performers. Skips entities whose score is unchanged. |
| **Clear Restash Data** | `clear` | Removes the `restash_*` keys from every entity. Other custom fields and `rating100` are left untouched. |
| **Quick Refresh** | `refresh` | Fast daily re-score from the cached taste model (written by `Recompute All`): re-applies freshness, novelty, jitter, and wildcards **without** rebuilding affinities or reading watch histories. Self-heals to a full recompute if the cache is missing or stale. See [Scheduling](#scheduling). |

**Non-destructive by design:** writes use the **partial** form of `CustomFieldsInput`
(merge), so your own custom fields survive; `Clear` uses the **remove** form. The plugin
**never writes `rating100`**, and it registers no update hooks (so it can't trigger itself).

### The taste-model cache

`Recompute All` writes a `restash_state.json` file next to the plugin (in the `restash/`
folder) holding the affinity model and each scene's pre-freshness base. **Quick Refresh**
reads it to skip the expensive affinity rebuild and history read. It's a pure speed cache:
the authoritative scores live in `custom_fields`, and the file is fully regenerable — delete
it (or change a scoring setting) and the next Quick Refresh self-heals by running a full
recompute. It's local-only and never committed to git.

### Reading the scores

Request `custom_fields` in a `findScenes` / `findPerformers` query and sort/rank
client-side on `restash_score`:

```graphql
query {
  findScenes(filter: { per_page: 50 }) {
    scenes { id title custom_fields }
  }
}
```

Custom fields are **filterable** in the Stash UI too, so you can build saved filters (e.g.
"fresh discoveries" where `restash_score` ≥ 90). Note: Stash supports custom-field
*filtering* but not *sorting* in the UI, so sort by score via the API/client.

---

## Scheduling

Stash has **no built-in scheduler for plugin tasks**, so run **Quick Refresh** on a
schedule from outside Stash. Quick Refresh is the cheap daily job: it re-applies
freshness, novelty, jitter, and wildcards from the cached taste model (written by
**Recompute All**) without rebuilding affinities. If the cache is missing or stale it
self-heals by running a full recompute. Expect a daily refresh to skip most scenes as
unchanged (performers churn a bit more — see the determinism note below); that is normal
and correct.

Trigger it via the GraphQL `runPluginTask` mutation. A ready-to-use helper lives in
[`scripts/restash-refresh.sh`](scripts/restash-refresh.sh):

```bash
STASH_URL=http://localhost:9999 ./scripts/restash-refresh.sh
# with auth enabled:
STASH_URL=http://host:9999 STASH_API_KEY=xxxx ./scripts/restash-refresh.sh
```

### cron

```cron
0 4 * * * STASH_URL=http://localhost:9999 /opt/restash/scripts/restash-refresh.sh >> /var/log/restash-refresh.log 2>&1
```

### systemd timer

Copy [`scripts/restash-refresh.service`](scripts/restash-refresh.service) and
[`scripts/restash-refresh.timer`](scripts/restash-refresh.timer) to
`/etc/systemd/system/` (edit the `ExecStart` path and `STASH_URL`/`STASH_API_KEY`), then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now restash-refresh.timer
systemctl list-timers restash-refresh.timer
```

The underlying mutation (for reference):

```graphql
mutation { runPluginTask(plugin_id: "restash", task_name: "Quick Refresh") }
```

---

## Settings

Exposed under **Settings → Plugins → Restash**. Defaults match the spec.

| Setting | Default | Meaning |
|---|---|---|
| Taste half-life (days) | `90` | How fast older watch events fade when building taste affinities. |
| Cooldown period (days) | `21` | Length of the post-watch suppression before rediscovery begins. |
| Freshness strength | `1.0` | Multiplier on the cooldown/rediscovery effect. |
| Wildcard % | `2.0` | Share of the library promoted as low-confidence "wildcards" each day. |
| Blend manual ratings as a taste prior | `false` | If on, a performer's manual `rating100` nudges their affinity (read-only; never written back). |
| Exclusion tag name | `[Restash: Exclude]` | Entities with this tag are dropped from scoring entirely; any existing `restash_*` keys on them are removed. |

Operational knobs (batch size, retry/backoff, the subset-first write cap) are tuned for
safe defaults and set programmatically rather than through the UI.

> **rating100 mirror:** Restash never writes the native `rating100` rating. An
> optional mirror (also write the score to `rating100`, for native UI sorting) is planned
> as a separate future release and will add its own setting when it lands. A "dry run" is
> simply the **Dry Run Report** task — there's no separate toggle.

---

## How the score is built (plain-English tour)

The maths stays exactly as implemented; this is just the narration.

- **Events.** Each play counts ~1× how completely it was watched (floored so a quick sample
  still counts a little); an "o" counts ~4× a full play — it's the strongest positive
  signal. A play that was abandoned early **and** barely watched gets a small penalty.
  *(0.1.0 detail D11: abandonment requires low completion too, because Stash resets a
  scene's resume position to 0 once it's finished — so resume-position alone would wrongly
  punish fully-watched scenes.)*
- **Taste model.** Every tag/performer/studio accumulates time-decayed event value,
  normalised so merely-common tags don't win by ubiquity, then standardised and squashed
  into roughly −1…+1. A favourited performer gets a fixed bump.
- **Scene base.** A blend of top performer affinities, rarer-tag-weighted tag affinities,
  studio affinity, and a quality prior (resolution, a learned duration "sweet spot",
  marker density, organised flag). Scenes you *have* watched blend in their own direct
  evidence, weighted by how much history they have.
- **Freshness.** From days since you last engaged: buried for the first couple of days,
  recovering across the cooldown window, then a rediscovery bonus that peaks months out.
  Never-watched scenes instead get a **novelty** boost that fades over their first month.
  *(0.1.0 detail D13: a scene's own evidence decays on a slower 365-day clock than the
  90-day taste clock, so genuine old favourites actually climb back instead of fading.)*
- **Satiation.** A category over ~25% of the last week's activity is damped (down to a
  floor), so a binge quietly rotates the feed toward everything else and recovers within
  days once you stop.
- **Serendipity.** A tiny deterministic daily jitter breaks ties (stable all day, different
  tomorrow), and a few low-confidence "wildcards" are promoted into the upper band to keep
  the model learning.
- **Normalise.** Rank everything and map to 0–100 by percentile (ties share the average
  rank, which is what makes two same-day runs reproducible).
- **Performers** are scored from their best (shrinkage-adjusted) scenes, their own
  affinity, their freshness, their unwatched-but-loved supply, and newcomer novelty;
  favourites are floored at the 60th percentile. *(0.1.0 detail D12: a performer's
  best-scenes term is shrunk toward the population mean by how many scored scenes they
  have, so a one-scene ensemble cast can't all sit at the ceiling.)*

A determinism note worth knowing: the date-seeded parts (jitter, wildcards) are identical
all day, but the freshness/novelty terms move with the real clock. So an immediate re-run
rewrites only the entities whose **integer** percentile actually shifted — most scenes are
skipped, though performers churn more: their scores ride a global percentile re-rank, so a
microscopic shift flips many across rounding boundaries. **Quick Refresh** behaves the same
way and shares the same skip-unchanged write path, so a scheduled daily run stays cheap.

---

## Development

The repo root is a small Python project; the installable plugin is the `restash/` folder.

```bash
python -m venv .venv && . .venv/bin/activate
pip install stashapp-tools pytest
pytest                      # 120+ offline unit tests, no Stash needed
```

`restash/tools/run_local.py` runs a task locally by feeding `restash.py` the same stdin
JSON Stash would send. **It connects to a live Stash — only run it intentionally.**

```bash
# Dry run against a live server (reads only):
python restash/tools/run_local.py --url http://HOST:9999 --mode dry

# Subset-first write gate — write to only the first N entities:
python restash/tools/run_local.py --url http://HOST:9999 --mode full --limit 5

# Targeted write — write to only specific scene IDs (e.g. to verify non-destructive
# merging against scenes you know already have custom fields):
python restash/tools/run_local.py --url http://HOST:9999 --mode full --ids 8137,8138,8139
```

Pass `--api-key KEY` if your Stash has authentication enabled.

### Releasing

`restash.yml`'s `version:` is what the Stash UI shows — it is **not** derived from the git
tag, so it must be bumped in the same commit as any release tag. `scripts/check_version.py
<tag>` enforces this (exit 1 on mismatch), and CI runs it automatically on tag pushes:

```bash
python scripts/check_version.py v0.2.0   # OK when restash.yml says 0.2.0
```

---

## Troubleshooting

- **"This Stash build lacks scene custom_fields…" on startup.** Your Stash predates scene
  custom fields. Upgrade to a recent stable build (v0.30+) and re-run.
- **`ModuleNotFoundError: stashapi`.** `stashapp-tools` isn't installed for the Python
  Stash invokes. Install it there (see *Docker / Alpine notes*).
- **`python: not found` (Docker/Alpine).** The image exposes `python3` only — install a
  `python` shim or change `exec:` in `restash.yml` to `python3`.
- **GraphQL content-type / transport errors after a Stash upgrade.** v0.29 changed the
  GraphQL response content-type; this is handled by `stashapp-tools`, so keep it updated.
- **A task seems to do nothing.** The plugin is task-only and registers no update hooks
  (deliberate, to avoid self-triggering loops). Check **Settings → Logs**; `Recompute All`
  logs how many entities it wrote/skipped, and reports a non-zero exit if the server
  rejected any update.
- **Scores didn't change on a re-run.** Expected — `Recompute All` skips entities whose
  score is unchanged.

---

## License

[MIT](LICENSE) © 2026 Espionage9248.
