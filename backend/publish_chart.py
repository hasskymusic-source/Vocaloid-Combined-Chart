import os
import re
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    import config
except ImportError:
    config = None

JST = timezone(timedelta(hours=9))

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent if BASE_DIR.name == "backend" else BASE_DIR


def resolve_config_path(attr_names, default_rel_path):
    if config:
        for name in attr_names:
            if hasattr(config, name):
                val = getattr(config, name)
                if val:
                    return Path(val)
    return PROJECT_ROOT / default_rel_path


DRAFT_FILE = resolve_config_path(["DRAFT_FILE", "WEEKLY_DRAFT_FILE"], "data/weekly_draft.json")
BACKUP_DRAFT_FILE = resolve_config_path(["BACKUP_DRAFT_FILE", "WEEKLY_DRAFT_BACKUP_FILE"], "data/weekly_draft.backup.json")
PUBLIC_LATEST = resolve_config_path(["PUBLIC_LATEST", "LATEST_RANKING_FILE"], "public/data/latest_ranking.json")
ARCHIVE_DIR = resolve_config_path(["ARCHIVE_DIR", "ARCHIVES_DIR"], "public/data/archives")
ARCHIVE_INDEX = resolve_config_path(["ARCHIVE_INDEX"], "public/data/archives/archive_index.json")

# 漏洩防止パターン（Google APIキー / GitHub Token / 秘密鍵）
SECRET_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "Google/YouTube API Key"),
    (re.compile(r"gh[pousr]_[0-9A-Za-z]{36,255}"), "GitHub Personal Access Token"),
    (re.compile(r"github_pat_[0-9A-Za-z_]{50,255}"), "GitHub Fine-grained Token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "Private Key"),
]

# PCローカルパス（ユーザー名・本名流出防止）パターン
LOCAL_PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\Users\\[^\\\"\'\s]+", re.IGNORECASE),
    re.compile(r"[A-Za-z]:/Users/[^/\"\'\s]+", re.IGNORECASE),
    re.compile(r"/Users/[^/\"\'\s]+"),
]


def inspect_and_redact_text(text, label="data"):
    """
    公開対象データにAPIキーが含まれていれば例外で公開を緊急停止し、
    ローカルPCのユーザーパスが含まれていれば自動的にマスクして個人情報を保護する
    """
    if not text:
        return text

    for regex, secret_name in SECRET_PATTERNS:
        if regex.search(text):
            raise RuntimeError(
                f"[SECURITY BLOCK] {label} 内に機密情報 ({secret_name}) の混入を検知したため、公開処理を緊急停止しました。"
            )

    redacted = text
    for path_regex in LOCAL_PATH_PATTERNS:
        redacted = path_regex.sub("[REDACTED_PATH]", redacted)

    return redacted


def load_json(filepath, default=None):
    path_obj = Path(filepath)
    if not path_obj.exists():
        return default
    try:
        with open(path_obj, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] JSON読み込み失敗 ({path_obj}): {e}")
        return default


def save_json(filepath, data):
    path_obj = Path(filepath)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    raw_json = json.dumps(data, ensure_ascii=False, indent=2)
    safe_json = inspect_and_redact_text(raw_json, label=str(path_obj.name))
    with open(path_obj, "w", encoding="utf-8") as f:
        f.write(safe_json + "\n")


def normalize_period_str(period_str, now_dt=None):
    if now_dt is None:
        now_dt = datetime.now(JST)
    if not period_str or not isinstance(period_str, str):
        today = now_dt.date()
        this_monday = today - timedelta(days=today.weekday())
        start_d = this_monday - timedelta(days=7)
        end_d = this_monday - timedelta(days=1)
        return f"{start_d.strftime('%Y/%m/%d')} - {end_d.strftime('%Y/%m/%d')}"

    m = re.match(
        r"^\s*(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})\s*[\-~〜]\s*(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})\s*$",
        period_str,
    )
    if not m:
        return period_str

    from datetime import date
    start_d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    end_d = date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
    if (end_d - start_d).days == 7:
        end_d = end_d - timedelta(days=1)
    return f"{start_d.strftime('%Y/%m/%d')} - {end_d.strftime('%Y/%m/%d')}"


def sanitize_frontend_content(text, filename=""):
    if not text:
        return text
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\r?\n", "", cleaned)
    cleaned = re.sub(r"\r?\n```$", "", cleaned)
    cleaned = inspect_and_redact_text(cleaned, label=filename)
    return cleaned + "\n"


def sync_frontend_assets():
    asset_groups = {
        "index.html": [
            PROJECT_ROOT / "public/index.html",
            PROJECT_ROOT / "index.html",
        ],
        "style.css": [
            PROJECT_ROOT / "public/style.css",
            PROJECT_ROOT / "public/css/style.css",
            PROJECT_ROOT / "style.css",
        ],
        "app.js": [
            PROJECT_ROOT / "public/app.js",
            PROJECT_ROOT / "public/js/app.js",
            PROJECT_ROOT / "app.js",
        ],
    }

    public_targets = {
        "index.html": [PROJECT_ROOT / "public/index.html"],
        "style.css": [PROJECT_ROOT / "public/style.css", PROJECT_ROOT / "public/css/style.css"],
        "app.js": [PROJECT_ROOT / "public/app.js", PROJECT_ROOT / "public/js/app.js"],
    }

    for name, candidates in asset_groups.items():
        existing = [p for p in candidates if p.exists() and p.is_file() and p.stat().st_size > 0]
        if not existing:
            continue
        newest_file = max(existing, key=lambda p: p.stat().st_mtime)
        try:
            raw_content = newest_file.read_text(encoding="utf-8")
            clean_content = sanitize_frontend_content(raw_content, filename=name)
            for target in public_targets[name]:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(clean_content, encoding="utf-8")
            print(f"[SYNC & SECURE] {name} を検証・同期しました (source: {newest_file.relative_to(PROJECT_ROOT)})")
        except Exception as e:
            print(f"[WARN] {name} の同期中に警告: {e}")
            raise


def update_archive_index(archive_id, period_str, publish_date):
    existing = load_json(ARCHIVE_INDEX, default=[])
    if isinstance(existing, dict) and "archives" in existing:
        archive_list = existing["archives"]
        is_wrapped = True
    elif isinstance(existing, list):
        archive_list = existing
        is_wrapped = False
    else:
        archive_list = []
        is_wrapped = False

    new_entry = {
        "id": archive_id,
        "archiveId": archive_id,
        "file": f"{archive_id}.json",
        "period": period_str,
        "publishDate": publish_date,
        "label": f"{publish_date} 公開 ({period_str})",
    }

    updated = False
    for idx, item in enumerate(archive_list):
        if isinstance(item, dict):
            item_id = item.get("archiveId") or item.get("id") or item.get("publishDate")
            if item_id == archive_id or item.get("file") == f"{archive_id}.json":
                archive_list[idx] = new_entry
                updated = True
                break

    if not updated:
        archive_list.insert(0, new_entry)

    archive_list.sort(
        key=lambda x: (x.get("archiveId") or x.get("publishDate") or x.get("id") or "")
        if isinstance(x, dict)
        else str(x),
        reverse=True,
    )

    payload = {"archives": archive_list} if is_wrapped else archive_list
    save_json(ARCHIVE_INDEX, payload)
    save_json(PROJECT_ROOT / "public/data/archive_index.json", payload)


def main():
    print("=== 週刊VOCALOID複合ランキング 本番公開処理開始 ===")

    sync_frontend_assets()

    draft_candidates = [
        DRAFT_FILE,
        PROJECT_ROOT / "data/weekly_draft.json",
        PROJECT_ROOT / "data/drafts/weekly_draft.json",
        BACKUP_DRAFT_FILE,
    ]
    draft_data = None
    used_draft_path = DRAFT_FILE
    for cand in draft_candidates:
        loaded = load_json(cand)
        if isinstance(loaded, dict) and (loaded.get("songs") or loaded.get("ranking")):
            draft_data = loaded
            used_draft_path = cand
            break

    if not isinstance(draft_data, dict):
        raise RuntimeError("有効な weekly_draft.json が見つかりません。先に build_draft.py を実行してください。")

    now_dt = datetime.now(JST)
    publish_date = draft_data.get("publishDate") or now_dt.strftime("%Y-%m-%d")
    archive_id = draft_data.get("archiveId") or publish_date
    period_str = normalize_period_str(draft_data.get("period"), now_dt)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")

    songs = draft_data.get("ranking") or draft_data.get("songs") or []
    draft_data["songs"] = songs
    draft_data["ranking"] = songs
    draft_data["publishDate"] = publish_date
    draft_data["archiveId"] = archive_id
    draft_data["period"] = period_str
    draft_data["updated_at"] = draft_data.get("updated_at") or now_str
    draft_data["published_at"] = now_str

    save_json(used_draft_path, draft_data)
    save_json(PUBLIC_LATEST, draft_data)
    save_json(PROJECT_ROOT / "data/latest_ranking.json", draft_data)

    archive_file = ARCHIVE_DIR / f"{archive_id}.json"
    save_json(archive_file, draft_data)
    update_archive_index(archive_id, period_str, publish_date)

    print(f"[OK] セキュリティ検査を通過し、最新ランキングを公開しました: {PUBLIC_LATEST}")


if __name__ == "__main__":
    main()