"""
Reset reviews.db to a scratch buffer after each scrape + ingestion.

PRECONDITION — your POST /scrape MUST drive the stop with a date boundary,
or every scrape becomes a full scroll of every place:
    "date_filter": {"mode": "early_stop",
                    "after": "<newest review_date you've ingested, minus a few days>",
                    "on_unparseable_date": "include"}
If you are NOT using date_filter, use the ledger variant (see bottom) instead.

Run order — must be SERIAL. Do not run this while a scrape job is in flight,
or you'll delete rows the server just wrote but your client hasn't GETted:
  1. POST /scrape   (with date_filter as above)
  2. GET /reviews/{place_id} -> transform -> your DB -> confirm success
  3. this script

Keeps: places, api_keys, schema_version, place_aliases, selector_health
(all <=16 KB; some load-bearing — deleting places makes GET /reviews 404).
Clears: the only two tables that actually grow (reviews + review_history)
plus per-run churn.
"""

import sqlite3

DB_PATH = "reviews.db"

WIPE = (
    "review_history",   # audit log; your own DB is the system of record
    "scrape_sessions",  # per-run metadata
    "api_audit_log",    # written on EVERY request, even with no API key set
    "sync_checkpoints", # MongoDB sync state (no-op if you don't sync)
    "reviews",          # the payload — listed last
)

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA busy_timeout=5000")   # wait out transient locks vs. failing
cur = conn.cursor()

n = cur.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

# FK off so delete order is irrelevant: we empty the whole related cluster,
# so no dangling references survive. VACUUM is deliberately absent — it needs
# an exclusive lock the running server won't grant, and WAL reuses freed pages
# so the file stabilizes on its own. Run VACUUM once, manually, server stopped,
# after the initial 100k backfill if you want the bytes back.
cur.execute("PRAGMA foreign_keys=OFF")
for tbl in WIPE:
    cur.execute(f"DELETE FROM {tbl}")
conn.commit()
cur.execute("PRAGMA foreign_keys=ON")
cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
conn.close()

print(f"Cleared {n} reviews + churn tables.")