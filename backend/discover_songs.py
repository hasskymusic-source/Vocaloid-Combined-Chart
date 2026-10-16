import json
import os
import re
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from config import MASTER_FILE

USER_AGENT = "VocaloidCombinedChartBot/1.0"

KNOWN_VOCALS = [
    "初音ミク", "重音テト", "重音テトSV", "GUMI", "可不", "鏡音リン", "鏡音レン",
    "巡音ルカ", "flower", "v_flower", "IA", "歌愛ユキ", "ずんだもん", "星界",
    "足立レイ", "音街ウナ", "結月ゆかり", "KAITO", "MEIKO", "知声"
]

YT_ID_PATTERN = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)
NC_ID_PATTERN = re.compile(r"(sm\d{7,9})")

def clean_title(raw_title: str) -> str:
    title = re.sub(r"【.*?】|\[.*?\]", "", raw_title).strip()
    for sep in [" / ", " - ", " feat.", " ft."]:
        if sep in title:
            title = title.split(sep)[0].strip()
    return title or raw_title

def extract_vocals(text: str) -> str:
    if not text:
        return "VOCALOID"
    found = [v for v in KNOWN_VOCALS if v in text]
    return "・".join(dict.fromkeys(found))[:20] if found else "VOCALOID"

def get_niconico_thumb_data(nc_id: str) -> dict:
    """GitHub Actionsから確実に動作する getthumbinfo XML API で詳細を取得"""
    if not nc_id:
        return {}
    url = f"https://ext.nicovideo.jp/api/getthumbinfo/{nc_id}"
    try:
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        root = ET.fromstring(res.text)
        if root.attrib.get("status") == "ok":
            thumb = root.find("thumb")
            tags = " ".join([t.text for t in thumb.findall("tags/tag") if t.text])
            return {
                "title": thumb.findtext("title", ""),
                "description": thumb.findtext("description", ""),
                "tags": tags,
                "author": thumb.findtext("user_nickname", "")
            }
    except Exception as e:
        print(f"Thumbinfo check error ({nc_id}): {e}")
    return {}

def search_niconico_id_by_title(title: str, producer: str) -> str:
    """タイトルからニコ動のsm番号を検索"""
    url = "https://api.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
    params = {
        "q": f"{title} {producer}".strip(),
        "targets": "title,tags",
        "fields": "contentId,title,viewCounter",
        "_sort": "-viewCounter",
        "_limit": 3,
        "_context": USER_AGENT
    }
    try:
        res = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
        if res.status_code == 200:
            items = res.json().get("data", [])
            if items:
                return items[0].get("contentId", "")
    except Exception:
        pass
    return ""

def resolve_missing_ids(youtube, songs: list) -> list:
    """既存マスターデータの空欄・無効IDを双方向で自動補完・修復"""
    # 1. 登録済みYouTube IDの有効性と概要欄を一括チェック
    yt_ids = [s["youtube_id"] for s in songs if s.get("youtube_id")]
    yt_info_map = {}
    for i in range(0, len(yt_ids), 50):
        chunk = yt_ids[i:i+50]
        try:
            res = youtube.videos().list(part="snippet", id=",".join(chunk)).execute()
            for item in res.get("items", []):
                yt_info_map[item["id"]] = item["snippet"]
        except Exception as e:
            print(f"YouTube snippet batch error: {e}")

    search_calls = 0
    for song in songs:
        yid = song.get("youtube_id", "")
        nid = song.get("niconico_id", "")

        # YouTube IDが無効または空欄の場合に補完
        if not yid or yid not in yt_info_map:
            # まずニコ動の説明文からYouTubeリンクを探す
            if nid:
                nc_data = get_niconico_thumb_data(nid)
                m = YT_ID_PATTERN.search(nc_data.get("description", ""))
                if m:
                    yid = m.group(1)

            # 見つからなければYouTube検索APIで公式MVを特定
            if (not yid or yid not in yt_info_map) and search_calls < 12:
                try:
                    q_str = f"{song['title']} {song['producer']}"
                    s_res = youtube.search().list(
                        part="snippet", q=q_str, type="video", maxResults=1
                    ).execute()
                    items = s_res.get("items", [])
                    if items:
                        yid = items[0]["id"]["videoId"]
                        # 概要欄全文を取得するためvideos.listを呼ぶ
                        v_res = youtube.videos().list(part="snippet", id=yid).execute()
                        if v_res.get("items"):
                            yt_info_map[yid] = v_res["items"][0]["snippet"]
                    search_calls += 1
                except Exception as e:
                    print(f"YT Search error ({song['title']}): {e}")

            song["youtube_id"] = yid

        # ニコ動IDが空欄の場合、YouTubeの概要欄または検索から補完
        if not nid:
            snippet = yt_info_map.get(yid, {})
            desc = snippet.get("description", "")
            m = NC_ID_PATTERN.search(desc)
            if m:
                nid = m.group(1)
            else:
                nid = search_niconico_id_by_title(song["title"], song["producer"])
            song["niconico_id"] = nid

    return songs

def discover_new_vocaloid_songs(youtube, existing_songs: list) -> list:
    """YouTube APIで概要欄にニコ動(sm番号)リンクがある最新ボカロ曲を自動発掘"""
    known_yt = {s.get("youtube_id") for s in existing_songs if s.get("youtube_id")}
    known_nc = {s.get("niconico_id") for s in existing_songs if s.get("niconico_id")}

    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    candidate_yt_ids = []

    try:
        res = youtube.search().list(
            part="id",
            q='("初音ミク" OR "重音テト" OR "VOCALOID") "nicovideo.jp/watch/sm"',
            type="video",
            order="viewCount",
            publishedAfter=thirty_days_ago,
            maxResults=15
        ).execute()
        for item in res.get("items", []):
            vid = item["id"].get("videoId")
            if vid and vid not in known_yt:
                candidate_yt_ids.append(vid)
    except Exception as e:
        print(f"Discovery search skipped: {e}")

    if not candidate_yt_ids:
        return []

    new_entries = []
    try:
        v_res = youtube.videos().list(
            part="snippet,statistics", id=",".join(candidate_yt_ids)
        ).execute()
        for item in v_res.get("items", []):
            vid = item["id"]
            snippet = item["snippet"]
            desc = snippet.get("description", "")
            m = NC_ID_PATTERN.search(desc)
            if not m:
                continue
            nc_id = m.group(1)
            if nc_id in known_nc:
                continue

            raw_title = snippet.get("title", "")
            new_entries.append({
                "song_id": f"song_{nc_id}",
                "title": clean_title(raw_title),
                "producer": snippet.get("channelTitle", "ボカロP"),
                "vocal": extract_vocals(raw_title + " " + desc),
                "youtube_id": vid,
                "niconico_id": nc_id
            })
            known_yt.add(vid)
            known_nc.add(nc_id)
    except Exception as e:
        print(f"Discovery video details error: {e}")

    return new_entries

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YOUTUBE_API_KEY が未設定のためスキップします。")
        return

    youtube = build("youtube", "v3", developerKey=api_key)

    songs = []
    if MASTER_FILE.exists():
        with open(MASTER_FILE, "r", encoding="utf-8") as f:
            songs = json.load(f)

    # 1. 既存曲のID欠損・誤りを自動修復
    songs = resolve_missing_ids(youtube, songs)

    # 2. 新曲の自動発掘と追加
    new_songs = discover_new_vocaloid_songs(youtube, songs)
    updated_songs = songs + new_songs

    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(updated_songs, f, ensure_ascii=False, indent=2)

    print(f"マスターデータ整備完了: 合計 {len(updated_songs)} 曲（新規追加: {len(new_songs)} 曲）")

if __name__ == "__main__":
    main()