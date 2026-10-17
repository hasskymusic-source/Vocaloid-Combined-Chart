import json
import os
import shutil
import time
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta
from config import MASTER_FILE, PREV_SNAPSHOT, LATEST_SNAPSHOT
from discover_songs import clean_song_title, search_youtube_id_web_zero_quota
from googleapiclient.discovery import build

USER_AGENT = "Mozilla/5.0 (compatible; VocaloidCombinedChartBot/6.0)"

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
    """50曲ずつまとめて1ユニットでYouTube統計を取得（リトライ機構付き）"""
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
    """個別XML APIからのリアルタイム取得（2回リトライ付き）"""
    if not niconico_id:
        return {}
    url = f"https://ext.nicovideo.jp/api/getthumbinfo/{niconico_id}"
    for attempt in range(2):
        try:
            res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            root = ET.fromstring(res.text)
            if root.attrib.get("status") == "ok":
                thumb = root.find("thumb")
                return {
                    "nc_title": thumb.findtext("title", ""),
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
    """スナップショットAPIの一括取得＋getthumbinfo個別取得のハイブリッドで確実・高速に取得"""
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
            "fields": "contentId,title,viewCounter,mylistCounter,commentCounter,startTime",
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
                        "nc_views": int(item.get("viewCounter", 0)),
                        "nc_mylist": int(item.get("mylistCounter", 0)),
                        "nc_comments": int(item.get("commentCounter", 0)),
                        "nc_published_at": item.get("startTime", ""),
                        "nc_author": ""
                    }
        except Exception:
            pass

    # スナップショットに未反映の新曲や取得漏れは getthumbinfo で1曲ずつ確実に補完
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

    # 既存スナップショットをキャッシュとして保持（通信失敗やID欠損時の自動保護用）
    prev_cache = {}
    for snap_path in [LATEST_SNAPSHOT, PREV_SNAPSHOT]:
        if snap_path.exists():
            try:
                with open(snap_path, "r", encoding="utf-8") as f:
                    for item in json.load(f):
                        sid = item.get("song_id")
                        if sid and sid not in prev_cache:
                            prev_cache[sid] = item
            except Exception:
                pass

    rotate_snapshots_if_needed()

    with open(MASTER_FILE, "r", encoding="utf-8") as f:
        songs = json.load(f)

    # もし master 側で youtube_id が空でも、過去キャッシュに youtube_id があれば自動復元
    for song in songs:
        sid = song["song_id"]
        cached = prev_cache.get(sid, {})
        if not song.get("youtube_id") and cached.get("youtube_id"):
            song["youtube_id"] = cached["youtube_id"]
        if not song.get("niconico_id") and cached.get("niconico_id"):
            song["niconico_id"] = cached["niconico_id"]

    yt_ids = [s.get("youtube_id") for s in songs if s.get("youtube_id")]
    nc_ids = [s.get("niconico_id") for s in songs if s.get("niconico_id")]

    yt_map = fetch_youtube_stats_batch(yt_ids, api_key)
    nc_map = fetch_niconico_stats_hybrid(nc_ids)

    # 万が一 YouTube データが取れていない注目曲（ニコ動1万再生以上）があれば、その場でWeb検索からIDを特定して即時再取得
    rescue_yt_ids = []
    for song in songs:
        yid = song.get("youtube_id", "")
        nid = song.get("niconico_id", "")
        nc_v = nc_map.get(nid, {}).get("nc_views", 0)
        if (not yid or yid not in yt_map) and nc_v >= 10000:
            found_yid = search_youtube_id_web_zero_quota(f"{song['title']} {song['producer']} MV", song["title"])
            if found_yid:
                song["youtube_id"] = found_yid
                rescue_yt_ids.append(found_yid)

    if rescue_yt_ids:
        yt_map.update(fetch_youtube_stats_batch(rescue_yt_ids, api_key))
        with open(MASTER_FILE, "w", encoding="utf-8") as f:
            json.dump(songs, f, ensure_ascii=False, indent=2)

    snapshots = []
    for song in songs:
        sid = song["song_id"]
        yid = song.get("youtube_id", "")
        nid = song.get("niconico_id", "")
        cached = prev_cache.get(sid, {})

        yt_stats = yt_map.get(yid, {})
        nc_stats = nc_map.get(nid, {})

        # APIの一時エラーで0になった場合は前回キャッシュ値で下支えして急落バグを防止
        yt_views = yt_stats.get("yt_views", 0) or cached.get("yt_views", 0)
        yt_likes = yt_stats.get("yt_likes", 0) or cached.get("yt_likes", 0)
        yt_comments = yt_stats.get("yt_comments", 0) or cached.get("yt_comments", 0)

        nc_views = nc_stats.get("nc_views", 0) or cached.get("nc_views", 0)
        nc_mylist = nc_stats.get("nc_mylist", 0) or cached.get("nc_mylist", 0)
        nc_comments = nc_stats.get("nc_comments", 0) or cached.get("nc_comments", 0)

        if yt_views == 0 and nc_views == 0:
            continue

        producer = song.get("producer") or nc_stats.get("nc_author") or yt_stats.get("channel_title") or "ボカロP"
        title = clean_song_title(song["title"], producer)
        if title.lower() == producer.lower() or len(title) <= 1:
            raw_t = yt_stats.get("yt_title") or nc_stats.get("nc_title") or song["title"]
            title = clean_song_title(raw_t, producer)

        snapshots.append({
            "song_id": sid,
            "title": title,
            "producer": producer,
            "vocal": song.get("vocal", "VOCALOID"),
            "youtube_id": yid,
            "niconico_id": nid,
            "yt_published_at": yt_stats.get("yt_published_at") or cached.get("yt_published_at", ""),
            "nc_published_at": nc_stats.get("nc_published_at") or cached.get("nc_published_at", ""),
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