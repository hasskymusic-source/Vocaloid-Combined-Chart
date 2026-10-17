import json
from datetime import datetime, timedelta, timezone
from config import WEIGHTS, PREV_SNAPSHOT, LATEST_SNAPSHOT, DRAFT_FILE, PUBLIC_LATEST

TOP_N = 20
JST = timezone(timedelta(hours=9))

def parse_iso_dt(dt_str: str):
    if not dt_str:
        return None
    try:
        clean_str = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt.astimezone(JST)
    except Exception:
        return None

def compute_chart_window():
    now_jst = datetime.now(JST)
    days_since_sunday = (now_jst.weekday() + 1) % 7
    if days_since_sunday == 0 and now_jst.hour < 23:
        days_since_sunday = 7

    last_sunday_date = (now_jst - timedelta(days=days_since_sunday)).date()
    last_monday_date = last_sunday_date - timedelta(days=6)
    publish_wed_date = last_sunday_date + timedelta(days=3)

    window_start = datetime(
        last_monday_date.year, last_monday_date.month, last_monday_date.day,
        0, 0, 0, tzinfo=JST
    )
    window_end = datetime(
        last_sunday_date.year, last_sunday_date.month, last_sunday_date.day,
        23, 59, 59, tzinfo=JST
    )

    return (
        window_start,
        window_end,
        now_jst,
        f"{publish_wed_date.strftime('%Y-%m-%d')} 13:00",
        publish_wed_date.strftime("%Y-%m-%d"),
        f"{last_monday_date.strftime('%Y-%m-%d')} 〜 {last_sunday_date.strftime('%Y-%m-%d')}"
    )

def calc_window_fraction(pub_dt, window_start, window_end, now_dt) -> tuple:
    """
    指定された7日間ウィンドウ [window_start, window_end] の獲得シェアを算出。
    """
    if pub_dt is None:
        return 0.0, 0.0

    if pub_dt > window_end:
        return 0.0, 0.0

    t_now = max(0.25, (now_dt - pub_dt).total_seconds() / 86400.0)
    t_start = max(0.0, (window_start - pub_dt).total_seconds() / 86400.0)
    t_end = max(0.0, min(t_now, (window_end - pub_dt).total_seconds() / 86400.0))

    if t_end <= t_start:
        return 0.0, 0.0

    alpha_views = 0.52
    alpha_engage = 0.36

    share_views = ((t_end ** alpha_views) - (t_start ** alpha_views)) / (t_now ** alpha_views)
    share_engage = ((t_end ** alpha_engage) - (t_start ** alpha_engage)) / (t_now ** alpha_engage)

    # 公開から2年(730日)以上経過した旧譜カタログは定常減衰係数を適用し、直近1年のバイラル曲・新譜の精度を高める
    if t_now > 730.0:
        share_views *= 0.45
        share_engage *= 0.35

    return min(0.92, max(0.0, share_views)), min(0.92, max(0.0, share_engage))

def calculate_period_metrics(song: dict, window_start, window_end, now_dt) -> dict:
    yt_pub = parse_iso_dt(song.get("yt_published_at"))
    nc_pub = parse_iso_dt(song.get("nc_published_at"))

    yt_sv, yt_se = calc_window_fraction(yt_pub, window_start, window_end, now_dt) if song.get("yt_views", 0) > 0 else (0.0, 0.0)
    nc_sv, nc_se = calc_window_fraction(nc_pub, window_start, window_end, now_dt) if song.get("nc_views", 0) > 0 else (0.0, 0.0)

    return {
        "yt_views": int(song.get("yt_views", 0) * yt_sv),
        "yt_likes": int(song.get("yt_likes", 0) * yt_se),
        "yt_comments": int(song.get("yt_comments", 0) * yt_se),
        "nc_views": int(song.get("nc_views", 0) * nc_sv),
        "nc_mylist": int(song.get("nc_mylist", 0) * nc_se),
        "nc_comments": int(song.get("nc_comments", 0) * nc_se),
    }

def main():
    window_start, window_end, now_dt, publish_date, archive_id, period_str = compute_chart_window()

    with open(LATEST_SNAPSHOT, "r", encoding="utf-8") as f:
        latest_list = json.load(f)

    prev_ranks = {}
    if PUBLIC_LATEST.exists():
        try:
            with open(PUBLIC_LATEST, "r", encoding="utf-8") as f:
                pub_data = json.load(f)
                prev_ranks = {s["song_id"]: s["rank"] for s in pub_data.get("songs", [])}
        except json.JSONDecodeError:
            pass

    ranked_songs = []
    rebuilt_prev_snapshots = []

    for song in latest_list:
        sid = song["song_id"]
        raw_diff = calculate_period_metrics(song, window_start, window_end, now_dt)

        baseline_entry = dict(song)
        for k in WEIGHTS.keys():
            baseline_entry[k] = max(0, song.get(k, 0) - raw_diff[k])
        rebuilt_prev_snapshots.append(baseline_entry)

        pts = {k: raw_diff[k] * WEIGHTS[k] for k in WEIGHTS.keys()}
        yt_total = pts["yt_views"] + pts["yt_likes"] + pts["yt_comments"]
        nc_total = pts["nc_views"] + pts["nc_mylist"] + pts["nc_comments"]
        total_pt = yt_total + nc_total

        # 両サイト必須フィルタを撤廃：YouTube単体の海外ボカロP曲や片側先行の新譜も全てフェアに評価
        if total_pt <= 0:
            continue

        ranked_songs.append({
            "song_id": sid,
            "title": song["title"],
            "producer": song["producer"],
            "vocal": song.get("vocal", "VOCALOID"),
            "youtube_id": song.get("youtube_id", ""),
            "niconico_id": song.get("niconico_id", ""),
            "total_pt": total_pt,
            "yt_total_pt": yt_total,
            "nc_total_pt": nc_total,
            "raw": raw_diff,
            "pts": pts,
            "prevRank": prev_ranks.get(sid, "NEW"),
            "commentary": ""
        })

    with open(PREV_SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(rebuilt_prev_snapshots, f, ensure_ascii=False, indent=2)

    ranked_songs.sort(key=lambda x: x["total_pt"], reverse=True)
    top_songs = ranked_songs[:TOP_N]
    for idx, item in enumerate(top_songs, start=1):
        item["rank"] = idx

    top1 = top_songs[0] if top_songs else {"title": "-", "producer": "-", "total_pt": 0}

    draft_payload = {
        "publishDate": publish_date,
        "archiveId": archive_id,
        "period": period_str,
        "weeklySummary": (
            f"集計期間（{period_str}）の週間VOCALOID複合ランキングTOP 20。"
            f"日本国内のボカロ新譜から韓国・英語圏をはじめとするグローバルボカロPのヒット曲まで、"
            f"YouTubeとニコニコ動画の6指標を横断集計した結果、"
            f"{top1['producer']}「{top1['title']}」が週間 {top1['total_pt']:,} pt で総合1位を獲得した。"
        ),
        "weights": WEIGHTS,
        "songs": top_songs
    }

    DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DRAFT_FILE, "w", encoding="utf-8") as f:
        json.dump(draft_payload, f, ensure_ascii=False, indent=2)

    print(f"グローバル対応 TOP {len(top_songs)} ランキングを生成しました。")

if __name__ == "__main__":
    main()