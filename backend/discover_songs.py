import json
import os
import re
import requests
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from config import MASTER_FILE

USER_AGENT = "VocaloidCombinedChartBot/1.0"

# ニコ動のタグから自動判定する合成音声ライブラリ一覧
KNOWN_VOCALS = [
    "初音ミク", "重音テト", "重音テトSV", "GUMI", "可不", "鏡音リン", "鏡音レン",
    "巡音ルカ", "flower", "v_flower", "IA", "歌愛ユキ", "ずんだもん", "星界",
    "裏命", "狐子", "足立レイ", "琴葉姉妹", "音街ウナ", "結月ゆかり", "紲星あかり",
    "神威がくぽ", "KAITO", "MEIKO", "知声", "ナースロボ＿タイプＴ", "春歌ナナ"
]

YT_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)

def clean_title(raw_title: str) -> str:
    """【初音ミク】などの括弧書きや / ボカロP名 を整理して曲名を抽出"""
    title = re.sub(r"【.*?】|\[.*?\]", "", raw_title).strip()
    if " / " in title:
        title = title.split(" / ")[0].strip()
    elif " - " in title:
        title = title.split(" - ")[0].strip()
    return title or raw_title

def extract_vocals(tags_str: str) -> str:
    if not tags_str:
        return "VOCALOID"
    found = [v for v in KNOWN_VOCALS if v in tags_str]
    return "・".join(found[:3]) if found else "VOCALOID"

def fetch_niconico_candidates():
    """ニコ動スナップショットAPIから直近の急上昇曲と人気曲を取得"""
    url = "https://api.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
    headers = {"User-Agent": USER_AGENT}
    candidates = {}

    # 1. 直近60日以内の新曲・急上昇（マイリスト順）
    sixty_days_ago = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00+09:00")
    queries = [
        {"_sort": "-mylistCounter", "_limit": 25, "filters[startTime][gte]": sixty_days_ago},
        {"_sort": "-viewCounter", "_limit": 25}
    ]

    for q_params in queries:
        params = {
            "q": "VOCALOID",
            "targets": "tagsExact",
            "fields": "contentId,title,description,viewCounter,mylistCounter,tags,startTime",
            "_context": USER_AGENT,
            **q_params
        }
        try:
            res = requests.get(url, params=params, headers=headers, timeout=15)
            data = res.json()
            for item in data.get("data", []):
                cid = item.get("contentId")
                if cid and cid not in candidates:
                    candidates[cid] = item
        except Exception as e:
            print(f"Niconico candidate fetch error: {e}")

    return list(candidates.values())

def search_youtube_id(youtube, title: str):
    """概要欄にリンクがない場合、YouTube APIで曲名から検索"""
    try:
        req = youtube.search().list(
            part="snippet",
            q=f"{title} VOCALOID",
            type="video",
            maxResults=1
        )
        res = req.execute()
        items = res.get("items", [])
        if items:
            return items[0]["id"]["videoId"], items[0]["snippet"]["channelTitle"]
    except Exception as e:
        print(f"YouTube search fallback error ({title}): {e}")
    return None, None

def fetch_youtube_channels(youtube, yt_ids: list) -> dict:
    """YouTubeの動画IDリストから投稿者名(チャンネル名)を一括取得"""
    channel_map = {}
    for i in range(0, len(yt_ids), 50):
        chunk = yt_ids[i:i+50]
        try:
            res = youtube.videos().list(part="snippet", id=",".join(chunk)).execute()
            for item in res.get("items", []):
                channel_map[item["id"]] = item["snippet"]["channelTitle"]
        except Exception as e:
            print(f"YouTube channel fetch error: {e}")
    return channel_map

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    youtube = build("youtube", "v3", developerKey=api_key) if api_key else None

    existing_songs = []
    if MASTER_FILE.exists():
        try:
            with open(MASTER_FILE, "r", encoding="utf-8") as f:
                existing_songs = json.load(f)
        except json.JSONDecodeError:
            existing_songs = []

    by_nc = {s.get("niconico_id"): s for s in existing_songs if s.get("niconico_id")}
    nc_items = fetch_niconico_candidates()
    print(f"ニコニコ動画から候補曲を {len(nc_items)} 件取得しました。")

    search_quota_used = 0
    MAX_SEARCH_CALLS = 15  # APIクォータ節約のため1回の自動検索は最大15件まで

    new_entries = []
    for item in nc_items:
        nc_id = item["contentId"]
        if nc_id in by_nc:
            continue

        raw_title = item.get("title", "")
        title = clean_title(raw_title)
        desc = item.get("description") or ""
        tags = item.get("tags") or ""

        # Step 1: ニコ動の概要欄からYouTubeリンクを正規表現で探す
        match = YT_URL_PATTERN.search(desc)
        yt_id = match.group(1) if match else None
        producer = None

        # Step 2: 概要欄になければYouTube検索で探す
        if not yt_id and youtube and search_quota_used < MAX_SEARCH_CALLS:
            yt_id, producer = search_youtube_id(youtube, title)
            search_quota_used += 1

        if not yt_id:
            continue

        entry = {
            "song_id": f"song_{nc_id}",
            "title": title,
            "producer": producer or "ボカロP",
            "vocal": extract_vocals(tags),
            "youtube_id": yt_id,
            "niconico_id": nc_id
        }
        new_entries.append(entry)
        by_nc[nc_id] = entry

    # チャンネル名（ボカロP名）が未取得のものをYouTube APIで一括補完
    if youtube and new_entries:
        need_channel_ids = [e["youtube_id"] for e in new_entries if e["producer"] == "ボカロP"]
        if need_channel_ids:
            ch_map = fetch_youtube_channels(youtube, need_channel_ids)
            for e in new_entries:
                if e["youtube_id"] in ch_map:
                    e["producer"] = ch_map[e["youtube_id"]]

    updated_master = existing_songs + new_entries
    MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(updated_master, f, ensure_ascii=False, indent=2)

    print(f"マスターデータ更新完了: 新規追加 {len(new_entries)} 曲 / 合計 {len(updated_master)} 曲")

if __name__ == "__main__":
    main()