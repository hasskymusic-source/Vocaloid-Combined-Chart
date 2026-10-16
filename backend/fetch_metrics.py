import json
import os
import shutil
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta
from config import MASTER_FILE, PREV_SNAPSHOT, LATEST_SNAPSHOT
from googleapiclient.discovery import build

USER_AGENT = "VocaloidCombinedChartBot/1.0"

def rotate_snapshots_if_needed():
    """前回のスナップショットが5日以上前ならprev_monday.jsonへローテーションする"""
    if not LATEST_SNAPSHOT.exists():
        return
    try:
        with open(LATEST_SNAPSHOT, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
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
    """YouTube Data APIで複数動画の統計を50件ずつ一括取得"""
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
                    "channel_title": snippet.get("channelTitle", "")
                }
        except Exception as e:
            print(f"YouTube Batch API Error: {e}")
    return result

def fetch_niconico_thumbinfo_fallback(niconico_id: str) -> dict:
    """スナップショットAPIで取れない場合のリアルタイムXML APIフォールバック"""
    url = f"https://ext.nicovideo.jp/api/getthumbinfo/{niconico_id}"
    headers = {"User-Agent": USER_AGENT}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        root = ET.fromstring(res.text)
        if root.attrib.get("status") == "ok":
            thumb = root.find("thumb")
            return {
                "nc_views": int(thumb.findtext("view_counter", "0")),
                "nc_mylist": int(thumb.findtext("mylist_counter", "0")),
                "nc_comments": int(thumb.findtext("comment_num", "0"))
            }
    except Exception as e:
        print(f"Niconico thumbinfo fallback error ({niconico_id}): {e}")
    return {"nc_views": 0, "nc_mylist": 0, "nc_comments": 0}

def fetch_niconico_stats_batch(niconico_ids: list) -> dict:
    """ニコニコ動画スナップショット検索API v2で一括取得（必須パラメータ完備）"""
    result = {}
    valid_ids = [nid for nid in niconico_ids if nid]
    if not valid_ids:
        return result

    url = "https://api.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
    headers = {"User-Agent": USER_AGENT}

    for i in range(0, len(valid_ids), 40):
        chunk = valid_ids[i:i+40]
        params = {
            "q": "",
            "targets": "",
            "fields": "contentId,viewCounter,mylistCounter,commentCounter",
            "_sort": "-viewCounter",
            "_limit": len(chunk),
            "_context": USER_AGENT
        }
        for idx, cid in enumerate(chunk):
            params[f"filters[contentId][{idx}]"] = cid

        try:
            res = requests.get(url, params=params, headers=headers, timeout=15)
            data = res.json()
            for item in data.get("data", []):
                cid = item.get("contentId")
                result[cid] = {
                    "nc_views": int(item.get("viewCounter", 0)),
                    "nc_mylist": int(item.get("mylistCounter", 0)),
                    "nc_comments": int(item.get("commentCounter", 0))
                }
        except Exception as e:
            print(f"Niconico Batch API Error: {e}")

    # 万が一取得漏れがあったIDは getthumbinfo API で個別に補完
    for cid in valid_ids:
        if cid not in result or result[cid]["nc_views"] == 0:
            result[cid] = fetch_niconico_thumbinfo_fallback(cid)

    return result

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("エラー: YOUTUBE_API_KEY が設定されていません。")
        return

    rotate_snapshots_if_needed()

    with open(MASTER_FILE, "r", encoding="utf-8") as f:
        songs = json.load(f)

    yt_ids = [s.get("youtube_id") for s in songs if s.get("youtube_id")]
    nc_ids = [s.get("niconico_id") for s in songs if s.get("niconico_id")]

    print(f"集計対象 {len(songs)} 曲のデータを一括取得中...")
    yt_map = fetch_youtube_stats_batch(yt_ids, api_key)
    nc_map = fetch_niconico_stats_batch(nc_ids)

    snapshots = []
    for song in songs:
        yid = song.get("youtube_id")
        nid = song.get("niconico_id")
        yt_stats = yt_map.get(yid, {"yt_views": 0, "yt_likes": 0, "yt_comments": 0})
        nc_stats = nc_map.get(nid, {"nc_views": 0, "nc_mylist": 0, "nc_comments": 0})

        producer = song.get("producer", "ボカロP")
        if producer == "ボカロP" and yt_stats.get("channel_title"):
            producer = yt_stats["channel_title"]

        snapshots.append({
            "song_id": song["song_id"],
            "title": song["title"],
            "producer": producer,
            "vocal": song.get("vocal", "VOCALOID"),
            "youtube_id": yid,
            "niconico_id": nid,
            "yt_views": yt_stats["yt_views"],
            "yt_likes": yt_stats["yt_likes"],
            "yt_comments": yt_stats["yt_comments"],
            "nc_views": nc_stats["nc_views"],
            "nc_mylist": nc_stats["nc_mylist"],
            "nc_comments": nc_stats["nc_comments"],
            "updated_at": datetime.now().isoformat()
        })

    LATEST_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    with open(LATEST_SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)
    print(f"全 {len(snapshots)} 曲のデータ取得が完了しました。")

if __name__ == "__main__":
    main()