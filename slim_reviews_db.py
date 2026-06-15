"""
Slim reviews.db after each scrape + ingestion.

Run order:
  1. python api_server.py             # server running in background
  2. trigger scrape via API           # POST /scrape
  3. ingest reviews into your own DB  # GET /reviews/{place_id}
  4. python slim_reviews_db.py        # this script

The scraper's "what's new?" logic only reads review_id + content_hash +
is_deleted from the reviews table. Everything else is dead weight once
you've ingested it into your own DB.

KEEP_LAST_N rationale (empirical):
  Early-stop needs `stop_threshold` (default 3) consecutive scroll batches
  of all-matched reviews, batch_total >= 3 each. The scraper tracks
  processed review_ids cumulatively, so batches are DISJOINT — the floor
  for KEEP_LAST_N is literally the sum of the first 3 batch sizes.

  Observed on Gold Needle Tailoring (167 reviews):
    batch 1: 10 reviews  (initial DOM render before any scroll)
    batch 2: 20 reviews
    batch 3: 20 reviews
    => floor = 50

  Set to 60 for ~20% headroom against batch-size variance run-to-run.
  Re-measure with: grep "Fully matched batch" logs/*.log
"""

import sqlite3
from pathlib import Path

DB_PATH = "reviews.db"
KEEP_LAST_N = 60   # proven floor 50 (Gold Needle, 2026-06-14); +20% safety

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=ON")
cur = conn.cursor()

before = Path(DB_PATH).stat().st_size

# Step 1: drop all but N newest reviews per place
for (pid,) in cur.execute("SELECT place_id FROM places").fetchall():
    cur.execute(
        "DELETE FROM reviews WHERE place_id=? AND review_id NOT IN ("
        "  SELECT review_id FROM reviews WHERE place_id=? "
        "  ORDER BY COALESCE(review_date,'') DESC, created_date DESC "
        "  LIMIT ?)",
        (pid, pid, KEEP_LAST_N))

# Step 2: NULL heavy columns on survivors (scraper only reads
# review_id, content_hash, engagement_hash, is_deleted)
cur.execute(
    "UPDATE reviews SET "
    "  author=NULL, review_text=NULL, raw_date=NULL, "
    "  user_images=NULL, s3_images=NULL, "
    "  profile_url=NULL, profile_picture=NULL, s3_profile_picture=NULL, "
    "  owner_responses=NULL, sub_ratings=NULL")

# Step 3: wipe aux tables (see table reference)
for tbl in (
    "review_history",      # audit log of review changes
    "scrape_sessions",     # per-run metadata; FK SET NULL on reviews
    "sync_checkpoints",    # MongoDB sync state (unused)
    "selector_health",     # DOM selector reliability stats
    "api_audit_log",       # API request log (90d auto-prune)
    "place_aliases",       # alternate URLs for same place
):
    cur.execute(f"DELETE FROM {tbl}")

# Keep: reviews (slimmed), places, api_keys, schema_version, sqlite_sequence

conn.commit()
cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
cur.execute("VACUUM")
conn.close()

after = Path(DB_PATH).stat().st_size
print(f"Reclaimed {(before-after)/1024:.0f} KB ({100*(1-after/before):.0f}%)")