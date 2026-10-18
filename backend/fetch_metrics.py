import json
import os
import shutil
import time
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta
from config import MASTER_FILE, PREV_SNAPSHOT, LATEST_SNAPSHOT
from discover_songs import clean_song_title, detect_vocals, search_youtube_id_web_strict
from googleapiclient.discovery import build

USER_AGENT = "Mozilla/5.0 (compatible; VocaloidCombinedChartBot/8.1)"

def rotate_snapshots_if_needed():
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
    result = {}
    if not api_key or not youtube_ids:
        return result

    youtube = build("youtube", "v3", developerKey=api_key)
    valid_ids = list(dict.fromkeys([yid for yid in youtube_ids if yid]))

    for i in range(0, len(valid_ids), 50):
        chunk = valid_ids[i:i+50]
        for attempt in range(2):
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
                        "yt_title": snippet.get("title", ""),
                        "yt_desc": snippet.get("description", "")[:400],
                        "yt_tags": " ".join(snippet.get("tags", [])),
                        "yt_views": int(stats.get("viewCount", 0)),
                        "yt_likes": int(stats.get("likeCount", 0)),
                        "yt_comments": int(stats.get("commentCount", 0)),
                        "yt_published_at": snippet.get("publishedAt", ""),
                        "channel_title": snippet.get("channelTitle", "")
                    }
                break
            except Exception as e:
                print(f"YouTube Batch API Warning (attempt {attempt+1}): {e}")
                time.sleep(1)
    return result

def fetch_niconico_thumbinfo(niconico_id: str) -> dict:
    if not niconico_id:
        return {}
    url = f"https://ext.nicovideo.jp/api/getthumbinfo/{niconico_id}"
    for attempt in range(2):
        try:
            res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            root = ET.fromstring(res.text)
            if root.attrib.get("status") == "ok":
                thumb = root.find("thumb")
                tags = " ".join([t.text for t in thumb.findall("tags/tag") if t.text])
                return {
                    "nc_title": thumb.findtext("title", ""),
                    "nc_desc": (thumb.findtext("description", "") or "")[:400],
                    "nc_tags": tags,
                    "nc_views": int(thumb.findtext("view_counter", "0")),
                    "nc_mylist": int(thumb.findtext("mylist_counter", "0")),
                    "nc_comments": int(thumb.findtext("comment_num", "0")),
                    "nc_published_at": thumb.findtext("first_retrieve", ""),
                    "nc_author": thumb.findtext("user_nickname", "")
                }
        except Exception:
            time.sleep(0.5)
    return {}

def fetch_niconico_stats_hybrid(niconico_ids: list) -> dict:
    result = {}
    valid_ids = list(dict.fromkeys([nid for nid in niconico_ids if nid]))
    if not valid_ids:
        return result

    snap_url = "https://api.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
    headers = {"User-Agent": USER_AGENT}

    for i in range(0, len(valid_ids), 40):
        chunk = valid_ids[i:i+40]
        params = {
            "q": "",
            "targets": "",
            "fields": "contentId,title,description,tags,viewCounter,mylistCounter,commentCounter,startTime",
            "_sort": "-viewCounter",
            "_limit": len(chunk),
            "_context": "VocaloidCombinedChartBot"
        }
        for idx, cid in enumerate(chunk):
            params[f"filters[contentId][{idx}]"] = cid
        try:
            res = requests.get(snap_url, params=params, headers=headers, timeout=12)
            if res.status_code == 200:
                for item in res.json().get("data", []):
                    cid = item.get("contentId")
                    result[cid] = {
                        "nc_title": item.get("title", ""),
                        "nc_desc": (item.get("description") or "")[:400],
                        "nc_tags": item.get("tags", ""),
                        "nc_views": int(item.get("viewCounter", 0)),
                        "nc_mylist": int(item.get("mylistCounter", 0)),
                        "nc_comments": int(item.get("commentCounter", 0)),
                        "nc_published_at": item.get("startTime", ""),
                        "nc_author": ""
                    }
        except Exception:
            pass

    for cid in valid_ids:
        if cid not in result or result[cid]["nc_views"] == 0:
            info = fetch_niconico_thumbinfo(cid)
            if info:
                result[cid] = info

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

    yt_map = fetch_youtube_stats_batch(yt_ids, api_key)
    nc_map = fetch_niconico_stats_hybrid(nc_ids)

    used_yt_ids = set(yt_ids)
    rescue_yt_ids = []
    for song in songs:
        yid = song.get("youtube_id", "")
        nid = song.get("niconico_id", "")
        nc_v = nc_map.get(nid, {}).get("nc_views", 0)
        if (not yid or yid not in yt_map) and nc_v >= 10000:
            found_yid = search_youtube_id_web_strict(song["title"], song["producer"], used_yt_ids)
            if found_yid and found_yid not in used_yt_ids:
                song["youtube_id"] = found_yid
                used_yt_ids.add(found_yid)
                rescue_yt_ids.append(found_yid)

    if rescue_yt_ids:
        yt_map.update(fetch_youtube_stats_batch(rescue_yt_ids, api_key))
        with open(MASTER_FILE, "w", encoding="utf-8") as f:
            json.dump(songs, f, ensure_ascii=False, indent=2)

    snapshots = []
    seen_yt = set()
    seen_nc = set()

    for song in songs:
        sid = song["song_id"]
        yid = song.get("youtube_id", "")
        nid = song.get("niconico_id", "")

        if (yid and yid in seen_yt) or (nid and nid in seen_nc):
            continue
        if yid:
            seen_yt.add(yid)
        if nid:
            seen_nc.add(nid)

        yt_stats = yt_map.get(yid, {})
        nc_stats = nc_map.get(nid, {})

        yt_views = yt_stats.get("yt_views", 0)
        yt_likes = yt_stats.get("yt_likes", 0)
        yt_comments = yt_stats.get("yt_comments", 0)

        nc_views = nc_stats.get("nc_views", 0)
        nc_mylist = nc_stats.get("nc_mylist", 0)
        nc_comments = nc_stats.get("nc_comments", 0)

        if yt_views == 0 and nc_views == 0:
            continue

        producer = song.get("producer") or nc_stats.get("nc_author") or yt_stats.get("channel_title") or "ボカロP"
        title = clean_song_title(song["title"], producer)
        if title.lower() == producer.lower() or len(title) <= 1:
            raw_t = yt_stats.get("yt_title") or nc_stats.get("nc_title") or song["title"]
            title = clean_song_title(raw_t, producer)

        # 動画タイトルとタグ・概要欄を分離して渡し、タイトルの表記（初音ミク・重音テト・亞北ネル）を最優先で確定
        video_titles = f"{yt_stats.get('yt_title', '')} {nc_stats.get('nc_title', '')}".strip()
        video_metas = " ".join([
            yt_stats.get("yt_tags", ""),
            yt_stats.get("yt_desc", ""),
            nc_stats.get("nc_tags", ""),
            nc_stats.get("nc_desc", "")
        ]).strip()
        vocal = detect_vocals(video_titles, video_metas, song.get("vocal", ""))

        snapshots.append({
            "song_id": sid,
            "title": title,
            "producer": producer,
            "vocal": vocal,
            "youtube_id": yid,
            "niconico_id": nid,
            "yt_published_at": yt_stats.get("yt_published_at", ""),
            "nc_published_at": nc_stats.get("nc_published_at", ""),
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