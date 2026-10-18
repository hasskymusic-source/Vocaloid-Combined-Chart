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
    with open(path_obj, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def sanitize_frontend_content(text):
    """
    コピペ時に誤って先頭や末尾に Markdown のコードブロック (```html, ```css, ```javascript 等) が
    混入していた場合でも自動的に除去して正常なコードに修復する
    """
    if not text:
        return text
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\r?\n", "", cleaned)
    cleaned = re.sub(r"\r?\n```$", "", cleaned)
    return cleaned + "\n"


def sync_frontend_assets():
    """
    ルート直下・public直下・public/css・public/js のどこでファイルが編集されても、
    最新（最終更新時刻が最も新しい）ファイルを検出し、すべての参照パスへ自動同期する。
    これにより GitHub Pages での CSS/JS 404 エラーを恒久的に防止する。
    """
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

    public_Targets = {
        "index.html": [PROJECT_ROOT / "public/index.html"],
        "style.css": [PROJECT_ROOT / "public/style.css", PROJECT_ROOT / "public/css/style.css"],
        "app.js": [PROJECT_ROOT / "public/app.js", PROJECT_ROOT / "public/js/app.js"],
    }

    for name, candidates in asset_groups.items():
        existing = [p for p in candidates if p.exists() and p.is_file() and p.stat().st_size > 0]
        if not existing:
            continue
        # 最も新しく編集されたファイルを採用
        newest_file = max(existing, key=lambda p: p.stat().st_mtime)
        try:
            raw_content = newest_file.read_text(encoding="utf-8")
            clean_content = sanitize_frontend_content(raw_content)
            for target in public_Targets[name]:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(clean_content, encoding="utf-8")
            print(f"[SYNC] {name} を最新状態に同期・検証しました (source: {newest_file.relative_to(PROJECT_ROOT)})")
        except Exception as e:
            print(f"[WARN] {name} の同期中に警告: {e}")


def update_archive_index(archive_id, period_str, publish_date):
    """
    archive_index.json を読み込み、今回のアーカイブを追加・更新する
    """
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

    # 新しい順（降順）にソート
    archive_list.sort(
        key=lambda x: (x.get("archiveId") or x.get("publishDate") or x.get("id") or "")
        if isinstance(x, dict)
        else str(x),
        reverse=True,
    )

    payload = {"archives": archive_list} if is_wrapped else archive_list
    save_json(ARCHIVE_INDEX, payload)
    # フォールバック用パスにも保存
    save_json(PROJECT_ROOT / "public/data/archive_index.json", payload)


def main():
    print("=== 週刊VOCALOID複合ランキング 本番公開処理開始 ===")

    # 1. フロントエンドファイル（HTML/CSS/JS）の自動同期＆構文サニタイズ
    sync_frontend_assets()

    # 2. ドラフトデータの読み込み（複数候補パスに対応）
    draft_candidates = [
        DRAFT_FILE,
        PROJECT_ROOT / "data/weekly_draft.json",
        PROJECT_ROOT / "data/drafts/weekly_draft.json",
        BACKUP_DRAFT_FILE,
    ]
    draft_data = None
    for cand in draft_candidates:
        draft_data = load_json(cand)
        if isinstance(draft_data, dict) and (draft_data.get("songs") or draft_data.get("ranking")):
            break

    if not isinstance(draft_data, dict):
        raise RuntimeError("有効な weekly_draft.json が見つかりません。先に build_draft.py を実行してください。")

    now_dt = datetime.now(JST)
    publish_date = draft_data.get("publishDate") or now_dt.strftime("%Y-%m-%d")
    archive_id = draft_data.get("archiveId") or publish_date
    period_str = draft_data.get("period") or publish_date

    songs = draft_data.get("ranking") or draft_data.get("songs") or []
    draft_data["songs"] = songs
    draft_data["ranking"] = songs
    draft_data["publishDate"] = publish_date
    draft_data["archiveId"] = archive_id
    draft_data["period"] = period_str
    draft_data["published_at"] = now_dt.strftime("%Y-%m-%d %H:%M")

    # 3. 最新ランキング JSON の保存
    save_json(PUBLIC_LATEST, draft_data)
    save_json(PROJECT_ROOT / "data/latest_ranking.json", draft_data)

    # 4. アーカイブ JSON の保存とインデックス更新
    archive_file = ARCHIVE_DIR / f"{archive_id}.json"
    save_json(archive_file, draft_data)
    update_archive_index(archive_id, period_str, publish_date)

    print(f"[OK] 最新ランキングを公開しました: {PUBLIC_LATEST}")
    print(f"[OK] アーカイブを保存しました: {archive_file}")


if __name__ == "__main__":
    main()