import json
from datetime import datetime, timedelta
from config import WEIGHTS, PREV_SNAPSHOT, LATEST_SNAPSHOT, DRAFT_FILE, PUBLIC_LATEST

def main():
    with open(PREV_SNAPSHOT, "r", encoding="utf-8") as f:
        prev_map = {item["song_id"]: item for item in json.load(f)}

    with open(LATEST_SNAPSHOT, "r", encoding="utf-8") as f:
        latest_list = json.load(f)

    # 前週の公開ランキングから前回順位を取得
    prev_ranks = {}
    if PUBLIC_LATEST.exists():
        with open(PUBLIC_LATEST, "r", encoding="utf-8") as f:
            pub_data = json.load(f)
            prev_ranks = {s["song_id"]: s["rank"] for s in pub_data.get("songs", [])}

    ranked_songs = []
    for song in latest_list:
        sid = song["song_id"]
        p = prev_map.get(sid, {})

        # 月曜0:00〜日曜23:59の7日間増加分（Δ）
        raw_diff = {
            k: max(0, song.get(k, 0) - p.get(k, 0))
            for k in WEIGHTS.keys()
        }

        # 各指標のポイント計算
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
            "vocal": song.get("vocal", ""),
            "youtube_id": song.get("youtube_id", ""),
            "niconico_id": song.get("niconico_id", ""),
            "total_pt": total_pt,
            "yt_total_pt": yt_total,
            "nc_total_pt": nc_total,
            "raw": raw_diff,
            "pts": pts,
            "prevRank": prev_ranks.get(sid, "NEW"),
            "commentary": ""  # ★ここに月曜〜水曜昼の間に解説を追記できる
        })

    # 総合ポイント降順ソート＆順位付け
    ranked_songs.sort(key=lambda x: x["total_pt"], reverse=True)
    for idx, item in enumerate(ranked_songs[:100], start=1):
        item["rank"] = idx

    now = datetime.now()
    wednesday = now + timedelta(days=(2 - now.weekday()) % 7)
    start_day = now - timedelta(days=7)
    end_day = now - timedelta(days=1)

    draft_payload = {
        "publishDate": wednesday.strftime("%Y-%m-%d 13:00"),
        "archiveId": wednesday.strftime("%Y-%m-%d"),
        "period": f"{start_day.strftime('%Y-%m-%d')} 〜 {end_day.strftime('%Y-%m-%d')}",
        "weeklySummary": "ここに今週のチャート総括（Billion Hits!風の全体考察）を記入します。",
        "weights": WEIGHTS,
        "songs": ranked_songs[:100]
    }

    DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DRAFT_FILE, "w", encoding="utf-8") as f:
        json.dump(draft_payload, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()