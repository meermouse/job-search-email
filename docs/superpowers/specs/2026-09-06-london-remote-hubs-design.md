# Remote Location Hubs, Foundation Fixes, and Sponsor-Unverified Carve-Out

**Date:** 2026-09-06
**Branch:** feature/FE-021-remote-jobs-check
**Status:** Draft

## Problem

`include_remote` (FE-020) added a single UK-wide remote leg and a strict fully-remote
confirmation gate. Jie's real interest is narrower and higher-value: **fully-remote
roles at London employers** — London has the density of senior digital-transformation
and governance roles she is targeting. Those roles are currently indistinguishable
from the UK-wide remote pool and are not deliberately searched for.

A live probe run (Jie's profile, `include_remote` on, experimental London hub legs
added to jobspy and Reed) surfaced both the opportunity and the obstacles:

- The London hub leg found **273 distinct jobs the UK-wide leg did not** — real
  incremental coverage.
- `classify_locations` sends every uncached location string in **one** Haiku call
  (1024-token cap, no batching). At ~200 locations it returned invalid JSON, silently
  defaulted every location to `uncertain`, **and wrote `uncertain` into
  `location_cache.json`** — poisoning the cache permanently.
- Reed's `"{query} remote"` legs returned mostly contractor / IR35 / interim roles,
  with day-rates (£240, £650) misparsed as annual salaries, and location strings that
  are bare postcodes (`EC3A5AT`, `WC2A3LH`) the classifier cannot read. jobspy's
  structured `is_remote=True` leg was the source of nearly all genuinely-remote jobs.
- For a sponsor-filtered profile, genuinely-remote roles are disproportionately
  agency-posted (Michael Page, Hays, Tiger, Sanderson) and are hard-rejected by the
  recruitment / sponsor gate even when the advert states fully-remote working. This
  removes most of Jie's remote-London supply.
- Relevance, not availability, is the bottleneck: the extra jobs were mostly outside
  Jie's domain, and the scorer — the stage that would filter them — is not aware that
  a confirmed-remote far-afield job is *wanted*, and its existing "location outside
  area → exclude" instruction actively works against this feature.
- A ` ` character in a job title crashes `job-search-debug`'s report writing on
  Windows (`UnicodeEncodeError`, cp1252) after the JSON outputs are written.

Goal: deliberately search named location hubs (starting with London) for fully-remote
roles, call them out distinctly in the email, fix the classifier foundation this
depends on, and stop the sponsor gate from silently discarding confirmed-remote roles
whose sponsor status merely needs manual checking.

## Decisions Made

| Decision | Choice |
|---|---|
| Config shape | Replace the `include_remote` bool with a `remote:` block: `uk_wide: bool` + `hubs: list[str]`. Old `include_remote:` key → hard error on load. |
| First adopter | Jie. The app is built for her; the sponsor-gate attrition is addressed by the carve-out rather than by switching profiles. |
| Hub search mechanism | jobspy only (`location=<hub>`, `is_remote=True`), one leg per hub. No Reed hub leg — its keyword-remote search is too noisy. |
| Provenance | New `JobListing.search_legs: list[str]` from a small controlled vocabulary; `deduplicate` unions legs on collision. |
| Location classifier | Batch at 50 strings/call; never cache a fallback verdict; one-time purge of the poisoned `location_cache.json`. |
| Postcode handling | `normalise_location` maps London outward codes to `London`; other bare postcodes left unchanged. |
| Remote verdict set | Add `remote_with_travel` (remote-first but recurring client/site travel) — kept at the gate, badged distinctly. `unverified` still never cached, still fails closed. |
| Sponsor carve-out | For **all** confirmed `remote` / `remote_with_travel` jobs: downgrade *unverifiable* sponsor/recruitment rejections (agency client undisclosed, company string too sparse) to keep-with-`sponsor_unverified`. A named company that clearly cannot sponsor is still rejected. |
| Email | Up to three blocks: main table; "Remote — London"; "Remote — sponsor not verified". No job in two blocks. |
| Scorer | When `remote` is configured, tell the scorer a confirmed-remote role must not be penalised for being outside the home region; `remote_with_travel` is acceptable. |
| Query generation | One prompt line favouring role/skill/seniority angles over location-bound title variants when `remote` is configured. No mechanical `" remote"` keyword-stuffing. |

## Design

### 1. Profile setting

`profiles/*.yaml`:

```yaml
remote:
  uk_wide: true       # existing UK-wide remote leg (jobspy + Reed)
  hubs: [London]      # named location hubs searched remote-only (jobspy)
```

`profile.py`:

- Parse `data.get("remote")`. Accept an absent block (both fields default:
  `uk_wide: false`, `hubs: []`), a partial block, and validate that `hubs` is a list
  of non-empty strings.
- If the legacy key `include_remote` is present, raise `ValueError` with a message
  naming the new block.
- `Profile` gains `remote_uk_wide: bool = False` and
  `remote_hubs: list[str] = field(default_factory=list)`.
- Keep a compatibility read-only `include_remote` property:
  `self.remote_uk_wide or bool(self.remote_hubs)`. Existing call-sites
  (`main.py`, `explain_job.py`, `jobspy_searcher.py`, `reed.py`) keep working; each is
  migrated to the specific field it actually needs during implementation.
- Both fields feed `fingerprint_profile` (via the existing profile serialisation), so
  changing the block invalidates the cached search plan, exactly as `include_remote`
  does today.

Jie's profile gains `remote: { uk_wide: true, hubs: [London] }`. Marc's profile is
unchanged (no `remote` block → behaviour identical to today).

### 2. Foundation fixes (Tier 1)

**2a. Batch `classify_locations`** (`location_filter.py`). Replace the single
all-strings call with batches of `_BATCH_SIZE = 50`, mirroring `remote_filter`:
iterate `to_classify` in slices, one `messages.create` per slice, merge verdict maps.
`max_tokens` stays 1024 (a 50-entry map fits comfortably).

**2b. Never cache a fallback verdict.** On exception, or when a verdict is missing /
not one of `within|outside|uncertain`, return `uncertain` for that string **without
writing it to `cache`**. Cache writes happen only for verdicts the model actually
returned. (Same principle as `remote_filter` not caching `unverified`.) Successful
verdicts are still cached as now.

**2c. One-time cache purge.** Implementation step (not code): delete
`location_cache.json` once so the poisoned `"…London… → uncertain"` entries are
regenerated correctly. The file is gitignored and rebuilt on the next run.

**2d. `normalise_location(raw: str) -> str`** — new helper in `location_filter.py`
(already imported across the pipeline):

- Trim; collapse internal whitespace.
- If the string is a bare UK postcode (full, e.g. `EC3A 5AT`, or outward-only, e.g.
  `EC3A`) whose outward area matches a London district — `EC`, `WC`, `E`, `N`, `NW`,
  `SE`, `SW`, `W` (the standalone `W`/`E`/`N` London areas plus `EC`/`WC`/`NW`/`SE`/`SW`;
  **not** `EN`, `WD`, `SG`, `SL`, `SM`, `WS`, etc., which are Home Counties) — return
  `"London"`. A conservative explicit prefix set matched against the parsed outward
  code, not a fuzzy substring match.
- Any other bare postcode → returned unchanged.
- Any non-postcode string → returned unchanged.

Applied in two places: building `unique_locations` in `run_pipeline` (so the
classifier and its cache key see `London`, not `EC3A5AT`), and in `job_hub`
(Section 3d). Job objects' own `location` strings are left as-is for display.

**2e. Unicode crash.** In `debug_run.py`: write `DEBUG_REPORT_PATH` with
`encoding="utf-8"` (already the case) and guard `_print_decisions` so a title
containing characters outside the console codepage cannot abort the run — print via a
helper that falls back to `str.encode(sys.stdout.encoding, "replace").decode(...)`.
Isolated; no behaviour change beyond not crashing.

### 3. Hub search, provenance, dedup (Tier 2)

**3a. Hub legs — `jobspy_searcher.search`.** After the existing radius leg and (when
`remote_uk_wide`) the UK-wide leg, add one leg per hub in `profile.remote_hubs`:

```python
for hub in profile.remote_hubs:
    try:
        frames.append((f"jobspy:hub:{hub}", scrape_jobs(
            site_name=["linkedin", "indeed"], search_term=query,
            location=hub, is_remote=True,
            results_wanted=50, country_indeed="UK",
        )))
    except Exception as exc:
        print(f"[jobspy_searcher] hub leg {hub!r} failed for {query!r}: {exc}", file=sys.stderr)
```

Each leg is `(leg_name, dataframe)`; rows are converted with `search_legs=[leg_name]`.
A hub-leg failure must not lose radius/UK-wide results (independent try/except per
leg). Reed and NHS are unchanged. Reed's existing UK-wide `" remote"` leg stays under
`remote_uk_wide` — its noise is a known limitation, out of scope here.

**3b. `JobListing.search_legs: list[str] = field(default_factory=list)`.** Controlled
vocabulary: `jobspy:radius`, `jobspy:uk-remote`, `jobspy:hub:<hub>`, `reed:radius`,
`reed:uk-remote`, `nhs:radius`. Every searcher sets it on the listings it creates.
`asdict` / JSON round-trip it into `job_results.json` for tooling.

**3c. `deduplicate`** keeps the `(title.lower().strip(), company.lower().strip())`
key. On a collision, union the incoming job's `search_legs` into the kept job's
(order-preserving, no duplicates) instead of discarding them. The kept job is still
the first one seen.

**3d. `job_hub(job, hubs: list[str]) -> str | None`** — new helper in `email.py`
(its only consumer):

- For each `hub` in `hubs`: return `hub` if `f"jobspy:hub:{hub}"` is in
  `job.search_legs`, **or** `normalise_location(job.location)` case-insensitively
  equals `hub`.
- Else `None`.

### 4. Remote verdict and filter changes (Tier 3a / 3c)

**4a. `remote_filter.py` — third verdict `remote_with_travel`.** Prompt gains a class:
the posting states remote-first working **but** names recurring travel to client
sites, regional offices, or customer locations as a routine part of the role.
Occasional pre-arranged visits stay under `remote` as now. Verdict set becomes
`remote | remote_with_travel | not_remote`. `classify_remote` accepts and caches all
three; anything else (missing/garbled) → `not_remote` as now; API failure →
`unverified`, still never cached.

**4b. `filter.py` — `_check_location`.** For opted-in profiles the gate treats
`remote_with_travel` exactly like `remote` (kept), but sets a `remote_with_travel`
flag instead of `remote_confirmed`. `not_remote` / `unverified` / `uncertain`
unchanged (rejected, distinct reasons).

**4c. Sponsor / recruitment carve-out.** Applies when the job's location result
carries `remote_confirmed` **or** `remote_with_travel`. In `filter_jobs`, compute a
`remote_ok` boolean from the location result's flags before the recruitment / sponsor
checks, and thread it in:

- `_check_recruitment`: if `remote_ok` and the rejection would be
  `_RECRUITMENT_REASON` (agency, client not disclosed) → instead return a
  non-rejected `FilteredResult` with flag `sponsor_unverified`.
- `_check_sponsor`: if `remote_ok` and the rejection reason would be
  `"company not specified — cannot verify approved sponsor"` (sparse company string)
  → keep with flag `sponsor_unverified`. The reason
  `"company not on approved sponsor list"` (a resolved company name that simply is
  not on the list) is **still a hard reject** — that company cannot sponsor whether
  the role is remote or not.

`sponsor_unverified` jobs flow through scoring normally. They are never mixed with
sponsor-verified results in the email.

Non-remote jobs: every filter path is exactly as today.

### 5. Email (`email.py`)

`build_email_html` partitions the scored, non-rejected pool (analysis present) into
three disjoint groups, in this order:

1. **Main table** — everything not claimed by group 2 or 3. Top 20 by score. A
   sponsor-verified UK-wide confirmed-remote job that is not a hub job stays here with
   the existing "Remote" badge; `remote_with_travel` jobs here get "Remote · some
   travel".
2. **Remote — London** — `job_hub(job, profile.remote_hubs)` is truthy **and** the job
   is sponsor-verified (no `sponsor_unverified` flag) **and** confirmed
   `remote_confirmed` / `remote_with_travel`. Its own table, ranked by score, same
   columns, badge per verdict. Rendered only when `remote_hubs` is non-empty and the
   group is non-empty. Heading per hub if more than one hub is ever configured.
3. **Remote — sponsor not verified** — carries `sponsor_unverified`. Its own table,
   ranked by score, with a caption: "Sponsor status could not be verified from the
   listing — check the employer manually." Hub and non-hub jobs mixed.

`top_n` / preamble logic unchanged; the count reflects the main table as today.
`build_debug_email_html` and the `explain-job` / `filter_trace` output gain the
`remote_with_travel` verdict and the `sponsor_unverified` disposition, following the
existing stage-trace pattern.

### 6. Scorer and query generation (Tier 3b)

**6a. `scorer._build_system_prompt`.** When `profile.remote_uk_wide or
profile.remote_hubs`, append: the candidate actively wants fully-remote work, so do
**not** set `exclude=true` or mark down a role solely because its location is outside
the candidate's home region when the posting is remote; a role that is remote-first
with some client travel is acceptable. Does not change score bands — removes a wrong
penalty. Prompt text feeds the score-cache fingerprint, so stale scores invalidate.

**6b. `queries.QUERY_GENERATION_PROMPT`.** When `remote` is configured, add one rule:
the candidate is open to fully-remote roles nationally — favour target-title,
adjacent-title, skills-led and seniority angles; do not narrow to location-bound
title variants. Still exactly 8 queries. No mechanical keyword-stuffing.

### 7. Testing and tooling

Unit tests (injected verdicts / fixtures; no live LLM calls):

- `profile.py`: `remote:` block (full, partial, absent); legacy `include_remote:` key
  raises with the pointer message; `include_remote` compatibility property.
- `location_filter.py`: batching splits at 50; a failed batch returns `uncertain` and
  writes nothing to the cache; a successful batch still caches.
- `location_normalise`: London outward codes → `London`; a non-London postcode is
  unchanged; an ordinary place string is unchanged.
- `dedup`: colliding jobs union their `search_legs`.
- `remote_filter.py`: `remote_with_travel` parsed and cached; `unverified` not cached.
- `filter.py`: carve-out matrix — confirmed-remote + agency → kept `sponsor_unverified`;
  confirmed-remote + sparse company → kept `sponsor_unverified`; confirmed-remote +
  resolved non-sponsor company → still rejected; `remote_with_travel` treated as
  `remote` at the gate; non-remote paths unchanged.
- `email.py`: three-group partition is disjoint; groups hidden when empty; badge text
  per verdict; `sponsor_unverified` never appears in group 1 or 2.
- `jobspy_searcher`: one hub leg per hub tagged `jobspy:hub:<hub>`; a hub-leg
  exception does not drop radius results.

Tooling:

- `job-search-email-local` fixtures gain a hub job, a `remote_with_travel` job, and a
  `sponsor_unverified` job so the offline dry run renders all three email groups.
- `job-search-debug` / `explain-job` traces surface the new verdict and disposition.
- `CLAUDE.md`: replace the `include_remote` sentence with the `remote:` block; note
  the London hub behaviour and the "sponsor not verified" email group.

## Out of Scope

- Reed hub legs (keyword-remote search too noisy).
- Overseas remote jobs.
- Remote leg for NHS Jobs (empty descriptions cannot pass confirmation).
- Changing the `uncertain` pass-through for profiles with no `remote` block.
- Hubs as anything other than a location string handed to jobspy (no radius, no
  per-hub salary weighting, no hub-specific query sets).
- Improving Reed's existing UK-wide `" remote"` leg.
