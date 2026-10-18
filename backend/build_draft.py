import os
import json
import glob
from datetime import datetime, timezone, timedelta

try:
    import config
except ImportError:
    config = None

JST = timezone(timedelta(hours=9))

# ディレクトリ・ファイルパス設定（config.py がある場合は優先）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..")) if os.path.basename(BASE_DIR) == "backend" else BASE_DIR

def get_path(attr_name, default_rel_path):
    if config and hasattr(config, attr_name):
        return getattr(config, attr_name)
    return os.path.join(PROJECT_ROOT, default_rel_path)

SONGS_MASTER_FILE = get_path("SONGS_MASTER_FILE", "data/master/songs_master.json")
SNAPSHOTS_DIR = get_path("SNAPSHOTS_DIR", "data/snapshots")
DRAFTS_DIR = get_path("DRAFTS_DIR", "data/drafts")
WEEKLY_DRAFT_FILE = get_path("WEEKLY_DRAFT_FILE", "data/drafts/weekly_draft.json")
WEEKLY_DRAFT_BACKUP_FILE = get_path("WEEKLY_DRAFT_BACKUP_FILE", "data/drafts/weekly_draft.backup.json")
LATEST_RANKING_FILE = get_path("LATEST_RANKING_FILE", "public/data/latest_ranking.json")
ARCHIVES_DIR = get_path("ARCHIVES_DIR", "public/data/archives")
DATA_ARCHIVES_DIR = os.path.join(PROJECT_ROOT, "data/archives")

# 6指標の重み付け係数
DEFAULT_WEIGHTS = {
    "yt_views": 1,
    "yt_likes": 50,
    "yt_comments": 100,
    "nc_views": 5,
    "nc_mylists": 100,
    "nc_comments": 10,
}
WEIGHTS = getattr(config, "WEIGHTS", DEFAULT_WEIGHTS) if config else DEFAULT_WEIGHTS
TOP_N = getattr(config, "TOP_N", 20) if config else 20


def load_json(filepath, default=None):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to load {filepath}: {e}")
        return default


def save_json(filepath, data):
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_song_keys(song_obj):
    """
    名寄せ・ID統合に対応するため、楽曲を一意に識別するキーセットを返す
    """
    keys = set()
    song_id = song_obj.get("song_id") or song_obj.get("id")
    yt_id = song_obj.get("youtube_id") or song_obj.get("yt_id")
    nc_id = song_obj.get("niconico_id") or song_obj.get("nc_id") or song_obj.get("sm_id")
    if song_id:
        keys.add(f"id:{song_id}")
    if yt_id:
        keys.add(f"yt:{yt_id}")
    if nc_id:
        keys.add(f"nc:{nc_id}")
    return keys


def collect_past_charts(current_period_id=None):
    """
    public/data/archives/, data/archives/, public/data/latest_ranking.json から
    過去の公開済みチャートデータを時系列順（古い順）に収集・重複排除して返す
    """
    chart_files = []
    for d in [ARCHIVES_DIR, DATA_ARCHIVES_DIR]:
        if os.path.exists(d):
            chart_files.extend(glob.glob(os.path.join(d, "*.json")))

    if os.path.exists(LATEST_RANKING_FILE):
        chart_files.append(LATEST_RANKING_FILE)

    charts_by_period = {}
    for fpath in chart_files:
        if os.path.basename(fpath) in ("archive_index.json", "index.json"):
            continue
        data = load_json(fpath)
        if not isinstance(data, dict) or "ranking" not in data:
            continue
        period_key = (
            data.get("chart_id")
            or data.get("period")
            or data.get("published_at")
            or data.get("updated_at")
            or os.path.splitext(os.path.basename(fpath))[0]
        )
        if current_period_id and period_key == current_period_id:
            continue
        charts_by_period[period_key] = data

    sorted_periods = sorted(charts_by_period.keys())
    return [charts_by_period[k] for k in sorted_periods]


def build_historical_stats(past_charts):
    """
    過去チャート群から以下を集計する:
    1. 各識別キーごとの過去TOP20チャートイン回数 (appearances)
    2. 直近（前週）チャートの順位 (prev_rank) と 総合ポイント (prev_total_pt)
    """
    appearance_counts = {}
    prev_chart_map = {}

    for chart in past_charts:
        ranking_list = chart.get("ranking", [])
        for item in ranking_list[:TOP_N]:
            for k in get_song_keys(item):
                appearance_counts[k] = appearance_counts.get(k, 0) + 1

    if past_charts:
        last_chart = past_charts[-1]
        for item in last_chart.get("ranking", []):
            info = {
                "prev_rank": item.get("rank"),
                "prev_total_pt": item.get("total_pt", 0),
                "prev_chart_in_count": item.get("chart_in_count", 0),
            }
            for k in get_song_keys(item):
                prev_chart_map[k] = info

    return appearance_counts, prev_chart_map


def get_two_latest_snapshots():
    """
    スナップショットディレクトリから最新と前回（7日前基準）の2つのスナップショットを取得する
    """
    if not os.path.exists(SNAPSHOTS_DIR):
        return None, None
    files = sorted(glob.glob(os.path.join(SNAPSHOTS_DIR, "*.json")))
    if not files:
        return None, None
    latest_file = files[-1]
    prev_file = files[-2] if len(files) >= 2 else None
    return load_json(latest_file, {}), load_json(prev_file, {}) if prev_file else {}


def preserve_existing_commentary():
    """
    コンフリクト回避・原稿消失防止のため、既存の weekly_draft.json および
    weekly_draft.backup.json から執筆済みの解説文や全体総評を救出する
    """
    saved_song_comments = {}
    saved_meta = {}

    for path in [WEEKLY_DRAFT_BACKUP_FILE, WEEKLY_DRAFT_FILE]:
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        for meta_key in ("overall_commentary", "trend_analysis", "editor_note", "summary"):
            if data.get(meta_key):
                saved_meta[meta_key] = data[meta_key]
        for item in data.get("ranking", []):
            comment = item.get("commentary") or item.get("comment")
            if comment and str(comment).strip():
                for k in get_song_keys(item):
                    saved_song_comments[k] = comment

    return saved_song_comments, saved_meta


def extract_metrics_dict(snapshot_data):
    """
    スナップショットJSONから { key: metrics } 辞書を構築する
    """
    if not snapshot_data:
        return {}
    items = snapshot_data.get("songs", snapshot_data.get("metrics", snapshot_data))
    result = {}
    if isinstance(items, dict):
        for k, v in items.items():
            if isinstance(v, dict):
                result[f"id:{k}"] = v
                for sk in get_song_keys(v):
                    result[sk] = v
    elif isinstance(items, list):
        for v in items:
            if isinstance(v, dict):
                for sk in get_song_keys(v):
                    result[sk] = v
    return result


def calculate_song_points(song, current_metrics, prev_metrics):
    """
    6指標の期間内純増数を算出し、重み付けポイントを計算する
    """
    raw_gains = {}
    pts_breakdown = {}

    metric_keys = [
        "yt_views",
        "yt_likes",
        "yt_comments",
        "nc_views",
        "nc_mylists",
        "nc_comments",
    ]

    # すでに純増数 (raw) が直接入っている場合とスナップショット差分の両方に対応
    raw_source = song.get("raw") if isinstance(song.get("raw"), dict) else None

    for mk in metric_keys:
        if raw_source is not None and mk in raw_source:
            diff = max(0, int(raw_source.get(mk, 0) or 0))
        else:
            cur_val = int(current_metrics.get(mk, song.get(mk, 0)) or 0)
            prv_val = int(prev_metrics.get(mk, 0) or 0) if prev_metrics else 0
            diff = max(0, cur_val - prv_val)

        raw_gains[mk] = diff
        pts_breakdown[mk] = diff * WEIGHTS.get(mk, 1)

    yt_total = pts_breakdown["yt_views"] + pts_breakdown["yt_likes"] + pts_breakdown["yt_comments"]
    nc_total = pts_breakdown["nc_views"] + pts_breakdown["nc_mylists"] + pts_breakdown["nc_comments"]
    total_pt = yt_total + nc_total

    pts_breakdown["yt_total"] = yt_total
    pts_breakdown["nc_total"] = nc_total

    return total_pt, raw_gains, pts_breakdown


def main():
    print("=== 週刊VOCALOID複合ランキング ドラフト生成開始 ===")

    # 1. 既存の解説原稿をバックアップ＆救出
    existing_draft = load_json(WEEKLY_DRAFT_FILE)
    if existing_draft:
        save_json(WEEKLY_DRAFT_BACKUP_FILE, existing_draft)
    saved_comments, saved_meta = preserve_existing_commentary()

    # 2. 過去チャートから「前週ポイント」と「過去チャートイン回数」を集計
    current_period = existing_draft.get("period") if isinstance(existing_draft, dict) else None
    past_charts = collect_past_charts(current_period_id=current_period)
    appearance_counts, prev_chart_map = build_historical_stats(past_charts)

    # 3. 楽曲マスターとスナップショットの読み込み
    master_data = load_json(SONGS_MASTER_FILE)
    latest_snap, prev_snap = get_two_latest_snapshots()
    cur_map = extract_metrics_dict(latest_snap)
    prv_map = extract_metrics_dict(prev_snap)

    songs_list = []
    if isinstance(master_data, dict):
        songs_list = master_data.get("songs", list(master_data.values()))
    elif isinstance(master_data, list):
        songs_list = master_data

    # マスターが空または既存の weekly_draft を再計算する場合のフォールバック
    if not songs_list and isinstance(existing_draft, dict):
        songs_list = existing_draft.get("ranking", [])

    scored_songs = []
    for song in songs_list:
        if not isinstance(song, dict):
            continue

        keys = get_song_keys(song)
        cur_m = {}
        prv_m = {}
        for k in keys:
            if k in cur_map:
                cur_m = cur_map[k]
                break
        for k in keys:
            if k in prv_map:
                prv_m = prv_map[k]
                break

        total_pt, raw_gains, pts_breakdown = calculate_song_points(song, cur_m, prv_m)
        if total_pt <= 0:
            continue

        # 過去のチャートイン回数と前週データの照合
        past_count = 0
        prev_info = None
        for k in keys:
            if k in appearance_counts:
                past_count = max(past_count, appearance_counts[k])
            if k in prev_chart_map and prev_info is None:
                prev_info = prev_chart_map[k]

        # 既存データに prev_rank や prev_total_pt が明示されている場合のフォールバック
        prev_rank = prev_info["prev_rank"] if prev_info else song.get("prev_rank")
        prev_total_pt = prev_info["prev_total_pt"] if prev_info else song.get("prev_total_pt")

        # ポイント前週比率（%）の算出（例: 2,000,000 -> 3,000,000 なら 150）
        pt_ratio = None
        if prev_total_pt is not None and prev_total_pt > 0:
            pt_ratio = round((total_pt / prev_total_pt) * 100)

        # 救出した解説文の復元
        commentary = song.get("commentary", "")
        for k in keys:
            if k in saved_comments:
                commentary = saved_comments[k]
                break

        song_entry = {
            "song_id": song.get("song_id") or song.get("id") or song.get("youtube_id") or song.get("niconico_id"),
            "title": song.get("title", "不明な楽曲"),
            "producer": song.get("producer", "不明"),
            "vocal": song.get("vocal", "VOCALOID"),
            "youtube_id": song.get("youtube_id") or song.get("yt_id"),
            "niconico_id": song.get("niconico_id") or song.get("nc_id"),
            "thumbnail": song.get("thumbnail") or (
                f"https://i.ytimg.com/vi/{song.get('youtube_id')}/mqdefault.jpg"
                if song.get("youtube_id")
                else ""
            ),
            "published_at": song.get("published_at", ""),
            "total_pt": total_pt,
            "prev_rank": prev_rank,
            "prev_total_pt": prev_total_pt,
            "pt_ratio": pt_ratio,
            "_past_chart_in_count": past_count,
            "raw": raw_gains,
            "pts": pts_breakdown,
            "commentary": commentary,
        }
        scored_songs.append(song_entry)

    # 総合ポイント降順でソートして TOP 20 を抽出
    scored_songs.sort(key=lambda x: x["total_pt"], reverse=True)
    top_songs = scored_songs[:TOP_N]

    for idx, item in enumerate(top_songs, start=1):
        item["rank"] = idx
        past_c = item.pop("_past_chart_in_count", 0)
        # 今週TOP20入りした分 (+1) を加算した通算チャートイン回数
        item["chart_in_count"] = past_c + 1

    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    period_str = (
        existing_draft.get("period")
        if isinstance(existing_draft, dict) and existing_draft.get("period")
        else datetime.now(JST).strftime("%Y-%m-%d")
    )

    draft_output = {
        "updated_at": now_str,
        "period": period_str,
        "overall_commentary": saved_meta.get(
            "overall_commentary",
            existing_draft.get("overall_commentary", "") if isinstance(existing_draft, dict) else "",
        ),
        "trend_analysis": saved_meta.get(
            "trend_analysis",
            existing_draft.get("trend_analysis", "") if isinstance(existing_draft, dict) else "",
        ),
        "ranking": top_songs,
    }

    save_json(WEEKLY_DRAFT_FILE, draft_output)
    save_json(WEEKLY_DRAFT_BACKUP_FILE, draft_output)
    print(f"[OK] TOP {len(top_songs)} のドラフトを生成しました: {WEEKLY_DRAFT_FILE}")


if __name__ == "__main__":
    main()