import json
import os
import shutil
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta
from config import MASTER_FILE, PREV_SNAPSHOT, LATEST_SNAPSHOT
from googleapiclient.discovery import build

USER_AGENT = "VocaloidCombinedChartBot/2.0"

def rotate_snapshots_if_needed():
    """前回のスナップショット取得から5日以上経過していれば prev_monday.json へローテーション"""
    if not LATEST_SNAPSHOT.exists():
        return
    try:
        with open(LATEST_SNAPSHOT, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data or len(data) < 10:
            return
        updated_str = data[0].get("updated_at")
        if updated_str:
            last_dt = datetime.fromisoformat(updated_str)
            if datetime.now() - last_dt >= timedelta(days=5):
                shutil.copyfile(LATEST_SNAPSHOT, PREV_SNAPSHOT)
                print("前週のスナップショットを prev_monday.json にローテーションしました。")
    except Exception as e:
        print(f"Snapshot rotation check skipped: {e}")

def fetch_youtube_stats_batch(youtube_ids: list, api_key: str) -> dict:
    """YouTube Data API v3 で50曲ずつ一括取得"""
    result = {}
    if not api_key or not youtube_ids:
        return result

    youtube = build("youtube", "v3", developerKey=api_key)
    valid_ids = [yid for yid in youtube_ids if yid]

    for i in range(0, len(valid_ids), 50):
        chunk = valid_ids[i:i+50]
        try:
            res = youtube.videos().list(
                part="snippet,statistics",
                id=",".join(chunk)
            ).execute()
            for item in res.get("items", []):
                vid = item["id"]
                stats = item.get("statistics", {})
                snippet = item.get("snippet", {})
                result[vid] = {
                    "yt_views": int(stats.get("viewCount", 0)),
                    "yt_likes": int(stats.get("likeCount", 0)),
                    "yt_comments": int(stats.get("commentCount", 0)),
                    "published_at": snippet.get("publishedAt", ""),
                    "channel_title": snippet.get("channelTitle", "")
                }
        except Exception as e:
            print(f"YouTube Batch API Error: {e}")
    return result

def fetch_niconico_thumbinfo(niconico_id: str) -> dict:
    """ニコニコ動画の公式XML API (getthumbinfo) から実測値を取得"""
    if not niconico_id:
        return {}
    url = f"https://ext.nicovideo.jp/api/getthumbinfo/{niconico_id}"
    try:
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        root = ET.fromstring(res.text)
        if root.attrib.get("status") == "ok":
            thumb = root.find("thumb")
            return {
                "nc_views": int(thumb.findtext("view_counter", "0")),
                "nc_mylist": int(thumb.findtext("mylist_counter", "0")),
                "nc_comments": int(thumb.findtext("comment_num", "0")),
                "nc_published_at": thumb.findtext("first_retrieve", ""),
                "nc_author": thumb.findtext("user_nickname", "")
            }
    except Exception as e:
        print(f"Niconico thumbinfo error ({niconico_id}): {e}")
    return {}

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("エラー: YOUTUBE_API_KEY が設定されていません。")
        return

    rotate_snapshots_if_needed()

    with open(MASTER_FILE, "r", encoding="utf-8") as f:
        songs = json.load(f)

    yt_ids = [s.get("youtube_id") for s in songs if s.get("youtube_id")]
    yt_map = fetch_youtube_stats_batch(yt_ids, api_key)

    snapshots = []
    for song in songs:
        yid = song.get("youtube_id", "")
        nid = song.get("niconico_id", "")

        yt_stats = yt_map.get(yid, {})
        nc_stats = fetch_niconico_thumbinfo(nid) if nid else {}

        yt_views = yt_stats.get("yt_views", 0)
        yt_likes = yt_stats.get("yt_likes", 0)
        yt_comments = yt_stats.get("yt_comments", 0)

        nc_views = nc_stats.get("nc_views", 0)
        nc_mylist = nc_stats.get("nc_mylist", 0)
        nc_comments = nc_stats.get("nc_comments", 0)

        if yt_views == 0 and nc_views == 0:
            continue

        pub_date = yt_stats.get("published_at") or nc_stats.get("nc_published_at") or ""
        producer = song.get("producer") or yt_stats.get("channel_title") or nc_stats.get("nc_author") or "ボカロP"

        snapshots.append({
            "song_id": song["song_id"],
            "title": song["title"],
            "producer": producer,
            "vocal": song.get("vocal", "VOCALOID"),
            "youtube_id": yid,
            "niconico_id": nid,
            "published_at": pub_date,
            "yt_views": yt_views,
            "yt_likes": yt_likes,
            "yt_comments": yt_comments,
            "nc_views": nc_views,
            "nc_mylist": nc_mylist,
            "nc_comments": nc_comments,
            "updated_at": datetime.now().isoformat()
        })

    LATEST_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    with open(LATEST_SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)
    print(f"全 {len(snapshots)} 曲の6指標データ取得が完了しました。")

if __name__ == "__main__":
    main()