import json
import os
import re
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from config import MASTER_FILE

USER_AGENT = "VocaloidCombinedChartBot/4.0"

STRICT_VOCAL_NAMES = [
    "初音ミク", "重音テト", "重音テトSV", "GUMI", "可不", "鏡音リン", "鏡音レン",
    "巡音ルカ", "v_flower", "flower", "Ci flower", "IA", "歌愛ユキ", "ずんだもん",
    "星界", "裏命", "狐子", "足立レイ", "音街ウナ", "結月ゆかり", "紲星あかり",
    "KAITO", "MEIKO", "神威がくぽ", "知声", "ナースロボ＿タイプＴ", "琴葉姉妹", "春歌ナナ"
]

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

# タイトル内の『初音ミク』『オリジナル曲PV』など曲名ではない装飾括弧を判定するパターン
META_BRACKET_RE = re.compile(
    r"^(?:初音ミク|重音テト|重音テトSV|GUMI|可不|鏡音リン|鏡音レン|巡音ルカ|flower|v_flower|IA|歌愛ユキ|ずんだもん|足立レイ|VOCALOID|ボカロ|"
    r"オリジナル|オリジナル曲|オリジナル曲PV|PV|MV|Official|Music\s*Video|公式|新曲|歌愛ユキ・初音ミク)+$",
    re.IGNORECASE
)

YT_ID_PATTERN = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)
NC_ID_PATTERN = re.compile(r"(sm\d{7,9})")
ISO_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")

def parse_iso_duration_seconds(duration_str: str) -> int:
    if not duration_str:
        return 0
    m = ISO_DURATION_RE.match(duration_str)
    if not m:
        return 0
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)

def is_valid_vocaloid_mv(title: str, description: str = "", tags: str = "", duration_sec: int = 180) -> bool:
    if duration_sec < 95 or duration_sec > 420:
        return False

    t_low = title.lower()
    d_low = description.lower()
    tags_low = tags.lower()

    for ng in NG_KEYWORDS:
        if ng in t_low or ng in tags_low:
            return False

    if "#shorts" in d_low or "mikumikudance" in d_low or "yyb式" in d_low or "tda式" in d_low:
        return False

    if re.search(r"\b(cover|covered by|歌:|vocal:.*歌い手)\b", t_low):
        return False

    title_and_tags = f"{title} {tags}"
    has_vocal = any(v in title_and_tags for v in STRICT_VOCAL_NAMES) or any(
        k in title_and_tags.lower() for k in ["vocaloid", "ボカロ", "synthesizer v", "cevio", "utau", "voicevox", "初音ミク", "重音テト"]
    )
    return has_vocal

def normalize_compare_str(s: str) -> str:
    return re.sub(r"[\s\*\-\_・／/!！?？pPチャンネルchannelofficial]", "", s.lower())

def clean_song_title(raw_title: str, producer: str = "") -> str:
    """
    『DECO*27 - ヒバナ feat. 初音ミク』『ハチ MV「砂の惑星」』『『初音ミク』千本桜『オリジナル曲PV』』
    などの多様なタイトルから、アーティスト名や装飾を除外して純粋な楽曲名のみを抽出する。
    """
    t = raw_title.strip()

    # 1. 【...】や[...]を除去
    t = re.sub(r"【[^】]*】|\[[^\]]*\]", " ", t)

    # 2. 『...』や「...」のうち、中身がボーカル名や「オリジナル曲PV」「MV」等のメタ情報なら丸ごと除去し、曲名なら中身を取り出す
    def replace_quotes(m):
        inner = m.group(1).strip()
        if META_BRACKET_RE.match(re.sub(r"[\s・&＆/／]", "", inner)):
            return " "
        return f" 「{inner}」 "

    t = re.sub(r"[『「]([^』」]+)[』」]", replace_quotes, t)

    # 「ハチ MV 「砂の惑星」」のようにカギ括弧で曲名が明示されている場合はその中身を優先抽出
    quoted_titles = re.findall(r"「([^」]+)」", t)
    if len(quoted_titles) == 1 and len(quoted_titles[0]) >= 2:
        cand = quoted_titles[0].strip()
        if not META_BRACKET_RE.match(cand):
            return cand

    t = t.replace("「", "").replace("」", "")

    # 3. feat. / ft. / Vocal 以降をカット
    t = re.sub(r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\([^)]*(?:MV|Official|Music Video|初音ミク|重音テト|可不|GUMI|flower|足立レイ|歌愛ユキ|鏡音)[^)]*\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"#\S+", "", t)

    # 4. 「DECO*27 - ヒバナ」や「曲名 / ボカロP名」の分割処理（ボカロP名側を絶対に選ばない）
    prod_norm = normalize_compare_str(producer) if producer else ""
    for sep in [" / ", " ／ ", " - ", " ― ", " – "]:
        if sep in t:
            parts = [p.strip() for p in t.split(sep) if p.strip()]
            if len(parts) >= 2:
                filtered = []
                for p in parts:
                    p_norm = normalize_compare_str(p)
                    # ボカロP名と一致するパーツや「MV」「初音ミク」だけのパーツを除外
                    if prod_norm and (p_norm == prod_norm or p_norm in prod_norm or prod_norm in p_norm):
                        continue
                    if META_BRACKET_RE.match(re.sub(r"[\s・]", "", p)):
                        continue
                    filtered.append(p)
                if filtered:
                    t = filtered[0]
                    break

    # 5. 先頭・末尾に残った「MV」「オリジナル曲PV」「初音ミク」等のゴミを除去
    t = re.sub(r"^(?:公式|Official\s*MV|MV|PV)\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*(?:オリジナル曲PV|オリジナル曲|オリジナルPV|Official\s*MV|Music\s*Video|MV|PV)$", "", t, flags=re.IGNORECASE)

    return t.strip() or raw_title.strip()

def detect_vocals(text: str) -> str:
    found = [v for v in STRICT_VOCAL_NAMES if v in text]
    return "・".join(dict.fromkeys(found))[:25] if found else "VOCALOID"

def lookup_vocadb_by_pv(service: str, pv_id: str) -> dict:
    """
    VocaDB APIに動画ID(sm番号 または YouTube ID)を照会し、
    正式な曲名・ボカロP名・YouTube公式ID・ニコ動公式IDを一括取得する（APIクォータ消費ゼロ）
    """
    if not pv_id:
        return {}
    url = "https://vocadb.net/api/songs/byPv"
    params = {
        "pvService": service,  # "NicoNicoDouga" or "Youtube"
        "pvId": pv_id,
        "fields": "PVs,Artists",
        "lang": "Japanese"
    }
    try:
        res = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=8)
        if res.status_code == 200 and res.text and res.text != "null":
            data = res.json()
            if not data or not isinstance(data, dict):
                return {}
            # オリジナル曲またはリミックスのみ対象（カバー等は除外）
            song_type = data.get("songType", "")
            if song_type not in ["Original", "Remaster", "Remix", ""]:
                return {}

            yt_id = ""
            nc_id = ""
            for pv in data.get("pvs", []):
                if pv.get("pvType") == "Original" and not pv.get("disabled", False):
                    if pv.get("service") == "Youtube" and not yt_id:
                        yt_id = pv.get("pvId", "")
                    elif pv.get("service") == "NicoNicoDouga" and not nc_id:
                        nc_id = pv.get("pvId", "")

            # アーティスト文字列からプロデューサー名を抽出
            artist_str = data.get("artistString", "")
            producer = artist_str.split(" feat.")[0].strip() if " feat." in artist_str else artist_str

            return {
                "title": data.get("name", ""),
                "producer": producer,
                "youtube_id": yt_id,
                "niconico_id": nc_id
            }
    except Exception:
        pass
    return {}

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

def crawl_niconico_candidates() -> list:
    """ニコニコ動画で現在ポイントを伸ばしているボカロ曲を新譜〜中長期まで幅広く収集"""
    nc_ids = []
    headers = {"User-Agent": USER_AGENT}

    rss_urls = [
        "https://www.nicovideo.jp/tag/VOCALOID?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/VOCALOID?sort=m&order=d&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E3%83%9C%E3%82%AB%E3%83%AD%E3%82%AA%E3%83%AA%E3%82%B8%E3%83%8A%E3%83%AB%E6%9B%B2?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E5%88%9D%E9%9F%B3%E3%83%9F%E3%82%AF?sort=h&rss=2.0&lang=ja-jp",
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
    now = datetime.now(timezone.utc)
    d10 = (now - timedelta(days=10)).strftime("%Y-%m-%dT00:00:00+09:00")
    d30 = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00+09:00")
    d90 = (now - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00+09:00")

    snap_plans = [
        {"_sort": "-mylistCounter", "filters[startTime][gte]": d10, "_limit": 45},
        {"_sort": "-viewCounter", "filters[startTime][gte]": d10, "_limit": 45},
        {"_sort": "-mylistCounter", "filters[startTime][gte]": d30, "_limit": 40},
        {"_sort": "-viewCounter", "filters[startTime][gte]": d90, "_limit": 35},
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

    return nc_ids[:110]

def search_youtube_official_mv(youtube, title: str, producer: str) -> str:
    """VocaDBや概要欄にリンクがない新曲について、YouTube APIで公式MVのIDを検索"""
    try:
        q_str = f"{title} {producer}"
        res = youtube.search().list(
            part="snippet",
            q=q_str,
            type="video",
            videoDuration="medium",
            maxResults=3
        ).execute()
        for item in res.get("items", []):
            vid = item["id"]["videoId"]
            cand_title = item["snippet"]["title"]
            cand_low = cand_title.lower()
            if any(ng in cand_low for ng in ["歌ってみた", "cover", "カラオケ", "#shorts", "mmd", "マイクラ"]):
                continue
            if title.lower() in cand_low or normalize_compare_str(title) in normalize_compare_str(cand_title):
                return vid
    except Exception as e:
        print(f"YouTube search fallback warning ({title}): {e}")
    return ""

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("エラー: YOUTUBE_API_KEY が設定されていません。")
        return

    youtube = build("youtube", "v3", developerKey=api_key)

    # 1. 既存プールを読み込み、タイトル表記バグやYouTube ID欠損を修復する
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
    yt_search_calls = 0
    MAX_YT_SEARCH = 35

    for s in raw_pool:
        yid = s.get("youtube_id", "")
        nid = s.get("niconico_id", "")
        if (yid and yid in by_yt) or (nid and nid in by_nc):
            continue

        # VocaDBで正式曲名と欠損IDを照会
        vdb = lookup_vocadb_by_pv("NicoNicoDouga", nid) if nid else lookup_vocadb_by_pv("Youtube", yid)
        if vdb:
            if vdb.get("title"):
                s["title"] = vdb["title"]
            if vdb.get("producer") and (not s.get("producer") or s.get("producer") == "ボカロP"):
                s["producer"] = vdb["producer"]
            if not yid and vdb.get("youtube_id"):
                yid = vdb["youtube_id"]
            if not nid and vdb.get("niconico_id"):
                nid = vdb["niconico_id"]

        # まだYouTube IDが空欄の場合、ニコ動説明文またはYouTube検索で補完
        if not yid and nid:
            nc_info = get_niconico_thumbinfo(nid)
            if nc_info:
                s["title"] = vdb.get("title") or clean_song_title(nc_info["title"], nc_info["producer"])
                m = YT_ID_PATTERN.search(nc_info["description"])
                if m:
                    yid = m.group(1)
                elif yt_search_calls < MAX_YT_SEARCH:
                    yid = search_youtube_official_mv(youtube, s["title"], s.get("producer", ""))
                    yt_search_calls += 1

        # タイトルがボカロP名と同じになっている等の表記バグをクリーニング
        s["title"] = clean_song_title(s["title"], s.get("producer", ""))
        s["youtube_id"] = yid
        s["niconico_id"] = nid

        clean_pool.append(s)
        if yid:
            by_yt[yid] = s
        if nid:
            by_nc[nid] = s

    # 2. ニコニコ動画のトレンド候補曲を探索し、VocaDB＋YouTubeとペアリング
    nc_candidates = crawl_niconico_candidates()
    new_nc_ids = [cid for cid in nc_candidates if cid not in by_nc]
    print(f"ニコニコ動画トレンド探索: 新規候補 {len(new_nc_ids)} 件")

    for cid in new_nc_ids:
        nc_info = get_niconico_thumbinfo(cid)
        if not nc_info:
            continue
        if not is_valid_vocaloid_mv(nc_info["title"], nc_info["description"], nc_info["tags"], nc_info["duration_sec"]):
            continue

        vdb = lookup_vocadb_by_pv("NicoNicoDouga", cid)
        producer = vdb.get("producer") or nc_info["producer"] or "ボカロP"
        title = vdb.get("title") or clean_song_title(nc_info["title"], producer)
        vocal = detect_vocals(f"{nc_info['title']} {nc_info['tags']}")

        # YouTube IDの特定: ①VocaDB -> ②ニコ動説明文リンク -> ③YouTube検索API
        yt_id = vdb.get("youtube_id", "")
        if not yt_id:
            m = YT_ID_PATTERN.search(nc_info["description"])
            if m:
                yt_id = m.group(1)
            elif yt_search_calls < MAX_YT_SEARCH:
                yt_id = search_youtube_official_mv(youtube, title, producer)
                yt_search_calls += 1

        if yt_id and yt_id in by_yt:
            by_yt[yt_id]["niconico_id"] = cid
            by_yt[yt_id]["title"] = title
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

    MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_pool, f, ensure_ascii=False, indent=2)

    both_count = sum(1 for x in clean_pool if x.get("youtube_id") and x.get("niconico_id"))
    print(f"トラッキングプール更新完了: 全 {len(clean_pool)} 曲 (うちYouTube×ニコ動ペア完了: {both_count} 曲)")

if __name__ == "__main__":
    main()