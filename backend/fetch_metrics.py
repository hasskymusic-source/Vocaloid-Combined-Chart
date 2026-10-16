import json
import os
import requests
from datetime import datetime
from config import MASTER_FILE, LATEST_SNAPSHOT
from googleapiclient.discovery import build

def fetch_youtube_stats(youtube_id, api_key):
    if not youtube_id or not api_key:
        return {"yt_views": 0, "yt_likes": 0, "yt_comments": 0}
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        request = youtube.videos().list(part="statistics", id=youtube_id)
        response = request.execute()
        if response["items"]:
            stats = response["items"][0]["statistics"]
            return {
                "yt_views": int(stats.get("viewCount", 0)),
                "yt_likes": int(stats.get("likeCount", 0)),
                "yt_comments": int(stats.get("commentCount", 0))
            }
    except Exception as e:
        print(f"YouTube API Error ({youtube_id}): {e}")
    return {"yt_views": 0, "yt_likes": 0, "yt_comments": 0}

def fetch_niconico_stats(niconico_id):
    if not niconico_id:
        return {"nc_views": 0, "nc_mylist": 0, "nc_comments": 0}
    try:
        # ニコニコ動画のスナップショット検索APIを使用
        url = "https://api.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
        params = {
            "q": niconico_id,
            "targets": "contentId",
            "fields": "viewCounter,mylistCounter,commentCounter",
            "filters[contentId][0]": niconico_id
        }
        res = requests.get(url, params=params)
        data = res.json()
        if data.get("data"):
            stats = data["data"][0]
            return {
                "nc_views": stats.get("viewCounter", 0),
                "nc_mylist": stats.get("mylistCounter", 0),
                "nc_comments": stats.get("commentCounter", 0)
            }
    except Exception as e:
        print(f"Niconico API Error ({niconico_id}): {e}")
    return {"nc_views": 0, "nc_mylist": 0, "nc_comments": 0}

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("エラー: YOUTUBE_API_KEY が設定されていません。")
        return

    # マスターデータを読み込む
    with open(MASTER_FILE, "r", encoding="utf-8") as f:
        songs = json.load(f)

    snapshots = []
    for song in songs:
        print(f"データ取得中: {song['title']}")
        yt_stats = fetch_youtube_stats(song.get("youtube_id"), api_key)
        nc_stats = fetch_niconico_stats(song.get("niconico_id"))

        # 取得したデータを結合
        snapshots.append({
            "song_id": song["song_id"],
            "title": song["title"],
            "producer": song["producer"],
            "vocal": song["vocal"],
            "youtube_id": song.get("youtube_id"),
            "niconico_id": song.get("niconico_id"),
            **yt_stats,
            **nc_stats,
            "updated_at": datetime.now().isoformat()
        })

    # latest_monday.json として保存
    LATEST_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    with open(LATEST_SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)
    print("データ取得が完了しました。")

if __name__ == "__main__":
    main()