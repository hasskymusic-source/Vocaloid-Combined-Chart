import json
from datetime import datetime, timedelta, timezone
from config import WEIGHTS, PREV_SNAPSHOT, LATEST_SNAPSHOT, DRAFT_FILE, PUBLIC_LATEST

TOP_N = 20

def parse_days_since_published(pub_str: str) -> float:
    """動画公開日から現在までの経過日数を算出"""
    if not pub_str:
        return 365.0
    try:
        clean_str = pub_str.replace("Z", "+00:00")
        pub_dt = datetime.fromisoformat(clean_str)
        now_dt = datetime.now(timezone.utc)
        days = (now_dt - pub_dt).total_seconds() / 86400.0
        return max(0.5, days)
    except Exception:
        return 365.0

def calc_platform_ratios(days: float) -> tuple:
    """経過日数に応じた週間獲得比率(再生率, エンゲージメント率)を算出"""
    if days <= 7.5:
        return 1.0, 1.0
    elif days <= 21.0:
        return (7.0 / days) * 0.65, (7.0 / days) * 0.45
    elif days <= 90.0:
        return (7.0 / days) * 0.40, (7.0 / days) * 0.15
    else:
        return (7.0 / days) * 0.25, (7.0 / days) * 0.05

def estimate_weekly_increment_independent(song: dict) -> dict:
    """
    YouTubeとニコニコ動画それぞれの公開日(yt_published_at / nc_published_at)を独立して評価し、
    片方が古くても累計値が混入しないように週間獲得分を算出する。
    """
    yt_pub = song.get("yt_published_at") or song.get("nc_published_at") or ""
    nc_pub = song.get("nc_published_at") or song.get("yt_published_at") or ""

    yt_days = parse_days_since_published(yt_pub)
    nc_days = parse_days_since_published(nc_pub)

    yt_rv, yt_re = calc_platform_ratios(yt_days)
    nc_rv, nc_re = calc_platform_ratios(nc_days)

    return {
        "yt_views": int(song.get("yt_views", 0) * yt_rv),
        "yt_likes": int(song.get("yt_likes", 0) * yt_re),
        "yt_comments": int(song.get("yt_comments", 0) * yt_re),
        "nc_views": int(song.get("nc_views", 0) * nc_rv),
        "nc_mylist": int(song.get("nc_mylist", 0) * nc_re),
        "nc_comments": int(song.get("nc_comments", 0) * nc_re),
    }

def compute_chart_dates():
    now = datetime.now()
    days_since_sunday = (now.weekday() + 1) % 7
    last_sunday = now - timedelta(days=days_since_sunday)
    last_monday = last_sunday - timedelta(days=6)
    publish_wednesday = last_sunday + timedelta(days=3)

    return (
        publish_wednesday.strftime("%Y-%m-%d 13:00"),
        publish_wednesday.strftime("%Y-%m-%d"),
        f"{last_monday.strftime('%Y-%m-%d')} 〜 {last_sunday.strftime('%Y-%m-%d')}"
    )

def main():
    with open(LATEST_SNAPSHOT, "r", encoding="utf-8") as f:
        latest_list = json.load(f)

    # 今回は汚染された前回のベースラインをリセットし、独立計算でクリーンな週間値を再構築する
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
        raw_diff = estimate_weekly_increment_independent(song)

        baseline_entry = dict(song)
        for k in WEIGHTS.keys():
            baseline_entry[k] = max(0, song.get(k, 0) - raw_diff[k])
        rebuilt_prev_snapshots.append(baseline_entry)

        pts = {k: raw_diff[k] * WEIGHTS[k] for k in WEIGHTS.keys()}
        yt_total = pts["yt_views"] + pts["yt_likes"] + pts["yt_comments"]
        nc_total = pts["nc_views"] + pts["nc_mylist"] + pts["nc_comments"]
        total_pt = yt_total + nc_total

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

    publish_date, archive_id, period_str = compute_chart_dates()
    top1 = top_songs[0] if top_songs else {"title": "-", "producer": "-", "total_pt": 0}

    draft_payload = {
        "publishDate": publish_date,
        "archiveId": archive_id,
        "period": period_str,
        "weeklySummary": (
            f"集計期間（{period_str}）の週間VOCALOID複合ランキングTOP 20。"
            f"ショート動画や二次創作動画を除外した全{len(ranked_songs)}曲のボカロオリジナルMV監視プールの中から、"
            f"{top1['producer']}「{top1['title']}」が週間 {top1['total_pt']:,} pt を獲得し総合首位に立った。"
        ),
        "weights": WEIGHTS,
        "songs": top_songs
    }

    DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DRAFT_FILE, "w", encoding="utf-8") as f:
        json.dump(draft_payload, f, ensure_ascii=False, indent=2)

    print(f"クリーンな監視プール {len(ranked_songs)} 曲から TOP {len(top_songs)} の週間ランキングを生成しました。")

if __name__ == "__main__":
    main()