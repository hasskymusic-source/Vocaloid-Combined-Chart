import os
import re
import sys
import json
import glob
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    import config
except ImportError:
    config = None

JST = timezone(timedelta(hours=9))

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent if BASE_DIR.name in ("backend", "scripts", "src") else BASE_DIR


def resolve_config_path(attr_names, default_rel_path):
    if config:
        for name in attr_names:
            if hasattr(config, name):
                val = getattr(config, name)
                if val:
                    return Path(val)
    return PROJECT_ROOT / default_rel_path


DRAFT_FILE = resolve_config_path(["DRAFT_FILE", "WEEKLY_DRAFT_FILE"], "data/drafts/weekly_draft.json")
BACKUP_DRAFT_FILE = resolve_config_path(["BACKUP_DRAFT_FILE", "WEEKLY_DRAFT_BACKUP_FILE"], "data/drafts/weekly_draft.backup.json")
PUBLIC_LATEST = resolve_config_path(["PUBLIC_LATEST", "LATEST_RANKING_FILE"], "public/data/latest_ranking.json")
ARCHIVE_DIR = resolve_config_path(["ARCHIVE_DIR", "ARCHIVES_DIR"], "public/data/archives")
ARCHIVE_INDEX = resolve_config_path(["ARCHIVE_INDEX"], "public/data/archives/archive_index.json")

ARTICLES_MASTER_FILE = resolve_config_path(["ARTICLES_MASTER_FILE"], "data/articles/articles_master.json")
PUBLIC_ARTICLES_FILE = resolve_config_path(["PUBLIC_ARTICLES_FILE"], "public/data/articles.json")

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

# 水曜13:00のアクセス集中をCloudflareエッジで高速吸収するキャッシュ＆セキュリティヘッダー定義
CLOUDFLARE_HEADERS_CONTENT = """/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin

/index.html
  Cache-Control: public, max-age=0, s-maxage=60, stale-while-revalidate=86400

/app.js
  Cache-Control: public, max-age=60, s-maxage=300, stale-while-revalidate=86400

/js/app.js
  Cache-Control: public, max-age=60, s-maxage=300, stale-while-revalidate=86400

/style.css
  Cache-Control: public, max-age=60, s-maxage=300, stale-while-revalidate=86400

/css/style.css
  Cache-Control: public, max-age=60, s-maxage=300, stale-while-revalidate=86400

/data/latest_ranking.json
  Cache-Control: public, max-age=30, s-maxage=60, stale-while-revalidate=86400

/public/data/latest_ranking.json
  Cache-Control: public, max-age=30, s-maxage=60, stale-while-revalidate=86400

/data/articles.json
  Cache-Control: public, max-age=30, s-maxage=60, stale-while-revalidate=86400

/public/data/articles.json
  Cache-Control: public, max-age=30, s-maxage=60, stale-while-revalidate=86400

/data/archive_index.json
  Cache-Control: public, max-age=60, s-maxage=120, stale-while-revalidate=86400

/data/archives/archive_index.json
  Cache-Control: public, max-age=60, s-maxage=120, stale-while-revalidate=86400

/data/archives/*
  Cache-Control: public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800
"""


def inspect_and_redact_text(text, label="data"):
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


def get_release_datetime_jst(chart_data: dict) -> datetime:
    if not isinstance(chart_data, dict):
        return datetime.min.replace(tzinfo=JST)

    pub_at_str = chart_data.get("publishAt")
    if pub_at_str and isinstance(pub_at_str, str):
        try:
            cleaned = pub_at_str.strip()
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
            return dt.astimezone(JST)
        except Exception:
            pass

    pub_date_str = chart_data.get("publishDate") or chart_data.get("archiveId") or ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(pub_date_str).strip())
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 13, 0, 0, tzinfo=JST)

    return datetime.min.replace(tzinfo=JST)


def is_chart_released(chart_data: dict, now_dt: datetime = None) -> bool:
    if now_dt is None:
        now_dt = datetime.now(JST)
    release_dt = get_release_datetime_jst(chart_data)
    return now_dt >= release_dt


def is_article_released(article: dict, now_dt: datetime = None) -> bool:
    """
    記事・コラムの公開判定：
    - status が 'draft'（下書き）の場合は非公開
    - publishAt（予約公開日時）が設定されており、現在時刻がまだ到達していない場合は非公開
    """
    if not isinstance(article, dict):
        return False
    status = str(article.get("status", "published")).lower()
    if status == "draft":
        return False

    if now_dt is None:
        now_dt = datetime.now(JST)

    pub_at_str = article.get("publishAt") or ""
    if pub_at_str and isinstance(pub_at_str, str):
        try:
            cleaned = pub_at_str.strip()
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
            else:
                dt = dt.astimezone(JST)
            if now_dt < dt:
                return False
        except Exception:
            pass

    return True


def sync_published_articles(now_dt: datetime = None):
    """
    記事・コラム執筆スタジオで保存されたマスターデータ(data/articles/articles_master.json)から、
    公開中かつ解禁日時到達済みの記事のみをフィルタリングし、本番公開用の articles.json に書き出す。
    """
    if now_dt is None:
        now_dt = datetime.now(JST)

    master_data = load_json(ARTICLES_MASTER_FILE, default={"articles": [], "speakers": []})
    raw_articles = (
        master_data.get("articles", [])
        if isinstance(master_data, dict)
        else (master_data if isinstance(master_data, list) else [])
    )

    published_list = [a for a in raw_articles if is_article_released(a, now_dt)]

    # ピックアップ(featured)優先 ＋ 公開日降順でソート
    published_list.sort(
        key=lambda a: (
            1 if a.get("featured") else 0,
            str(a.get("publishedAt") or a.get("publishAt") or a.get("updatedAt") or ""),
        ),
        reverse=True,
    )

    payload = {
        "updatedAt": now_dt.strftime("%Y-%m-%d %H:%M"),
        "articles": published_list,
    }

    save_json(PUBLIC_ARTICLES_FILE, payload)
    save_json(PROJECT_ROOT / "data/articles.json", payload)
    print(f"[SYNC & SECURE] 記事・コラムデータを公開同期しました (公開中: {len(published_list)} 件)")
    return published_list


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

    for headers_target in (PROJECT_ROOT / "_headers", PROJECT_ROOT / "public/_headers"):
        headers_target.parent.mkdir(parents=True, exist_ok=True)
        headers_target.write_text(CLOUDFLARE_HEADERS_CONTENT, encoding="utf-8")
    print("[SYNC & SECURE] Cloudflare エッジキャッシュ設定 (_headers) を更新しました")


def rollback_unreleased_public_files(now_dt: datetime):
    if not ARCHIVE_DIR.exists():
        return

    released_archives = []
    for fpath in glob.glob(str(ARCHIVE_DIR / "*.json")):
        p = Path(fpath)
        if p.name in ("archive_index.json", "index.json"):
            continue
        data = load_json(p)
        if not isinstance(data, dict):
            continue
        if not is_chart_released(data, now_dt):
            print(f"[ROLLBACK] 解禁時刻前のアーカイブを本番公開フォルダから退避・削除しました: {p.name}")
            try:
                p.unlink()
            except Exception:
                pass
        else:
            aid = data.get("archiveId") or data.get("publishDate") or p.stem
            released_archives.append((str(aid), data))

    for idx_path in (ARCHIVE_INDEX, PROJECT_ROOT / "public/data/archive_index.json", PROJECT_ROOT / "data/archive_index.json"):
        if not idx_path.exists():
            continue
        idx_data = load_json(idx_path, default=[])
        is_wrapped = isinstance(idx_data, dict) and "archives" in idx_data
        raw_list = idx_data.get("archives", []) if is_wrapped else (idx_data if isinstance(idx_data, list) else [])

        filtered_list = []
        for entry in raw_list:
            if isinstance(entry, dict):
                if is_chart_released(entry, now_dt):
                    filtered_list.append(entry)
            elif isinstance(entry, str):
                stem = entry.replace(".json", "")
                fake_dict = {"publishDate": stem}
                if is_chart_released(fake_dict, now_dt):
                    filtered_list.append(entry)

        filtered_list.sort(
            key=lambda x: (x.get("archiveId") or x.get("publishDate") or x.get("id") or "")
            if isinstance(x, dict)
            else str(x),
            reverse=True,
        )
        save_json(idx_path, {"archives": filtered_list} if is_wrapped else filtered_list)

    current_public = load_json(PUBLIC_LATEST)
    if isinstance(current_public, dict) and not is_chart_released(current_public, now_dt):
        if released_archives:
            released_archives.sort(key=lambda x: x[0], reverse=True)
            latest_released_data = released_archives[0][1]
            save_json(PUBLIC_LATEST, latest_released_data)
            save_json(PROJECT_ROOT / "data/latest_ranking.json", latest_released_data)
            print(
                f"[ROLLBACK] latest_ranking.json が未解禁データだったため、"
                f"直前の公開済みランキング ({released_archives[0][0]}) に自動復元しました。"
            )


def update_archive_index(archive_id, period_str, publish_date, publish_at):
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
        "publishAt": publish_at,
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


def main(force_publish: bool = False):
    if "--force" in sys.argv:
        force_publish = True

    print("=== 週刊VOCALOID複合ランキング 公開・予約管理処理開始 ===")

    now_dt = datetime.now(JST)
    sync_frontend_assets()
    sync_published_articles(now_dt)

    draft_candidates = [
        DRAFT_FILE,
        PROJECT_ROOT / "data/drafts/weekly_draft.json",
        PROJECT_ROOT / "data/weekly_draft.json",
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
        print("[INFO] weekly_draft.json が見つからないため、記事・アセット同期のみ完了しました。")
        return False

    publish_date = draft_data.get("publishDate") or now_dt.strftime("%Y-%m-%d")
    archive_id = draft_data.get("archiveId") or publish_date
    publish_at = draft_data.get("publishAt") or f"{publish_date}T13:00:00+09:00"
    period_str = normalize_period_str(draft_data.get("period"), now_dt)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")

    songs = draft_data.get("ranking") or draft_data.get("songs") or []
    for idx, s in enumerate(songs, start=1):
        if isinstance(s, dict):
            if not s.get("rank"):
                s["rank"] = idx
            if not isinstance(s.get("chart_in_count"), int) or s.get("chart_in_count", 0) < 1:
                s["chart_in_count"] = 1

    draft_data["songs"] = songs
    draft_data["ranking"] = songs
    draft_data["publishDate"] = publish_date
    draft_data["publishAt"] = publish_at
    draft_data["archiveId"] = archive_id
    draft_data["period"] = period_str
    draft_data["updated_at"] = draft_data.get("updated_at") or now_str

    save_json(used_draft_path, draft_data)
    if DRAFT_FILE.resolve() != used_draft_path.resolve():
        save_json(DRAFT_FILE, draft_data)
    alt_draft = PROJECT_ROOT / "data" / "weekly_draft.json"
    if alt_draft.resolve() != DRAFT_FILE.resolve():
        save_json(alt_draft, draft_data)

    release_dt = get_release_datetime_jst(draft_data)

    if not force_publish and now_dt < release_dt:
        rollback_unreleased_public_files(now_dt)
        print(
            f"[SCHEDULED / 予約待機中] 解禁日時 ({release_dt.strftime('%Y-%m-%d %H:%M JST')}) より前のため、"
            f"本番サイトの表示は前週のまま維持し、今週のランキング・執筆原稿を予約保存しました。"
        )
        return False

    draft_data["published_at"] = now_str
    save_json(PUBLIC_LATEST, draft_data)
    save_json(PROJECT_ROOT / "data/latest_ranking.json", draft_data)

    archive_file = ARCHIVE_DIR / f"{archive_id}.json"
    save_json(archive_file, draft_data)
    update_archive_index(archive_id, period_str, publish_date, publish_at)

    print(f"[OK] 解禁日時到達を確認し、最新ランキングを本番サイトへ公開しました: {PUBLIC_LATEST}")
    return True


if __name__ == "__main__":
    main()