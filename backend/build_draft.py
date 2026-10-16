import json
from datetime import datetime, timedelta, timezone
from config import WEIGHTS, PREV_SNAPSHOT, LATEST_SNAPSHOT, DRAFT_FILE, PUBLIC_LATEST

TOP_N = 20

def parse_days_since_published(pub_str: str) -> float:
    """動画公開日から現在までの経過日数を算出"""
    if not pub_str:
        return 180.0
    try:
        clean_str = pub_str.replace("Z", "+00:00")
        pub_dt = datetime.fromisoformat(clean_str)
        now_dt = datetime.now(timezone.utc)
        days = (now_dt - pub_dt).total_seconds() / 86400.0
        return max(0.5, days)
    except Exception:
        return 180.0

def estimate_weekly_increment_for_new_entry(song: dict) -> dict:
    """
    クローラーが今週新しく発見した楽曲の週間獲得数を算出する。
    ・公開7日以内の新曲：累計値＝今週の獲得数（100%実測値）
    ・公開8日以上の既存曲：経過日数と減衰カーブから直近7日間の純増分を算出
    """
    days = parse_days_since_published(song.get("published_at", ""))

    if days <= 7.5:
        # 集計期間内に投稿された完全な新曲（全量が今週の純増分）
        ratio_views = 1.0
        ratio_engage = 1.0
    elif days <= 21.0:
        # 公開2〜3週目の準新曲
        ratio_views = (7.0 / days) * 0.70
        ratio_engage = (7.0 / days) * 0.50
    elif days <= 90.0:
        # 公開1〜3ヶ月の中期ヒット曲
        ratio_views = (7.0 / days) * 0.45
        ratio_engage = (7.0 / days) * 0.20
    else:
        # 公開3ヶ月以上のロングヒット・カタログ曲
        ratio_views = (7.0 / days) * 0.30
        ratio_engage = (7.0 / days) * 0.08

    return {
        "yt_views": int(song.get("yt_views", 0) * ratio_views),
        "yt_likes": int(song.get("yt_likes", 0) * ratio_engage),
        "yt_comments": int(song.get("yt_comments", 0) * ratio_engage),
        "nc_views": int(song.get("nc_views", 0) * ratio_views),
        "nc_mylist": int(song.get("nc_mylist", 0) * ratio_engage),
        "nc_comments": int(song.get("nc_comments", 0) * ratio_engage),
    }

def compute_chart_dates():
    """直近の月曜〜日曜の集計期間と、水曜13:00の公開日時を自動算出"""
    now = datetime.now()
    # 直近の日曜日を期末、その6日前（月曜日）を期首とする
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
    prev_map = {}
    if PREV_SNAPSHOT.exists():
        try:
            with open(PREV_SNAPSHOT, "r", encoding="utf-8") as f:
                prev_map = {item["song_id"]: item for item in json.load(f)}
        except json.JSONDecodeError:
            prev_map = {}

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
        p = prev_map.get(sid)
        days = parse_days_since_published(song.get("published_at", ""))

        # 前週のスナップショットが存在し、実測の増加がある場合
        use_measured_diff = False
        if p is not None:
            diff_yt = song.get("yt_views", 0) - p.get("yt_views", 0)
            diff_nc = song.get("nc_views", 0) - p.get("nc_views", 0)
            if (diff_yt > 0 or diff_nc > 0) and (days <= 14 or diff_yt < song.get("yt_views", 1) * 0.6):
                use_measured_diff = True

        if use_measured_diff:
            raw_diff = {
                k: max(0, song.get(k, 0) - p.get(k, 0))
                for k in WEIGHTS.keys()
            }
            rebuilt_prev_snapshots.append(p)
        else:
            raw_diff = estimate_weekly_increment_for_new_entry(song)
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

    # 次週の引き算用にベースラインスナップショットを保存
    with open(PREV_SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(rebuilt_prev_snapshots, f, ensure_ascii=False, indent=2)

    # 総合ポイントの降順でソートし、上位20曲（TOP 20）を選出
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
            f"今週は全{len(ranked_songs)}曲のアクティブ監視プールの中から、"
            f"{top1['producer']}「{top1['title']}」が週間 {top1['total_pt']:,} pt を獲得し総合首位に立った。"
        ),
        "weights": WEIGHTS,
        "songs": top_songs
    }

    DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DRAFT_FILE, "w", encoding="utf-8") as f:
        json.dump(draft_payload, f, ensure_ascii=False, indent=2)

    print(f"監視プール {len(ranked_songs)} 曲から TOP {len(top_songs)} の週間ランキングを生成しました。")

if __name__ == "__main__":
    main()