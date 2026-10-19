import os
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


MASTER_FILE = resolve_config_path(["MASTER_FILE", "SONGS_MASTER_FILE"], "data/master/songs_master.json")
SNAPSHOTS_DIR = resolve_config_path(["SNAPSHOTS_DIR", "SNAPSHOT_DIR"], "data/snapshots")
LATEST_SNAPSHOT = resolve_config_path(["LATEST_SNAPSHOT"], "data/snapshots/latest_monday.json")
PREV_SNAPSHOT = resolve_config_path(["PREV_SNAPSHOT"], "data/snapshots/prev_monday.json")
DRAFT_FILE = resolve_config_path(["DRAFT_FILE", "WEEKLY_DRAFT_FILE"], "data/drafts/weekly_draft.json")
BACKUP_DRAFT_FILE = resolve_config_path(["BACKUP_DRAFT_FILE", "WEEKLY_DRAFT_BACKUP_FILE"], "data/drafts/weekly_draft.backup.json")
PUBLIC_LATEST = resolve_config_path(["PUBLIC_LATEST", "LATEST_RANKING_FILE"], "public/data/latest_ranking.json")
ARCHIVE_DIR = resolve_config_path(["ARCHIVE_DIR", "ARCHIVES_DIR"], "public/data/archives")
ARCHIVE_INDEX = resolve_config_path(["ARCHIVE_INDEX"], "public/data/archives/archive_index.json")

DEFAULT_WEIGHTS = {
    "yt_views": 1,
    "yt_likes": 50,
    "yt_comments": 100,
    "nc_views": 5,
    "nc_mylist": 100,
    "nc_mylists": 100,
    "nc_comments": 10,
}
WEIGHTS = getattr(config, "WEIGHTS", DEFAULT_WEIGHTS) if config else DEFAULT_WEIGHTS
TOP_N = getattr(config, "TOP_N", 20) if config else 20

# 新譜として初週の累計値算入を認める最大経過日数（集計期間7日＋タイムゾーン・先行公開バッファ3日＝10日）
MAX_NEW_SONG_AGE_DAYS = 10.0


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


def extract_songs_list(data):
    if not data:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("songs", "ranking", "metrics", "items", "data"):
            if key in data and isinstance(data[key], list):
                return [item for item in data[key] if isinstance(item, dict)]
        vals = list(data.values())
        if vals and all(isinstance(v, dict) for v in vals):
            return vals
    return []


def get_song_keys(song_obj):
    if not isinstance(song_obj, dict):
        return set()
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


def parse_iso_datetime(dt_str):
    if not dt_str or not isinstance(dt_str, str):
        return None
    cleaned = dt_str.strip()
    if not cleaned:
        return None
    try:
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt.astimezone(JST)
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(cleaned[:19], fmt).replace(tzinfo=JST)
            except Exception:
                continue
    return None


def resolve_earliest_published_dt(*dict_objs):
    """
    複数の辞書（song, cur_m, prev_m）に含まれる published_at / yt_published_at / nc_published_at から
    最も古い（本来の初出）公開日時を取得する。
    これにより、10年前のニコ動楽曲が最近YouTubeにアップされた場合でも旧譜として正確に判定できる。
    """
    candidates = []
    for d in dict_objs:
        if not isinstance(d, dict):
            continue
        for field in ("published_at", "yt_published_at", "nc_published_at", "first_retrieve", "startTime"):
            val = d.get(field)
            if val:
                dt = parse_iso_datetime(str(val))
                if dt:
                    candidates.append(dt)
    if not candidates:
        return None
    return min(candidates)


def resolve_platform_published_dt(platform_prefix, *dict_objs):
    """特定のプラットフォーム（yt または nc）の公開日時を取得し、なければ全体の最古公開日時を返す"""
    specific_field = f"{platform_prefix}_published_at"
    for d in dict_objs:
        if isinstance(d, dict) and d.get(specific_field):
            dt = parse_iso_datetime(str(d.get(specific_field)))
            if dt:
                return dt
    return resolve_earliest_published_dt(*dict_objs)


def compute_new_release_factor(pub_dt, ref_dt):
    """
    【厳格化された新譜判定ロジック】
    前週スナップショットにデータが存在しない楽曲について：
    - 公開日時が不明（None）の場合：0.0（旧譜の累計5%誤算入を完全防止）
    - 公開から MAX_NEW_SONG_AGE_DAYS（10日）を超えている旧譜の場合：0.0（今週はベースライン記録のみ、来週から実測差分で集計）
    - 公開から7日以内の新譜の場合：1.0（期間内の純増＝現在の累計値）
    - 公開から7日〜10日の新譜の場合：7日分相当への日割り比率（7.0 / 経過日数）
    """
    if pub_dt is None or ref_dt is None:
        return 0.0

    age_days = (ref_dt - pub_dt).total_seconds() / 86400.0
    if age_days < -1.0:
        return 1.0
    if age_days > MAX_NEW_SONG_AGE_DAYS:
        return 0.0
    if age_days <= 7.0:
        return 1.0
    return round(7.0 / age_days, 4)


def compute_chart_dates(now_dt=None):
    """
    今週の月曜日を基準として、直前の月曜日〜日曜日（7日間）を集計期間として算出する。
    さらに、何度再実行しても計算結果が変わらないよう、基準時刻（その週の月曜00:00 JST）も返す。
    """
    if now_dt is None:
        now_dt = datetime.now(JST)
    today = now_dt.date()
    this_monday = today - timedelta(days=today.weekday())
    start_date = this_monday - timedelta(days=7)
    end_date = this_monday - timedelta(days=1)
    period_str = f"{start_date.strftime('%Y/%m/%d')} - {end_date.strftime('%Y/%m/%d')}"

    wed_date = this_monday + timedelta(days=2)
    publish_date = wed_date.strftime("%Y-%m-%d")
    archive_id = wed_date.strftime("%Y-%m-%d")
    reference_dt = datetime(this_monday.year, this_monday.month, this_monday.day, 0, 0, 0, tzinfo=JST)
    return period_str, publish_date, archive_id, reference_dt


def extract_metrics_dict(snapshot_data):
    items = extract_songs_list(snapshot_data)
    result = {}
    for v in items:
        for sk in get_song_keys(v):
            result[sk] = v
    return result


def get_two_latest_snapshots():
    latest_data = load_json(LATEST_SNAPSHOT)
    prev_data = load_json(PREV_SNAPSHOT)

    if latest_data is not None:
        return latest_data, prev_data if prev_data is not None else []

    if not SNAPSHOTS_DIR.exists():
        return [], []

    files = sorted(
        [Path(p) for p in glob.glob(str(SNAPSHOTS_DIR / "*.json"))],
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        return [], []
    latest_f = files[-1]
    prev_f = files[-2] if len(files) >= 2 else None
    return load_json(latest_f, []), load_json(prev_f, []) if prev_f else []


def collect_past_charts(exclude_archive_id=None, exclude_period=None):
    candidate_dirs = [
        ARCHIVE_DIR,
        PROJECT_ROOT / "public/data/archives",
        PROJECT_ROOT / "data/archives",
    ]
    chart_files = []
    for d in candidate_dirs:
        if d.exists():
            chart_files.extend(glob.glob(str(d / "*.json")))

    if PUBLIC_LATEST.exists():
        chart_files.append(str(PUBLIC_LATEST))

    charts_by_key = {}
    for fpath in chart_files:
        fname = os.path.basename(fpath)
        if fname in ("archive_index.json", "index.json"):
            continue
        data = load_json(fpath)
        if not isinstance(data, dict):
            continue
        songs = extract_songs_list(data)
        if not songs:
            continue

        aid = data.get("archiveId") or data.get("chart_id") or data.get("publishDate")
        prd = data.get("period")
        key = aid or prd or os.path.splitext(fname)[0]

        if exclude_archive_id and aid == exclude_archive_id:
            continue
        if exclude_period and prd == exclude_period:
            continue

        charts_by_key[key] = data

    sorted_keys = sorted(charts_by_key.keys())
    return [charts_by_key[k] for k in sorted_keys]


def build_historical_stats(past_charts):
    appearance_counts = {}
    prev_chart_map = {}

    for chart in past_charts:
        ranking_list = extract_songs_list(chart)
        for item in ranking_list[:TOP_N]:
            for k in get_song_keys(item):
                appearance_counts[k] = appearance_counts.get(k, 0) + 1

    if past_charts:
        last_chart = past_charts[-1]
        for idx, item in enumerate(extract_songs_list(last_chart)[:TOP_N], start=1):
            info = {
                "prev_rank": item.get("rank", idx),
                "prev_total_pt": item.get("total_pt", item.get("total_points", 0)),
                "prev_chart_in_count": item.get("chart_in_count", 0),
            }
            for k in get_song_keys(item):
                prev_chart_map[k] = info

    return appearance_counts, prev_chart_map


def preserve_existing_commentary():
    saved_song_comments = {}
    saved_meta = {}

    candidate_files = [
        BACKUP_DRAFT_FILE,
        DRAFT_FILE,
        PROJECT_ROOT / "data/drafts/weekly_draft.backup.json",
        PROJECT_ROOT / "data/drafts/weekly_draft.json",
        PROJECT_ROOT / "data/weekly_draft.backup.json",
        PROJECT_ROOT / "data/weekly_draft.json",
    ]

    for path in candidate_files:
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        for meta_key in ("weeklySummary", "overall_commentary", "trend_analysis", "editor_note"):
            val = data.get(meta_key)
            if val and str(val).strip():
                saved_meta[meta_key] = val

        for item in extract_songs_list(data):
            comment = item.get("commentary") or item.get("comment")
            if comment and str(comment).strip():
                for k in get_song_keys(item):
                    saved_song_comments[k] = comment

    return saved_song_comments, saved_meta


def get_nc_mylist_value(metrics_dict):
    if not isinstance(metrics_dict, dict):
        return 0
    val = metrics_dict.get("nc_mylist")
    if val is None:
        val = metrics_dict.get("nc_mylists", 0)
    return int(val or 0)


def calculate_song_points(song, current_metrics, prev_metrics, reference_dt):
    cur_m = current_metrics if isinstance(current_metrics, dict) and current_metrics else song
    has_prev = isinstance(prev_metrics, dict) and bool(prev_metrics)

    earliest_pub_dt = resolve_earliest_published_dt(cur_m, song, prev_metrics if has_prev else {})
    yt_pub_dt = resolve_platform_published_dt("yt", cur_m, song, prev_metrics if has_prev else {})
    nc_pub_dt = resolve_platform_published_dt("nc", cur_m, song, prev_metrics if has_prev else {})

    # もしニコ動で10年前に公開された曲が最近YouTubeに転載された場合など、
    # 楽曲自体の初出（earliest_pub_dt）が旧譜であれば旧譜として扱う
    effective_yt_pub_dt = min(filter(None, [earliest_pub_dt, yt_pub_dt]), default=None)
    effective_nc_pub_dt = min(filter(None, [earliest_pub_dt, nc_pub_dt]), default=None)

    cur_vals = {
        "yt_views": int(cur_m.get("yt_views", 0) or 0),
        "yt_likes": int(cur_m.get("yt_likes", 0) or 0),
        "yt_comments": int(cur_m.get("yt_comments", 0) or 0),
        "nc_views": int(cur_m.get("nc_views", 0) or 0),
        "nc_mylist": get_nc_mylist_value(cur_m),
        "nc_comments": int(cur_m.get("nc_comments", 0) or 0),
    }

    raw_gains = {}
    if has_prev:
        prv_vals = {
            "yt_views": int(prev_metrics.get("yt_views", 0) or 0),
            "yt_likes": int(prev_metrics.get("yt_likes", 0) or 0),
            "yt_comments": int(prev_metrics.get("yt_comments", 0) or 0),
            "nc_views": int(prev_metrics.get("nc_views", 0) or 0),
            "nc_mylist": get_nc_mylist_value(prev_metrics),
            "nc_comments": int(prev_metrics.get("nc_comments", 0) or 0),
        }

        yt_newly_linked = prv_vals["yt_views"] == 0 and cur_vals["yt_views"] > 0
        nc_newly_linked = prv_vals["nc_views"] == 0 and cur_vals["nc_views"] > 0

        yt_new_factor = compute_new_release_factor(effective_yt_pub_dt, reference_dt)
        nc_new_factor = compute_new_release_factor(effective_nc_pub_dt, reference_dt)

        for mk in ("yt_views", "yt_likes", "yt_comments"):
            if yt_newly_linked:
                # 先週YouTubeデータが0で今週突然入った場合、本物の新曲（10日以内）のみ計上し、
                # 旧譜の後付けID紐付けによる累計混入は 0（次週から実測集計）とする
                raw_gains[mk] = int(round(cur_vals[mk] * yt_new_factor))
            else:
                raw_gains[mk] = max(0, cur_vals[mk] - prv_vals[mk])

        for mk in ("nc_views", "nc_mylist", "nc_comments"):
            if nc_newly_linked:
                raw_gains[mk] = int(round(cur_vals[mk] * nc_new_factor))
            else:
                raw_gains[mk] = max(0, cur_vals[mk] - prv_vals[mk])
    else:
        # 前週のスナップショット自体に存在しない新規登録曲の場合：
        # 集計期間内（10日以内）に公開された新譜のみ計上し、
        # 『チュルリラ・チュルリラ・ダッダッダ！』のような過去曲は 0 として除外する
        yt_new_factor = compute_new_release_factor(effective_yt_pub_dt, reference_dt)
        nc_new_factor = compute_new_release_factor(effective_nc_pub_dt, reference_dt)

        for mk in ("yt_views", "yt_likes", "yt_comments"):
            raw_gains[mk] = int(round(max(0, cur_vals[mk]) * yt_new_factor))
        for mk in ("nc_views", "nc_mylist", "nc_comments"):
            raw_gains[mk] = int(round(max(0, cur_vals[mk]) * nc_new_factor))

    raw_gains["nc_mylists"] = raw_gains["nc_mylist"]

    w_yt_views = WEIGHTS.get("yt_views", 1)
    w_yt_likes = WEIGHTS.get("yt_likes", 50)
    w_yt_comments = WEIGHTS.get("yt_comments", 100)
    w_nc_views = WEIGHTS.get("nc_views", 5)
    w_nc_mylist = WEIGHTS.get("nc_mylist", WEIGHTS.get("nc_mylists", 100))
    w_nc_comments = WEIGHTS.get("nc_comments", 10)

    pts_breakdown = {
        "yt_views": raw_gains["yt_views"] * w_yt_views,
        "yt_likes": raw_gains["yt_likes"] * w_yt_likes,
        "yt_comments": raw_gains["yt_comments"] * w_yt_comments,
        "nc_views": raw_gains["nc_views"] * w_nc_views,
        "nc_mylist": raw_gains["nc_mylist"] * w_nc_mylist,
        "nc_mylists": raw_gains["nc_mylist"] * w_nc_mylist,
        "nc_comments": raw_gains["nc_comments"] * w_nc_comments,
    }

    yt_total = pts_breakdown["yt_views"] + pts_breakdown["yt_likes"] + pts_breakdown["yt_comments"]
    nc_total = pts_breakdown["nc_views"] + pts_breakdown["nc_mylist"] + pts_breakdown["nc_comments"]
    total_pt = yt_total + nc_total

    pts_breakdown["yt_total"] = yt_total
    pts_breakdown["nc_total"] = nc_total

    pub_iso_str = earliest_pub_dt.isoformat() if earliest_pub_dt else ""
    return total_pt, raw_gains, pts_breakdown, pub_iso_str


def main():
    print("=== 週刊VOCALOID複合ランキング ドラフト生成開始 ===")
    now_dt = datetime.now(JST)
    period_str, publish_date, archive_id, reference_dt = compute_chart_dates(now_dt)

    existing_draft = load_json(DRAFT_FILE)
    if existing_draft:
        save_json(BACKUP_DRAFT_FILE, existing_draft)
    saved_comments, saved_meta = preserve_existing_commentary()

    past_charts = collect_past_charts(exclude_archive_id=archive_id, exclude_period=period_str)
    appearance_counts, prev_chart_map = build_historical_stats(past_charts)

    latest_snap, prev_snap = get_two_latest_snapshots()
    cur_map = extract_metrics_dict(latest_snap)
    prv_map = extract_metrics_dict(prev_snap)

    # スナップショット内に記録された日時があれば、その日時を基準時刻として固定（完全な決定論的計算）
    snap_list = extract_songs_list(latest_snap)
    if snap_list and snap_list[0].get("updated_at"):
        parsed_snap_dt = parse_iso_datetime(snap_list[0].get("updated_at"))
        if parsed_snap_dt:
            reference_dt = parsed_snap_dt

    master_data = load_json(MASTER_FILE)
    songs_list = extract_songs_list(master_data)
    if not songs_list:
        songs_list = snap_list
    if not songs_list and isinstance(existing_draft, dict):
        songs_list = extract_songs_list(existing_draft)

    # マスターと最新スナップショットの双方から漏れなく候補を統合
    combined_candidates = list(songs_list) + [s for s in snap_list if isinstance(s, dict)]

    scored_songs = []
    seen_song_keys = set()
    skipped_unmeasured_old_songs = 0

    for song in combined_candidates:
        if not isinstance(song, dict):
            continue

        keys = get_song_keys(song)
        if not keys or (keys & seen_song_keys):
            continue

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

        if not cur_m and not song.get("yt_views") and not song.get("nc_views"):
            continue

        total_pt, raw_gains, pts_breakdown, resolved_pub_str = calculate_song_points(
            song, cur_m, prv_m, reference_dt
        )
        if total_pt <= 0:
            if not prv_m:
                skipped_unmeasured_old_songs += 1
            continue

        seen_song_keys.update(keys)

        past_count = 0
        prev_info = None
        for k in keys:
            if k in appearance_counts:
                past_count = max(past_count, appearance_counts[k])
            if k in prev_chart_map and prev_info is None:
                prev_info = prev_chart_map[k]

        prev_rank = prev_info["prev_rank"] if prev_info else None
        prev_total_pt = prev_info["prev_total_pt"] if prev_info else None

        pt_ratio = None
        if prev_total_pt is not None and prev_total_pt > 0:
            pt_ratio = round((total_pt / prev_total_pt) * 100)

        commentary = song.get("commentary") or song.get("comment") or ""
        for k in keys:
            if k in saved_comments:
                commentary = saved_comments[k]
                break

        yt_id = (
            song.get("youtube_id")
            or song.get("yt_id")
            or cur_m.get("youtube_id")
            or cur_m.get("yt_id")
        )
        nc_id = (
            song.get("niconico_id")
            or song.get("nc_id")
            or cur_m.get("niconico_id")
            or cur_m.get("nc_id")
        )
        primary_id = song.get("song_id") or song.get("id") or (f"song_{nc_id}" if nc_id else f"song_{yt_id}")

        song_entry = {
            "id": primary_id,
            "song_id": primary_id,
            "title": cur_m.get("title") or song.get("title") or "不明な楽曲",
            "producer": cur_m.get("producer") or song.get("producer") or "不明",
            "vocal": cur_m.get("vocal") or song.get("vocal") or "VOCALOID",
            "youtube_id": yt_id,
            "niconico_id": nc_id,
            "thumbnail": (
                song.get("thumbnail")
                or cur_m.get("thumbnail")
                or (f"https://i.ytimg.com/vi/{yt_id}/mqdefault.jpg" if yt_id else "")
            ),
            "published_at": resolved_pub_str or song.get("published_at") or cur_m.get("published_at") or "",
            "total_pt": total_pt,
            "yt_total_pt": pts_breakdown["yt_total"],
            "nc_total_pt": pts_breakdown["nc_total"],
            "prevRank": prev_rank if prev_rank is not None else "NEW",
            "prev_rank": prev_rank,
            "prev_total_pt": prev_total_pt,
            "pt_ratio": pt_ratio,
            "_past_chart_in_count": past_count,
            "raw": raw_gains,
            "pts": pts_breakdown,
            "commentary": commentary,
        }
        scored_songs.append(song_entry)

    # ポイント降順、同点時は song_id 昇順で完全決定論的にソート
    scored_songs.sort(key=lambda x: (-x["total_pt"], str(x.get("song_id", ""))))
    top_songs = scored_songs[:TOP_N]

    for idx, item in enumerate(top_songs, start=1):
        item["rank"] = idx
        past_c = item.pop("_past_chart_in_count", 0)
        item["chart_in_count"] = past_c + 1

    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
    weekly_summary = (
        saved_meta.get("weeklySummary")
        or saved_meta.get("overall_commentary")
        or (existing_draft.get("weeklySummary", "") if isinstance(existing_draft, dict) else "")
        or (existing_draft.get("overall_commentary", "") if isinstance(existing_draft, dict) else "")
    )
    trend_analysis = (
        saved_meta.get("trend_analysis")
        or (existing_draft.get("trend_analysis", "") if isinstance(existing_draft, dict) else "")
    )

    draft_output = {
        "publishDate": publish_date,
        "archiveId": archive_id,
        "period": period_str,
        "updated_at": now_str,
        "weeklySummary": weekly_summary,
        "overall_commentary": weekly_summary,
        "trend_analysis": trend_analysis,
        "weights": WEIGHTS,
        "songs": top_songs,
        "ranking": top_songs,
    }

    save_json(DRAFT_FILE, draft_output)
    save_json(BACKUP_DRAFT_FILE, draft_output)

    # data/weekly_draft.json と data/drafts/weekly_draft.json の両方が存在し得る環境向けに同期
    alt_draft = PROJECT_ROOT / "data" / "weekly_draft.json"
    if alt_draft.resolve() != DRAFT_FILE.resolve():
        save_json(alt_draft, draft_output)

    print(
        f"[OK] TOP {len(top_songs)} のドラフトを生成しました: {DRAFT_FILE} "
        f"(集計期間: {period_str} / 前週データなしの旧譜除外: {skipped_unmeasured_old_songs} 曲)"
    )


if __name__ == "__main__":
    main()