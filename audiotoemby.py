import sqlite3
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# -----------------------------
# CONFIGURATION
# -----------------------------
DB1_PATH = "/Audiobookshelf/config/absdatabase.sqlite REPLACE WITH PATH TO ABS DB"
DB2_PATH = "/EmbyMediaServer/config/data/playback_reporting.db REPLACE WITH PATH TO EMBY DB"

SOURCE_TABLE = "playbackSessions"
TARGET_TABLE = "PlaybackActivity"
DRY_RUN = False

 # UserID map by user from ABS --> Emby1 ABS USERS FOUND IN ABS SQL DB in table 'users'
USER_ID_MAP = {
    "UserIDinABS1": "CorrespondingUserIDinEmby1",
    "UserIDinABS2": "CorrespondingUserIDinEmby2",
} 

# -----------------------------
# HELPERS
# -----------------------------

def get_all_emby_items(server_url="http://EMBYIPHERE:8096"):
    """Fetches all items once to avoid N+1 API calls."""
    params = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "Fields": "Name",
        "api_key": "EMBYAPIKEYHERE"
    }
    try:
        resp = requests.get(f"{server_url}/emby/Items", params=params, timeout=10)
        resp.raise_for_status()
        # Map { "lowercasename": "EmbyID" }
        return {item.get("Name", "").lower(): item.get("Id") for item in resp.json().get("Items", [])}
    except Exception as e:
        print(f"Warning: Could not fetch Emby items: {e}")
        return {}

def format_date(iso_string):
    """Parses UTC and converts to Central Time with Emby-specific precision."""
    dt = datetime.fromisoformat(iso_string.replace(" +00:00", "+00:00"))
    dt_central = dt.astimezone(ZoneInfo("America/Chicago"))
    return dt_central.strftime("%Y-%m-%d %H:%M:%S.%f") + "0"

# -----------------------------
# MAIN SYNC LOGIC
# -----------------------------

def sync_databases():
    # 1. Setup Connections
    conn1 = sqlite3.connect(DB1_PATH)
    conn1.row_factory = sqlite3.Row
    cur1 = conn1.cursor()

    conn2 = sqlite3.connect(DB2_PATH)
    cur2 = conn2.cursor()

    # 2. Pre-fetch external data
    print("Pre-fetching Emby library and existing records...")
    emby_map = get_all_emby_items()
    
    cur2.execute(f"SELECT UserId, DateCreated FROM {TARGET_TABLE}")
    existing_records = set(cur2.fetchall())

    # 3. Pull data with JOIN to handle device info in one go
    # Using a subquery for devices to get the latest updated record per device
    query = f"""
        SELECT 
            p.createdAt, p.userId, p.displayTitle, p.timeListening, 
            d.clientName as DeviceName, d.ipAddress as RemoteAddress
        FROM {SOURCE_TABLE} p
        LEFT JOIN (
            SELECT id, clientName, ipAddress, MAX(updatedAt) 
            FROM devices GROUP BY id
        ) d ON p.deviceId = d.id
    """
    cur1.execute(query)
    rows = cur1.fetchall()

    records_to_insert = []
    
    # 4. Process Rows
    for row in rows:
        try:
            # Transform data
            date_created = format_date(row['createdAt'])
            user_id = USER_ID_MAP.get(row['userId'])
            
            if not user_id:
                continue # Skip unmapped users

            # Deduplication check (In-memory is fast)
            if (user_id, date_created) in existing_records:
                continue

            item_name = row['displayTitle']
            item_id = emby_map.get(item_name.lower())
            play_duration = int(round(float(row['timeListening'] or 0)))

            # Prepare row for DB2
            records_to_insert.append((
                date_created,
                user_id,
                item_id,
                item_name,
                play_duration,
                row['DeviceName'],
                row['RemoteAddress'],
                "Audio",           # ItemType
                "DirectPlay",      # PlaybackMethod
                "AudioBookShelf",  # ClientName
                0                  # PauseDuration
            ))
        except Exception as e:
            print(f"Error processing row: {e}")
            continue

    # 5. Batch Insert
    if records_to_insert:
        columns = "DateCreated, UserId, ItemId, ItemName, PlayDuration, DeviceName, RemoteAddress, ItemType, PlaybackMethod, ClientName, PauseDuration"
        placeholders = ", ".join(["?"] * 11)
        insert_sql = f"INSERT INTO {TARGET_TABLE} ({columns}) VALUES ({placeholders})"

        if DRY_RUN:
            print(f"DRY RUN: Would have inserted {len(records_to_insert)} records.")
        else:
            cur2.executemany(insert_sql, records_to_insert)
            conn2.commit()
            print(f"Successfully synced {len(records_to_insert)} new records.")
    else:
        print("No new records to sync.")

    conn1.close()
    conn2.close()

if __name__ == "__main__":
    sync_databases()
