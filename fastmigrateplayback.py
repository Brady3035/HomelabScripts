import sqlite3

#Map of user IDs from DB2 → DB1 SUBSITITUE WITH YOUR OWN USER ID MAP
USER_MAP = {
 "userfromDB2_1": "userfromDB1_1",
 "userfromDB2_2": "userfromDB1_2",
 "userfromDB2_3": "userfromDB1_3",}

# Updated Dedup Key to ignore ItemId
DEDUP_KEY = [
    "DateCreated",
    "UserId",
    "ItemName",     # Replaced ItemId
    "PlayDuration", # Added for precision
    "ClientName",
    "DeviceName",
]

COLUMNS = [
    "DateCreated","UserId","ItemId","ItemType","ItemName",
    "PlaybackMethod","ClientName","DeviceName",
    "PlayDuration","PauseDuration","RemoteAddress","TranscodeReasons"
]

def fast_sync(db1, db2, table="PlaybackActivity", dry_run=False):
    conn = sqlite3.connect(db1)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("ATTACH DATABASE ? AS db2", (db2,))

        # Temp user map
        cur.execute("DROP TABLE IF EXISTS user_map")
        cur.execute("CREATE TEMP TABLE user_map (old_id TEXT PRIMARY KEY, new_id TEXT)")
        cur.executemany("INSERT INTO user_map VALUES (?,?)", USER_MAP.items())

        # Speed index - updated to match the new deduplication logic
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_dedupe_v2 ON {table} (DateCreated, UserId, ItemName, PlayDuration)")

        # Prepare column selections
        # Note: We still SELECT p.ItemId because it needs to be inserted, 
        # even if it's the "wrong" ID for now (you'll likely run your update script after this).
        select_cols = ", ".join([f"p.{c}" if c != "UserId" else "COALESCE(m.new_id, p.UserId) AS UserId" for c in COLUMNS])
        
        source_query = f"""
            FROM db2.{table} p
            LEFT JOIN user_map m ON m.old_id = p.UserId
            WHERE NOT EXISTS (
                SELECT 1 FROM main.{table} t
                WHERE t.DateCreated = p.DateCreated
                  AND t.UserId = COALESCE(m.new_id, p.UserId)
                  AND t.ItemName = p.ItemName
                  AND t.PlayDuration = p.PlayDuration
                  AND t.ClientName = p.ClientName
                  AND t.DeviceName = p.DeviceName
            )
        """

        if dry_run:
            cur.execute(f"SELECT {select_cols} {source_query} LIMIT 50")
            rows = cur.fetchall()
            
            if not rows:
                print("Everything is up to date. No new rows to add.")
            else:
                print(f"--- DRY RUN: Previewing first {len(rows)} rows ---")
                print(f"{'Date':<20} | {'User':<15} | {'Item Name'}")
                print("-" * 60)
                for row in rows:
                    print(f"{row['DateCreated'][:19]:<20} | {row['UserId'][:8]}... | {row['ItemName']}")
                
                cur.execute(f"SELECT COUNT(*) {source_query}")
                print(f"\nTotal pending: {cur.fetchone()[0]} rows.")
        else:
            # Perform actual sync
            cur.execute(f"INSERT INTO main.{table} ({', '.join(COLUMNS)}) SELECT {select_cols} {source_query}")
            conn.commit()
            print(f"Success: Synced {cur.rowcount} rows.")

    except sqlite3.Error as e:
        print(f"SQLite Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    fast_sync(
        "EmbyMediaServer/config/data/playback_reporting.db REPLACE WITH PATH TO FIRST/DESTINATION DB",
        "EmbyMediaServer2/config/data/playback_reporting.db REPLACE WITH PATH TO SECOND/SOURCE DB",
        "PlaybackActivity",
        dry_run=True
    )
