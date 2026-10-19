from pathlib import Path

# config.py がプロジェクト直下にある場合と backend/ 等のサブフォルダにある場合の両方に自動対応
_THIS_DIR = Path(__file__).resolve().parent
BASE_DIR = _THIS_DIR.parent if _THIS_DIR.name in ("backend", "scripts", "src") else _THIS_DIR

WEIGHTS = {
    "yt_views": 1,
    "yt_likes": 50,
    "yt_comments": 100,
    "nc_views": 5,
    "nc_mylist": 100,
    "nc_mylists": 100,
    "nc_comments": 10,
}

TOP_N = 20

# 既存のフォルダ構成（data/master/ または data/ 直下）を自動検出してパス解決
_MASTER_CANDIDATE_1 = BASE_DIR / "data" / "master" / "songs_master.json"
_MASTER_CANDIDATE_2 = BASE_DIR / "data" / "songs_master.json"
MASTER_FILE = _MASTER_CANDIDATE_1 if _MASTER_CANDIDATE_1.exists() or not _MASTER_CANDIDATE_2.exists() else _MASTER_CANDIDATE_2

SNAPSHOTS_DIR = BASE_DIR / "data" / "snapshots"
PREV_SNAPSHOT = SNAPSHOTS_DIR / "prev_monday.json"
LATEST_SNAPSHOT = SNAPSHOTS_DIR / "latest_monday.json"

_DRAFT_CANDIDATE_1 = BASE_DIR / "data" / "drafts" / "weekly_draft.json"
_DRAFT_CANDIDATE_2 = BASE_DIR / "data" / "weekly_draft.json"
DRAFT_FILE = _DRAFT_CANDIDATE_1 if _DRAFT_CANDIDATE_1.exists() or _DRAFT_CANDIDATE_1.parent.exists() else _DRAFT_CANDIDATE_2
BACKUP_DRAFT_FILE = DRAFT_FILE.parent / "weekly_draft.backup.json"

PUBLIC_DATA_DIR = BASE_DIR / "public" / "data"
PUBLIC_LATEST = PUBLIC_DATA_DIR / "latest_ranking.json"
ARCHIVE_DIR = PUBLIC_DATA_DIR / "archives"
ARCHIVE_INDEX = ARCHIVE_DIR / "archive_index.json"