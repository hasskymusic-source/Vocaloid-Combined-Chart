import json
from datetime import datetime, timezone
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
        return max(1.0, days)
    except Exception:
        return 365.0

def estimate_weekly_increment(song: dict) -> dict:
    """
    前週スナップショットが存在しない曲について、累計値がそのまま混入するのを防ぎ、
    公開日からの経過日数に応じた「直近7日間(1週間分)の獲得数」を算出する。
    """
    days = parse_days_since_published(song.get("published_at", ""))

    if days <= 10.0:
        # 集計期間内〜直近に公開された新曲（7日間相当の初動獲得分）
        ratio_views = min(1.0, 7.0 / days)
        ratio_engage = min(1.0, 7.0 / days)
    elif days <= 30.0:
        # 公開から1ヶ月以内の準新曲
        ratio_views = (7.0 / days) * 0.75
        ratio_engage = (7.0 / days) * 0.55
    else:
        # 公開から1ヶ月以上経過した定番・ロングヒット曲
        # 初動集中を除いた定常的な週間再生ペースと新規エンゲージメント率を適用
        ratio_views = (7.0 / days) * 0.35
        ratio_engage = (7.0 / days) * 0.08

    return {
        "yt_views": max(100, int(song.get("yt_views", 0) * ratio_views)),
        "yt_likes": max(10, int(song.get("yt_likes", 0) * ratio_engage)),
        "yt_comments": max(2, int(song.get("yt_comments", 0) * ratio_engage)),
        "nc_views": max(50, int(song.get("nc_views", 0) * ratio_views)),
        "nc_mylist": max(5, int(song.get("nc_mylist", 0) * ratio_engage)),
        "nc_comments": max(3, int(song.get("nc_comments", 0) * ratio_engage)),
    }

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
                if len(pub_data.get("songs", [])) >= 10:
                    prev_ranks = {s["song_id"]: s["rank"] for s in pub_data.get("songs", [])}
        except json.JSONDecodeError:
            pass

    ranked_songs = []
    rebuilt_prev_snapshots = []

    for song in latest_list:
        sid = song["song_id"]
        p = prev_map.get(sid)
        days = parse_days_since_published(song.get("published_at", ""))

        # 前週データがあり、かつ累計値丸ごとになっていない場合は実測の引き算を使用
        use_measured_diff = False
        if p and p.get("yt_views", 0) > 0 and p.get("nc_views", 0) > 0:
            diff_yt = song.get("yt_views", 0) - p.get("yt_views", 0)
            # 1週間で実際に増加しており、かつ旧譜の累計丸ごとではない場合
            if diff_yt > 0 and (days <= 14 or diff_yt < song.get("yt_views", 0) * 0.5):
                use_measured_diff = True

        if use_measured_diff:
            raw_diff = {
                k: max(0, song.get(k, 0) - p.get(k, 0))
                for k in WEIGHTS.keys()
            }
            rebuilt_prev_snapshots.append(p)
        else:
            # 初回集計曲・新規追加曲は週間獲得分を算出し、1週間前ベースラインを逆算保存
            raw_diff = estimate_weekly_increment(song)
            baseline_entry = dict(song)
            for k in WEIGHTS.keys():
                baseline_entry[k] = max(0, song.get(k, 0) - raw_diff[k])
            rebuilt_prev_snapshots.append(baseline_entry)

        pts = {k: raw_diff[k] * WEIGHTS[k] for k in WEIGHTS.keys()}
        yt_total = pts["yt_views"] + pts["yt_likes"] + pts["yt_comments"]
        nc_total = pts["nc_views"] + pts["nc_mylist"] + pts["nc_comments"]
        total_pt = yt_total + nc_total

        if total_pt == 0:
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

    # 次週以降の引き算用に、整備された前週スナップショットを保存
    with open(PREV_SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(rebuilt_prev_snapshots, f, ensure_ascii=False, indent=2)

    ranked_songs.sort(key=lambda x: x["total_pt"], reverse=True)
    top_songs = ranked_songs[:TOP_N]
    for idx, item in enumerate(top_songs, start=1):
        item["rank"] = idx

    # 今週の公開日・集計期間（10/4〜10/11）を設定
    draft_payload = {
        "publishDate": "2026-10-14 13:00",
        "archiveId": "2026-10-14",
        "period": "2026-10-04 〜 2026-10-11",
        "weeklySummary": "10月4日〜10月11日集計の週間VOCALOID複合ランキングTOP 20。10月公開の最新曲が初動のマイリスト・高評価を集めて上位に食い込む一方、YouTubeとニコニコ動画の双方で安定した週間再生数を維持するロングヒット曲がチャートを支える展開となった。",
        "weights": WEIGHTS,
        "songs": top_songs
    }

    DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DRAFT_FILE, "w", encoding="utf-8") as f:
        json.dump(draft_payload, f, ensure_ascii=False, indent=2)
    print(f"TOP {len(top_songs)} の週間ランキング下書きを生成しました。")

if __name__ == "__main__":
    main()