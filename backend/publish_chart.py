import json
import shutil
from config import DRAFT_FILE, PUBLIC_LATEST, ARCHIVE_DIR, ARCHIVE_INDEX

def main():
    if not DRAFT_FILE.exists():
        raise FileNotFoundError("weekly_draft.json が見つかりません。")

    with open(DRAFT_FILE, "r", encoding="utf-8") as f:
        draft_data = json.load(f)

    archive_id = draft_data["archiveId"]  # 例: "2026-10-21"

    # 1. 最新ランキング(latest_ranking.json)を上書き
    PUBLIC_LATEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DRAFT_FILE, PUBLIC_LATEST)

    # 2. アーカイブフォルダに日付名で保存
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"{archive_id}.json"
    shutil.copyfile(DRAFT_FILE, archive_path)

    # 3. アーカイブ一覧インデックス(archive_index.json)を更新
    index_list = []
    if ARCHIVE_INDEX.exists():
        with open(ARCHIVE_INDEX, "r", encoding="utf-8") as f:
            index_list = json.load(f)

    new_entry = {
        "archiveId": archive_id,
        "label": f"{archive_id} 公開（集計: {draft_data['period']}）"
    }
    # 重複を防いで先頭に追加
    index_list = [ item for item in index_list if item["archiveId"] != archive_id ]
    index_list.insert(0, new_entry)

    with open(ARCHIVE_INDEX, "w", encoding="utf-8") as f:
        json.dump(index_list, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()