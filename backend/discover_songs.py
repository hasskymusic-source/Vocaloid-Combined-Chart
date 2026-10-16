import json
import os
import re
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from config import MASTER_FILE

USER_AGENT = "VocaloidCombinedChartBot/2.0"

# 抽出対象の合成音声キーワード
VOCAL_NAMES = [
    "初音ミク", "重音テト", "重音テトSV", "GUMI", "可不", "鏡音リン", "鏡音レン",
    "巡音ルカ", "flower", "v_flower", "IA", "歌愛ユキ", "ずんだもん", "星界",
    "裏命", "狐子", "足立レイ", "音街ウナ", "結月ゆかり", "紲星あかり",
    "KAITO", "MEIKO", "神威がくぽ", "知声", "ナースロボ＿タイプＴ", "琴葉姉妹", "春歌ナナ"
]

# 「歌ってみた」「切り抜き」等の非オリジナル動画を弾くNGワード
NG_KEYWORDS = [
    "歌ってみた", "踊ってみた", "演奏してみた", "叩いてみた", "弾いてみた",
    "切り抜き", "まとめ", "メドレー", "カラオケ", "off vocal", "instrumental",
    "reaction", "リアクション", "プロセカ", "プロジェクトセカイ", "譜面",
    "耐久", "1時間", "作業用bgm", "解説", "ランキング", "比較"
]

YT_ID_PATTERN = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)
NC_ID_PATTERN = re.compile(r"(sm\d{7,9})")

def is_vocaloid_original(title: str, description: str = "", tags: str = "") -> bool:
    """タイトルやタグから歌ってみた・二次創作・まとめ動画等のノイズを除外"""
    title_lower = title.lower()
    for ng in NG_KEYWORDS:
        if ng in title_lower:
            return False
    # カバー表記の除外（ただし「Cover Illustration」等は除外しないようタイトルのみで判定）
    if re.search(r"\b(cover|covered by|歌:)\b", title_lower):
        return False

    combined = f"{title} {description} {tags}"
    has_vocal_keyword = any(v in combined for v in VOCAL_NAMES) or any(
        k in combined.lower() for k in ["vocaloid", "ボカロ", "synthesizer v", "cevio", "utau", "voicevox", "miku", "teto"]
    )
    return has_vocal_keyword

def clean_song_title(raw_title: str) -> str:
    """動画タイトルから【初音ミク】やボカロP名・feat.表記を除去して純粋な曲名を抽出"""
    t = re.sub(r"【.*?】|\[.*?\]|『.*?』", lambda m: m.group(0)[1:-1] if m.group(0).startswith("『") else "", raw_title)
    t = re.sub(r"\(.*?(?:MV|Official|Music Video|初音ミク|重音テト|可不|GUMI|flower).*?\)", "", t, flags=re.IGNORECASE)
    for sep in [" / ", " ／ ", " - ", " feat.", " ft.", " Feat."]:
        if sep in t:
            parts = [p.strip() for p in t.split(sep) if p.strip()]
            if parts:
                t = parts[0]
                break
    return t.strip() or raw_title.strip()

def detect_vocals(text: str) -> str:
    found = [v for v in VOCAL_NAMES if v in text]
    if not found:
        tl = text.lower()
        if "miku" in tl:
            found.append("初音ミク")
        if "teto" in tl:
            found.append("重音テト")
    return "・".join(dict.fromkeys(found))[:25] if found else "VOCALOID / 合成音声"

def get_niconico_thumbinfo(nc_id: str) -> dict:
    """ニコ動公式XML APIから動画情報と説明文(YouTubeリンク含む)を取得"""
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
                "nc_id": nc_id,
                "title": thumb.findtext("title", ""),
                "description": thumb.findtext("description", ""),
                "tags": tags,
                "producer": thumb.findtext("user_nickname", ""),
                "views": int(thumb.findtext("view_counter", "0")),
                "mylist": int(thumb.findtext("mylist_counter", "0"))
            }
    except Exception:
        pass
    return {}

def crawl_niconico_trending() -> list:
    """ニコニコ動画のVOCALOIDタグRSSおよび検索APIから今伸びているsm番号を自動収集"""
    nc_ids = []
    headers = {"User-Agent": USER_AGENT}

    # 1. ニコニコ動画タグRSS（人気順・マイリスト順・新着順）
    rss_urls = [
        "https://www.nicovideo.jp/tag/VOCALOID?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/VOCALOID?sort=m&order=d&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E3%83%9C%E3%82%AB%E3%83%AD%E3%82%AA%E3%83%AA%E3%82%B8%E3%83%8A%E3%83%AB%E6%9B%B2?sort=h&rss=2.0&lang=ja-jp"
    ]
    for r_url in rss_urls:
        try:
            res = requests.get(r_url, headers=headers, timeout=10)
            if res.status_code == 200:
                found = NC_ID_PATTERN.findall(res.text)
                for cid in found:
                    if cid not in nc_ids:
                        nc_ids.append(cid)
        except Exception:
            pass

    # 2. スナップショット検索API（利用可能な場合）
    snap_url = "https://api.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00+09:00")
    for sort_key in ["-mylistCounter", "-viewCounter"]:
        params = {
            "q": "VOCALOID",
            "targets": "tagsExact",
            "fields": "contentId",
            "filters[startTime][gte]": thirty_days_ago,
            "_sort": sort_key,
            "_limit": 30,
            "_context": USER_AGENT
        }
        try:
            res = requests.get(snap_url, params=params, headers=headers, timeout=10)
            if res.status_code == 200:
                for item in res.json().get("data", []):
                    cid = item.get("contentId")
                    if cid and cid not in nc_ids:
                        nc_ids.append(cid)
        except Exception:
            pass

    return nc_ids[:60]

def crawl_youtube_trending(youtube) -> list:
    """YouTube Data APIで期間別・キーワード別に今伸びているボカロMVを自動探索"""
    now = datetime.now(timezone.utc)
    d7 = (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
    d30 = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    d120 = (now - timedelta(days=120)).strftime("%Y-%m-%dT00:00:00Z")
    d730 = (now - timedelta(days=730)).strftime("%Y-%m-%dT00:00:00Z")

    # 新譜・月間急上昇・グローバル・ロングヒットを網羅するマルチクエリ
    search_plans = [
        {"q": '"初音ミク" OR "重音テト" OR "VOCALOID" MV -歌ってみた -cover', "after": d7, "max": 25},
        {"q": '"Synthesizer V" OR "可不" OR "GUMI" OR "flower" OR "足立レイ" MV -cover', "after": d14 := (now - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z"), "max": 20},
        {"q": '"初音ミク" OR "重音テト" OR "VOCALOID" "nicovideo.jp/watch/sm"', "after": d30, "max": 30},
        {"q": '"初音ミク" OR "重音テト" Official MV -歌ってみた -cover', "after": d30, "max": 25},
        {"q": '"初音ミク" OR "重音テト" OR "ボカロ" MV -歌ってみた -cover', "after": d120, "max": 25},
        {"q": '"初音ミク" OR "重音テト" OR "VOCALOID" MV -歌ってみた -cover', "after": d730, "max": 25},
    ]

    discovered_yt_ids = []
    for plan in search_plans:
        try:
            res = youtube.search().list(
                part="id",
                q=plan["q"],
                type="video",
                order="viewCount",
                publishedAfter=plan["after"],
                maxResults=plan["max"]
            ).execute()
            for item in res.get("items", []):
                vid = item["id"].get("videoId")
                if vid and vid not in discovered_yt_ids:
                    discovered_yt_ids.append(vid)
        except Exception as e:
            print(f"YouTube search plan warning: {e}")

    return discovered_yt_ids

def search_niconico_by_title(title: str, producer: str) -> str:
    """YouTube概要欄にsm番号がない場合、ニコ動の検索RSSを使って曲名からsm番号を特定"""
    headers = {"User-Agent": USER_AGENT}
    for query in [f"{title} {producer}", f"{title} VOCALOID"]:
        try:
            res = requests.get(
                "https://www.nicovideo.jp/search/" + requests.utils.quote(query),
                params={"sort": "v", "order": "d", "rss": "2.0"},
                headers=headers,
                timeout=8
            )
            if res.status_code == 200:
                root = ET.fromstring(res.text)
                for item in root.findall("./channel/item")[:3]:
                    item_title = item.findtext("title", "")
                    link = item.findtext("link", "")
                    if title.lower() in item_title.lower() and is_vocaloid_original(item_title):
                        m = NC_ID_PATTERN.search(link)
                        if m:
                            return m.group(1)
        except Exception:
            pass
    return ""

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("エラー: YOUTUBE_API_KEY が設定されていません。")
        return

    youtube = build("youtube", "v3", developerKey=api_key)

    # 既存のトラッキングプールを読み込む
    pool = []
    if MASTER_FILE.exists():
        try:
            with open(MASTER_FILE, "r", encoding="utf-8") as f:
                pool = json.load(f)
        except json.JSONDecodeError:
            pool = []

    by_yt = {s["youtube_id"]: s for s in pool if s.get("youtube_id")}
    by_nc = {s["niconico_id"]: s for s in pool if s.get("niconico_id")}

    # 1. YouTubeから今伸びているボカロ候補曲を収集
    yt_candidates = crawl_youtube_trending(youtube)
    new_yt_ids = [vid for vid in yt_candidates if vid not in by_yt]
    print(f"YouTubeトレンド探索: 候補 {len(yt_candidates)} 件 (うち新規 {len(new_yt_ids)} 件)")

    # 50件ずつ videos.list で詳細情報を取得してフィルタ＆ニコ動ID抽出
    for i in range(0, len(new_yt_ids), 50):
        chunk = new_yt_ids[i:i+50]
        try:
            v_res = youtube.videos().list(part="snippet,statistics", id=",".join(chunk)).execute()
            for item in v_res.get("items", []):
                vid = item["id"]
                snippet = item.get("snippet", {})
                raw_title = snippet.get("title", "")
                desc = snippet.get("description", "")
                tags = " ".join(snippet.get("tags", []))
                channel = snippet.get("channelTitle", "ボカロP")

                if not is_vocaloid_original(raw_title, desc, tags):
                    continue

                title = clean_song_title(raw_title)
                vocal = detect_vocals(f"{raw_title} {desc} {tags}")

                # 概要欄からニコ動の sm番号 を抽出、なければタイトル検索で照合
                m = NC_ID_PATTERN.search(desc)
                nc_id = m.group(1) if m else search_niconico_by_title(title, channel)

                if nc_id and nc_id in by_nc:
                    # 既にニコ動側から登録されていた場合はYouTube IDを統合
                    by_nc[nc_id]["youtube_id"] = vid
                    by_yt[vid] = by_nc[nc_id]
                    continue

                entry = {
                    "song_id": f"song_{nc_id if nc_id else vid}",
                    "title": title,
                    "producer": channel,
                    "vocal": vocal,
                    "youtube_id": vid,
                    "niconico_id": nc_id
                }
                pool.append(entry)
                by_yt[vid] = entry
                if nc_id:
                    by_nc[nc_id] = entry
        except Exception as e:
            print(f"YouTube details batch error: {e}")

    # 2. ニコニコ動画から今伸びているボカロ候補曲を収集しYouTubeとペアリング
    nc_candidates = crawl_niconico_trending()
    new_nc_ids = [cid for cid in nc_candidates if cid not in by_nc]
    print(f"ニコニコ動画トレンド探索: 候補 {len(nc_candidates)} 件 (うち新規 {len(new_nc_ids)} 件)")

    yt_search_budget = 10  # クォータ節約のためニコ動→YouTube検索フォールバックは最大10回
    for cid in new_nc_ids:
        info = get_niconico_thumbinfo(cid)
        if not info:
            continue
        raw_title = info["title"]
        desc = info["description"]
        tags = info["tags"]
        if not is_vocaloid_original(raw_title, desc, tags):
            continue

        title = clean_song_title(raw_title)
        producer = info["producer"] or "ボカロP"
        vocal = detect_vocals(f"{raw_title} {tags}")

        # ニコ動の説明文からYouTubeリンクを抽出
        m = YT_ID_PATTERN.search(desc)
        yt_id = m.group(1) if m else ""

        if not yt_id and yt_search_budget > 0:
            try:
                s_res = youtube.search().list(
                    part="snippet", q=f"{title} {producer}", type="video", maxResults=1
                ).execute()
                items = s_res.get("items", [])
                if items:
                    yt_id = items[0]["id"]["videoId"]
                yt_search_budget -= 1
            except Exception:
                pass

        if yt_id and yt_id in by_yt:
            if not by_yt[yt_id].get("niconico_id"):
                by_yt[yt_id]["niconico_id"] = cid
            by_nc[cid] = by_yt[yt_id]
            continue

        entry = {
            "song_id": f"song_{cid}",
            "title": title,
            "producer": producer,
            "vocal": vocal,
            "youtube_id": yt_id,
            "niconico_id": cid
        }
        pool.append(entry)
        by_nc[cid] = entry
        if yt_id:
            by_yt[yt_id] = entry

    # 3. 既存プール内でニコ動IDが未特定のものがあれば再照合
    for song in pool[:40]:
        if song.get("youtube_id") and not song.get("niconico_id"):
            found_nc = search_niconico_by_title(song["title"], song["producer"])
            if found_nc and found_nc not in by_nc:
                song["niconico_id"] = found_nc
                by_nc[found_nc] = song

    MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

    print(f"自動トラッキングプール更新完了: 現在 {len(pool)} 曲を監視中")

if __name__ == "__main__":
    main()