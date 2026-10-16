from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

WEIGHTS = {
    "yt_views": 1,
    "yt_likes": 50,
    "yt_comments": 100,
    "nc_views": 5,
    "nc_mylist": 100,
    "nc_comments": 10,
}

MASTER_FILE = BASE_DIR / "data" / "master" / "songs_master.json"
PREV_SNAPSHOT = BASE_DIR / "data" / "snapshots" / "prev_monday.json"
LATEST_SNAPSHOT = BASE_DIR / "data" / "snapshots" / "latest_monday.json"
DRAFT_FILE = BASE_DIR / "data" / "drafts" / "weekly_draft.json"

PUBLIC_DATA_DIR = BASE_DIR / "public" / "data"
PUBLIC_LATEST = PUBLIC_DATA_DIR / "latest_ranking.json"
ARCHIVE_INDEX = PUBLIC_DATA_DIR / "archive_index.json"
ARCHIVE_DIR = PUBLIC_DATA_DIR / "archives"