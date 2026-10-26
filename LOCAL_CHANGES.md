# Local changes vs upstream

Fork of georgekhananaev/google-reviews-scraper-pro. Branch: `my-local-dev`.
Last merged upstream: v1.3.1 (2026-10-19), tag `merged-upstream-v1.3.1`.

After every upstream merge, walk this list and confirm each item still exists
(`grep` the symbol). Fix anything missing *before* running the scraper.

Audit: `git diff master...my-local-dev --stat`

## Own files (no upstream counterpart — safe in merges)

- `modules/card_extract.py` — `extract_batch(driver, pane, keep_last)`: one
  in-page JS pass that expands "More", reads every unscraped card into a dict,
  and prunes already-scraped cards from the DOM. Replaces per-card Selenium calls.
- `slim_reviews_db.py` — utility script to shrink `reviews.db` (prune
  history/sessions). Not used by the scraper itself.
- `config.yaml` — committed on this branch (upstream gitignores it). Check
  defaults after merges: `use_mongodb`, `custom_params`, `browser_profile_dir`.

## Edits inside upstream files (conflict-prone — check after every merge)

### `modules/scraper.py`
- `from modules.card_extract import extract_batch` (import block) — **lost once, re-added**
- `import random` + `_sleep(base, jitter=0.4)` helper below the logger
- `CHROME_ARGS` constant and `chromium_arg=CHROME_ARGS` on all four `Driver()` calls
- `DOM_PRUNE_KEEP_DEFAULT` constant; `dom_prune_keep` read from config in `_scrape_once`
- `self.cards_seen` in `__init__`, updated each scroll iteration (live progress for JobManager)
- Scroll loop uses `extract_batch(...)` instead of `pane.find_elements(CARD_SEL)`;
  fresh-card loop is hand-written (includes upstream's `max_reviews` cap).
  Upstream's `_collect_fresh_cards` is kept only so upstream tests pass.
- `RawReview.from_dict(card)` instead of `from_card(card)` in the parse loop
- Fixed `time.sleep` calls in `_scrape_once` replaced with `_sleep(...)`

### `modules/models.py`
- `RawReview.from_dict(...)` — builds a review from the dict `extract_batch` returns.

### `modules/review_db.py`
- `count_reviews(..., after=...)` and `get_reviews(..., after=...)` — date lower bound.

### `api_server.py`
- `list_reviews`: `after: Optional[str] = None` query param (plain default on
  purpose — `Query()` breaks direct calls in tests).
- Job progress exposes `cards_seen`.

### `modules/job_manager.py`
- Reads `scraper.cards_seen` while a job runs (progress message).

### `start.py`
- Random 45–180 s pause between businesses in the multi-business loop.

### `.gitignore`
- Minor local additions (check diff).

## Merge procedure

1. `git switch master && git pull`
2. `git switch -c merge-upstream my-local-dev && git merge master`
3. Resolve conflicts keeping both sides; re-check every item above
4. `python -m pytest tests/ -k "not s3 and not mongodb" -q`
5. One real scrape with `--max-reviews 30`, confirm >5 reviews and signed-in log line
6. `git switch my-local-dev && git merge merge-upstream && git branch -d merge-upstream`
7. `git tag merged-upstream-vX.Y.Z` and update the header of this file