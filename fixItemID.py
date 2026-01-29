import sqlite3
import requests
import re
# Configuration
EMBY_URL = "http://Input Emby server here:8096"
API_KEY = "APIKEYHERE"
DB_PATH = "/EmbyMediaServer/config/data/playback_reporting.db  Location of your Emby server's playback_reporting.db file"
TABLE_NAME = "PlaybackActivity" 

def clean_name(name):
    if not name: return ""
    name = re.sub(r'\s*[\(\[].*?[\)\]]', '', name)
    return name.strip().lower()

def get_valid_emby_ids(existing_ids):
    """Checks which IDs are still recognized by the Emby server."""
    if not existing_ids: return set()
    
    print(f"[*] Validating {len(existing_ids)} existing IDs with Emby...")
    session = requests.Session()
    session.params = {'api_key': API_KEY}
    
    # Emby allows querying multiple IDs at once separated by commas
    valid_ids = set()
    # Batch the check in groups of 200 to avoid URL length limits
    id_list = list(existing_ids)
    for i in range(0, len(id_list), 200):
        batch = ",".join(id_list[i:i+200])
        try:
            response = session.get(f"{EMBY_URL}/Emby/Items", params={'Ids': batch, 'Fields': 'Id'})
            items = response.json().get('Items', [])
            for item in items:
                valid_ids.add(item['Id'])
        except Exception as e:
            print(f"    Error validating batch: {e}")
            
    print(f"    {len(valid_ids)} IDs are still valid. {len(existing_ids) - len(valid_ids)} need updating.")
    return valid_ids

def update_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Get current IDs to check validity
    cursor.execute(f"SELECT DISTINCT ItemId FROM {TABLE_NAME} WHERE ItemId IS NOT NULL AND ItemId != ''")
    current_ids = {row[0] for row in cursor.fetchall()}
    valid_ids = get_valid_emby_ids(current_ids)

    # 2. Get Emby Library for the new mapping
    print("[*] Fetching current Emby library for re-mapping...")
    session = requests.Session()
    session.params = {'api_key': API_KEY}
    response = session.get(f"{EMBY_URL}/Emby/Items", params={
        'Recursive': True,
        'Fields': 'SeriesName,IndexNumber,ParentIndexNumber',
        'IncludeItemTypes': 'Movie,Episode',
    })
    emby_items = response.json().get('Items', [])
    
    lookup = {}
    for i in emby_items:
        if i.get('Type') == 'Episode':
            lookup[(clean_name(i.get('SeriesName')), i.get('ParentIndexNumber'), i.get('IndexNumber'))] = i.get('Id')
        else:
            lookup[(clean_name(i.get('Name')), 'movie')] = i.get('Id')

    # 3. Identify rows that need a new ID
    cursor.execute(f"SELECT DISTINCT ItemName, ItemType, ItemId FROM {TABLE_NAME}")
    db_rows = cursor.fetchall()
    
    update_payload = []
    ep_regex = re.compile(r"^(.*?) - s(\d+)e(\d+) - (.*)$")

    for raw_name, itype, current_id in db_rows:
        # SKIP if the current ID is already valid
        if current_id in valid_ids:
            continue
            
        # Attempt to find a new ID
        found_id = None
        if itype == "Episode":
            match = ep_regex.match(raw_name)
            if match:
                show, s, e, _ = match.groups()
                found_id = lookup.get((clean_name(show), int(s), int(e)))
        else:
            found_id = lookup.get((clean_name(raw_name), 'movie'))

        if found_id:
            update_payload.append((found_id, raw_name))

    # 4. Perform the Update
    if update_payload:
        print(f"[*] Applying {len(update_payload)} updates...")
        cursor.execute("BEGIN TRANSACTION")
        cursor.execute("CREATE TEMP TABLE Mapping(NewId TEXT, RawName TEXT)")
        cursor.executemany("INSERT INTO Mapping VALUES (?, ?)", update_payload)
        cursor.execute(f"""
            UPDATE {TABLE_NAME} 
            SET ItemId = (SELECT NewId FROM Mapping WHERE Mapping.RawName = {TABLE_NAME}.ItemName)
            WHERE ItemName IN (SELECT RawName FROM Mapping)
        """)
        conn.commit()
        print("[!] Database update complete.")
    else:
        print("[!] No updates needed. All IDs are either valid or no matches were found.")

    conn.close()

if __name__ == "__main__":
    update_database()