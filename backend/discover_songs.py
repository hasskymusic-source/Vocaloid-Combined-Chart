import json
import os
import re
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from config import MASTER_FILE

USER_AGENT = "VocaloidCombinedChartBot/3.0"

# 明確な合成音声ライブラリ名（「flower」単体は一般名詞と衝突するため「v_flower」等で判定）
STRICT_VOCAL_NAMES = [
    "初音ミク", "重音テト", "重音テトSV", "GUMI", "可不", "鏡音リン", "鏡音レン",
    "巡音ルカ", "v_flower", "Ci flower", "IA", "歌愛ユキ", "ずんだもん", "星界",
    "裏命", "狐子", "足立レイ", "音街ウナ", "結月ゆかり", "紲星あかり",
    "KAITO", "MEIKO", "神威がくぽ", "知声", "ナースロボ＿タイプＴ", "琴葉姉妹", "春歌ナナ"
]

# 徹底排除する非オリジナル・二次創作・Shorts・企画動画のNGワード
NG_KEYWORDS = [
    "歌ってみた", "踊ってみた", "演奏してみた", "叩いてみた", "弾いてみた",
    "切り抜き", "まとめ", "メドレー", "カラオケ", "off vocal", "instrumental",
    "reaction", "リアクション", "プロセカ", "プロジェクトセカイ", "譜面",
    "耐久", "1時間", "作業用", "解説", "ランキング", "比較",
    "mmd", "mikumikudance", "yyb", "tda", "モデル", "モーション",
    "マイクラ", "マインクラフト", "minecraft", "再現", "レッドストーン", "音ブロック",
    "同時視聴", "初見", "配信", "live", "ライブ", "チャンネル登録", "万人ありがとう",
    "#shorts", "shorts", "ショート", "tiktok", "違い", "感性プレイ", "ホロドリ", "藤井風"
]

YT_ID_PATTERN = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)
NC_ID_PATTERN = re.compile(r"(sm\d{7,9})")
ISO_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")

# カタログ・ロングヒットの基準アンカー（Billboard常連曲の正確なIDペア）
CORE_CATALOG_ANCHORS = [
    {"title": "惑星直列", "producer": "いよわ", "vocal": "足立レイ", "youtube_id": "hL9W5TSUfwM", "niconico_id": "sm46891435"},
    {"title": "メズマライザー", "producer": "サツキ", "vocal": "初音ミク・重音テト", "youtube_id": "19y8YTbvri8", "niconico_id": "sm43708803"},
    {"title": "オーバーライド", "producer": "吉田夜世", "vocal": "重音テトSV", "youtube_id": "LLjfal8jCYI", "niconico_id": "sm43083649"},
    {"title": "ラビットホール", "producer": "DECO*27", "vocal": "初音ミク", "youtube_id": "eSW2LVbPThw", "niconico_id": "sm42224358"},
    {"title": "神っぽいな", "producer": "ピノキオピー", "vocal": "初音ミク", "youtube_id": "EHBFKhLUVig", "niconico_id": "sm39334235"},
    {"title": "アンノウン・マザーグース", "producer": "wowaka", "vocal": "初音ミク", "youtube_id": "P_CSdxSGfaA", "niconico_id": "sm31791630"},
    {"title": "シャンティ", "producer": "wotaku", "vocal": "KAITO", "youtube_id": "qT1k2hQ7H2I", "niconico_id": "sm39356749"}
]

def parse_iso_duration_seconds(duration_str: str) -> int:
    """YouTubeのISO 8601再生時間(PT3M20S等)を秒数に変換"""
    if not duration_str:
        return 0
    m = ISO_DURATION_RE.match(duration_str)
    if not m:
        return 0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds

def is_valid_vocaloid_mv(title: str, description: str = "", tags: str = "", duration_sec: int = 180, category_id: str = "10") -> bool:
    """
    Shorts・MMD・二次創作・無関係動画を完全に弾き、ボカロオリジナルMVのみを通す厳格フィルタ
    """
    # 1. 再生時間チェック：100秒未満(Shorts等) または 420秒(7分)超(配信・まとめ等)は除外
    if duration_sec < 100 or duration_sec > 420:
        return False

    t_low = title.lower()
    d_low = description.lower()
    tags_low = tags.lower()

    # 2. タイトルとタグにNGワードが含まれていたら即除外
    for ng in NG_KEYWORDS:
        if ng in t_low or ng in tags_low:
            return False

    # 概要欄に #shorts や MMDモデルクレジットがある場合も除外
    if "#shorts" in d_low or "mikumikudance" in d_low or "yyb式" in d_low or "tda式" in d_low:
        return False

    # カバー・歌ってみた表記の除外
    if re.search(r"\b(cover|covered by|歌:|vocal:.*歌い手)\b", t_low):
        return False

    # 3. タイトルまたはタグに明確なボカロ・合成音声キーワードが含まれているか確認
    title_and_tags = f"{title} {tags}"
    has_strict_vocal = any(v in title_and_tags for v in STRICT_VOCAL_NAMES) or any(
        k in title_and_tags.lower() for k in ["vocaloid", "ボカロ", "synthesizer v", "cevio", "utau", "voicevox", "初音ミク", "重音テト"]
    )
    return has_strict_vocal

def clean_song_title(raw_title: str) -> str:
    t = re.sub(r"【[^】]*】|\[[^\]]*\]|『[^』]*』", lambda m: m.group(0)[1:-1] if m.group(0).startswith("『") else "", raw_title)
    t = re.sub(r"\([^)]*(?:MV|Official|Music Video|初音ミク|重音テト|可不|GUMI|flower)[^)]*\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"#\S+", "", t)  # ハッシュタグを除去
    for sep in [" / ", " ／ ", " - ", " feat.", " ft.", " Feat."]:
        if sep in t:
            parts = [p.strip() for p in t.split(sep) if p.strip()]
            if parts:
                t = parts[0]
                break
    return t.strip() or raw_title.strip()

def detect_vocals(text: str) -> str:
    found = [v for v in STRICT_VOCAL_NAMES if v in text]
    if "flower" in text.lower() and "v_flower" not in found:
        found.append("flower")
    return "・".join(dict.fromkeys(found))[:25] if found else "VOCALOID"

def get_niconico_thumbinfo(nc_id: str) -> dict:
    if not nc_id:
        return {}
    url = f"https://ext.nicovideo.jp/api/getthumbinfo/{nc_id}"
    try:
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        root = ET.fromstring(res.text)
        if root.attrib.get("status") == "ok":
            thumb = root.find("thumb")
            tags = " ".join([t.text for t in thumb.findall("tags/tag") if t.text])
            length_str = thumb.findtext("length", "3:00")
            parts = length_str.split(":")
            dur_sec = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 180
            return {
                "nc_id": nc_id,
                "title": thumb.findtext("title", ""),
                "description": thumb.findtext("description", ""),
                "tags": tags,
                "producer": thumb.findtext("user_nickname", ""),
                "published_at": thumb.findtext("first_retrieve", ""),
                "duration_sec": dur_sec
            }
    except Exception:
        pass
    return {}

def is_same_song_pair(yt_title: str, yt_pub: str, nc_info: dict) -> bool:
    """
    【重要】二次創作動画が原曲(本家)のsm番号を概要欄に貼っているケース(GETCHA問題)をブロックする。
    1. ニコ動側がボカロオリジナル曲として有効か確認
    2. YouTubeとニコ動の投稿日が120日以上離れている場合は「二次創作または別動画」とみなしてペアリング拒否
    """
    if not nc_info:
        return False
    if not is_valid_vocaloid_mv(nc_info["title"], nc_info["description"], nc_info["tags"], nc_info["duration_sec"]):
        return False

    try:
        if yt_pub and nc_info.get("published_at"):
            yt_dt = datetime.fromisoformat(yt_pub.replace("Z", "+00:00"))
            nc_dt = datetime.fromisoformat(nc_info["published_at"].replace("Z", "+00:00"))
            diff_days = abs((yt_dt - nc_dt).total_seconds()) / 86400.0
            if diff_days > 120:
                print(f"ペアリング拒否(投稿日乖離 {int(diff_days)}日): YT='{yt_title}' / NC='{nc_info['title']}'")
                return False
    except Exception:
        pass

    return True

def crawl_niconico_vocaloid_songs() -> list:
    """BillboardのニコニコVOCALOID SONGSと同様に、ニコ動で伸びているボカロ曲sm番号を幅広く収集"""
    nc_ids = []
    headers = {"User-Agent": USER_AGENT}

    rss_urls = [
        "https://www.nicovideo.jp/tag/VOCALOID?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/VOCALOID?sort=m&order=d&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/VOCALOID?sort=v&order=d&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E3%83%9C%E3%82%AB%E3%83%AD%E3%82%AA%E3%83%AA%E3%82%B8%E3%83%8A%E3%83%AB%E6%9B%B2?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E3%83%9F%E3%82%AF%E3%82%AA%E3%83%AA%E3%82%B8%E3%83%8A%E3%83%AB%E6%9B%B2?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E9%87%8D%E9%9F%B3%E3%83%86%E3%83%88?sort=h&rss=2.0&lang=ja-jp"
    ]
    for r_url in rss_urls:
        try:
            res = requests.get(r_url, headers=headers, timeout=10)
            if res.status_code == 200:
                for cid in NC_ID_PATTERN.findall(res.text):
                    if cid not in nc_ids:
                        nc_ids.append(cid)
        except Exception:
            pass

    snap_url = "https://api.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
    d14 = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00+09:00")
    d60 = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00+09:00")
    snap_plans = [
        {"_sort": "-mylistCounter", "filters[startTime][gte]": d14, "_limit": 40},
        {"_sort": "-viewCounter", "filters[startTime][gte]": d14, "_limit": 40},
        {"_sort": "-mylistCounter", "filters[startTime][gte]": d60, "_limit": 40},
        {"_sort": "-viewCounter", "_limit": 30}
    ]
    for sp in snap_plans:
        params = {
            "q": "VOCALOID",
            "targets": "tagsExact",
            "fields": "contentId",
            "_context": USER_AGENT,
            **sp
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

    return nc_ids[:90]

def crawl_youtube_vocaloid_mvs(youtube) -> list:
    """YouTubeの音楽カテゴリ(categoryId=10)・中尺動画(videoDuration=medium)に限定してボカロMVを探索"""
    now = datetime.now(timezone.utc)
    d10 = (now - timedelta(days=10)).strftime("%Y-%m-%dT00:00:00Z")
    d45 = (now - timedelta(days=45)).strftime("%Y-%m-%dT00:00:00Z")

    search_plans = [
        {"q": '"初音ミク" OR "重音テト" OR "VOCALOID" "nicovideo.jp/watch/sm" -shorts -MMD -cover', "after": d10, "max": 30},
        {"q": '"初音ミク" OR "重音テト" OR "可不" OR "足立レイ" MV -歌ってみた -cover -shorts -MMD', "after": d10, "max": 25},
        {"q": '"初音ミク" OR "重音テト" OR "VOCALOID" "nicovideo.jp/watch/sm" -shorts -MMD -cover', "after": d45, "max": 30},
    ]

    discovered_yt_ids = []
    for plan in search_plans:
        try:
            res = youtube.search().list(
                part="id",
                q=plan["q"],
                type="video",
                videoCategoryId="10",      # 音楽カテゴリのみに厳格制限
                videoDuration="medium",    # 4分未満のShorts(60秒以下含む)をAPIレベルでも抑制
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

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("エラー: YOUTUBE_API_KEY が設定されていません。")
        return

    youtube = build("youtube", "v3", developerKey=api_key)

    # 1. 既存プールを読み込み、汚染データ（GETCHA MMDやShorts等）を浄化する
    raw_pool = []
    if MASTER_FILE.exists():
        try:
            with open(MASTER_FILE, "r", encoding="utf-8") as f:
                raw_pool = json.load(f)
        except json.JSONDecodeError:
            raw_pool = []

    clean_pool = []
    by_yt = {}
    by_nc = {}

    # コア・アンカー曲を登録
    for anchor in CORE_CATALOG_ANCHORS:
        sid = f"song_{anchor['niconico_id']}"
        entry = {"song_id": sid, **anchor}
        clean_pool.append(entry)
        by_yt[anchor["youtube_id"]] = entry
        by_nc[anchor["niconico_id"]] = entry

    # 既存プールの厳格チェック（動画尺・NGワード・投稿日整合性を再検証）
    existing_yt_ids = [s.get("youtube_id") for s in raw_pool if s.get("youtube_id") and s.get("youtube_id") not in by_yt]
    yt_meta_map = {}
    for i in range(0, len(existing_yt_ids), 50):
        chunk = existing_yt_ids[i:i+50]
        try:
            res = youtube.videos().list(part="snippet,contentDetails", id=",".join(chunk)).execute()
            for item in res.get("items", []):
                yt_meta_map[item["id"]] = item
        except Exception:
            pass

    for s in raw_pool:
        yid = s.get("youtube_id", "")
        nid = s.get("niconico_id", "")
        if (yid and yid in by_yt) or (nid and nid in by_nc):
            continue

        yt_item = yt_meta_map.get(yid)
        if not yt_item:
            continue
        snippet = yt_item.get("snippet", {})
        dur_sec = parse_iso_duration_seconds(yt_item.get("contentDetails", {}).get("duration", ""))
        raw_title = snippet.get("title", "")
        desc = snippet.get("description", "")
        tags = " ".join(snippet.get("tags", []))

        if not is_valid_vocaloid_mv(raw_title, desc, tags, dur_sec):
            print(f"ノイズ動画を除外しました: {raw_title}")
            continue

        # ニコ動IDが紐付いている場合、本家ハイジャックでないか検証
        if nid:
            nc_info = get_niconico_thumbinfo(nid)
            if not is_same_song_pair(raw_title, snippet.get("publishedAt", ""), nc_info):
                nid = ""  # 不正な紐付けを解除

        s["title"] = clean_song_title(raw_title)
        s["niconico_id"] = nid
        clean_pool.append(s)
        by_yt[yid] = s
        if nid:
            by_nc[nid] = s

    # 2. ニコニコ動画のトレンド曲から探索（Billboard VOCALOID SONGSと高い親和性）
    nc_candidates = crawl_niconico_vocaloid_songs()
    new_nc_ids = [cid for cid in nc_candidates if cid not in by_nc]
    print(f"ニコニコ動画トレンド探索: 新規候補 {len(new_nc_ids)} 件")

    yt_search_budget = 18
    for cid in new_nc_ids:
        nc_info = get_niconico_thumbinfo(cid)
        if not nc_info:
            continue
        if not is_valid_vocaloid_mv(nc_info["title"], nc_info["description"], nc_info["tags"], nc_info["duration_sec"]):
            continue

        title = clean_song_title(nc_info["title"])
        producer = nc_info["producer"] or "ボカロP"
        vocal = detect_vocals(f"{nc_info['title']} {nc_info['tags']}")

        # ニコ動の説明文からYouTube公式MVのIDを抽出
        m = YT_ID_PATTERN.search(nc_info["description"])
        yt_id = m.group(1) if m else ""

        # 説明文にリンクがない場合、曲名＋ボカロP名でYouTube公式MVを検索
        if not yt_id and yt_search_budget > 0:
            try:
                s_res = youtube.search().list(
                    part="snippet",
                    q=f'"{title}" "{producer}"',
                    type="video",
                    videoCategoryId="10",
                    maxResults=1
                ).execute()
                items = s_res.get("items", [])
                if items:
                    cand_vid = items[0]["id"]["videoId"]
                    cand_title = items[0]["snippet"]["title"]
                    if title.lower() in cand_title.lower() and is_valid_vocaloid_mv(cand_title, "", "", 180):
                        yt_id = cand_vid
                yt_search_budget -= 1
            except Exception:
                pass

        if yt_id and yt_id in by_yt:
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
        clean_pool.append(entry)
        by_nc[cid] = entry
        if yt_id:
            by_yt[yt_id] = entry

    # 3. YouTube側の新着ボカロMVから探索（動画尺100〜420秒＆ペアリング整合性チェック付き）
    yt_candidates = crawl_youtube_vocaloid_mvs(youtube)
    new_yt_ids = [vid for vid in yt_candidates if vid not in by_yt]
    print(f"YouTubeトレンド探索: 新規候補 {len(new_yt_ids)} 件")

    for i in range(0, len(new_yt_ids), 50):
        chunk = new_yt_ids[i:i+50]
        try:
            v_res = youtube.videos().list(part="snippet,contentDetails", id=",".join(chunk)).execute()
            for item in v_res.get("items", []):
                vid = item["id"]
                snippet = item.get("snippet", {})
                dur_sec = parse_iso_duration_seconds(item.get("contentDetails", {}).get("duration", ""))
                raw_title = snippet.get("title", "")
                desc = snippet.get("description", "")
                tags = " ".join(snippet.get("tags", []))
                channel = snippet.get("channelTitle", "ボカロP")
                yt_pub = snippet.get("publishedAt", "")

                if not is_valid_vocaloid_mv(raw_title, desc, tags, dur_sec):
                    continue

                title = clean_song_title(raw_title)
                vocal = detect_vocals(f"{raw_title} {desc} {tags}")

                # 概要欄にsm番号がある場合、本家ハイジャックでないか検証してから紐付け
                m = NC_ID_PATTERN.search(desc)
                nc_id = ""
                if m:
                    cand_nc = m.group(1)
                    nc_info = get_niconico_thumbinfo(cand_nc)
                    if is_same_song_pair(raw_title, yt_pub, nc_info):
                        nc_id = cand_nc

                if nc_id and nc_id in by_nc:
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
                clean_pool.append(entry)
                by_yt[vid] = entry
                if nc_id:
                    by_nc[nc_id] = entry
        except Exception as e:
            print(f"YouTube details batch error: {e}")

    MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_pool, f, ensure_ascii=False, indent=2)

    print(f"クリーンなトラッキングプール更新完了: 全 {len(clean_pool)} 曲を監視中")

if __name__ == "__main__":
    main()