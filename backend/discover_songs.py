import json
import os
import re
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from config import MASTER_FILE

USER_AGENT = "VocaloidCombinedChartBot/5.0"

# 日・韓・英の多言語ボーカル名辞書（正規化マップ）
VOCAL_SYNONYMS = {
    "初音ミク": ["初音ミク", "하츠네 미쿠", "hatsune miku", "miku"],
    "重音テト": ["重音テト", "重音テトSV", "카사네 테토", "kasane teto", "teto"],
    "GUMI": ["gumi", "구미", "megpoid"],
    "可不": ["可不", "kafu", "카후"],
    "鏡音リン": ["鏡音リン", "카가미네 린", "kagamine rin"],
    "鏡音レン": ["鏡音レン", "카가미네 렌", "kagamine len"],
    "巡音ルカ": ["巡音ルカ", "메구리네 루카", "megurine luka"],
    "v_flower": ["v_flower", "flower", "플라워"],
    "IA": ["ia", "이아"],
    "歌愛ユキ": ["歌愛ユキ", "카아이 유키", "kaai yuki"],
    "ずんだもん": ["ずんだもん", "준단몬", "zundamon"],
    "足立レイ": ["足立レイ", "아다치 레이", "adachi rei"],
    "星界": ["星界", "sekai"],
    "音街ウナ": ["音街ウナ", "otomachi una"],
    "結月ゆかり": ["結月ゆかり", "yuzuki yukari"],
    "KAITO": ["kaito", "카이토"],
    "MEIKO": ["meiko", "메이코"],
    "Yi Xi": ["yi xi", "이시"],
    "SeeU": ["seeu", "시유"],
    "UNI": ["uni", "유니"]
}

# グローバル＋国内の主要ヒット・新譜シード（取りこぼし防止＆海外バイラル捕捉用）
GLOBAL_AND_DOMESTIC_SEEDS = [
    {"title": "ヤラララ (YARARARA)", "producer": "ABM (AnythingBecomeMoe)", "vocal": "重音テト", "youtube_id": "T24rF_x0TmQ", "niconico_id": "sm46354721"},
    {"title": "처형박수 (Execution Clap)", "producer": "TRAP CHICK", "vocal": "重音テト", "youtube_id": "YcxhmHEykPg", "niconico_id": ""},
    {"title": "惑星直列", "producer": "いよわ", "vocal": "足立レイ", "youtube_id": "hL9W5TSUfwM", "niconico_id": "sm46891435"},
    {"title": "ご主人様、ロックのお時間にございます", "producer": "Neru", "vocal": "鏡音リン・鏡音レン", "youtube_id": "", "niconico_id": ""},
    {"title": "マイバッド", "producer": "はるまきごはん", "vocal": "初音ミク", "youtube_id": "", "niconico_id": ""},
    {"title": "Yoyo2", "producer": "r-906", "vocal": "初音ミク", "youtube_id": "", "niconico_id": ""},
    {"title": "えねみぃ", "producer": "ピノキオピー", "vocal": "初音ミク・重音テト", "youtube_id": "", "niconico_id": ""},
    {"title": "肆足歩行", "producer": "サツキ", "vocal": "足立レイ", "youtube_id": "", "niconico_id": ""},
    {"title": "デビットビット", "producer": "アボガド6", "vocal": "重音テト", "youtube_id": "", "niconico_id": ""},
    {"title": "もしもしも", "producer": "なきそ", "vocal": "初音ミク", "youtube_id": "", "niconico_id": ""},
    {"title": "洗脳", "producer": "DECO*27", "vocal": "初音ミク", "youtube_id": "", "niconico_id": ""},
    {"title": "メズマライザー", "producer": "サツキ", "vocal": "初音ミク・重音テト", "youtube_id": "19y8YTbvri8", "niconico_id": "sm43708803"},
    {"title": "オーバーライド", "producer": "吉田夜世", "vocal": "重音テトSV", "youtube_id": "LLjfal8jCYI", "niconico_id": "sm43083649"},
    {"title": "ラビットホール", "producer": "DECO*27", "vocal": "初音ミク", "youtube_id": "eSW2LVbPThw", "niconico_id": "sm42224358"}
]

NG_KEYWORDS = [
    "歌ってみた", "踊ってみた", "演奏してみた", "叩いてみた", "弾いてみた",
    "切り抜き", "まとめ", "メドレー", "カラオケ", "off vocal", "instrumental",
    "reaction", "リアクション", "プロセカ", "プロジェクトセカイ", "譜面",
    "耐久", "1時間", "1 hour", "作業用", "解説", "ランキング", "比較",
    "mmd", "mikumikudance", "yyb", "tda", "モデル", "モーション",
    "マイクラ", "マインクラフト", "minecraft", "再現", "レッドストーン", "音ブロック",
    "同時視聴", "初見", "配信", "live", "ライブ", "チャンネル登録", "万人ありがとう",
    "#shorts", "shorts", "ショート", "tiktok", "違い", "感性プレイ", "ホロドリ", "藤井風",
    "cover", "covered by", "커버", "불러보았다", "piano tutorial", "sheet music"
]

META_BRACKET_RE = re.compile(
    r"^(?:初音ミク|重音テト|重音テトSV|GUMI|可不|鏡音リン|鏡音レン|巡音ルカ|flower|v_flower|IA|歌愛ユキ|ずんだもん|足立レイ|"
    r"카사네\s*테토|하츠네\s*미쿠|보컬로이드|Kasane\s*Teto|Hatsune\s*Miku|VOCALOID|ボカロ|Synthesizer\s*V|SynthV|"
    r"オリジナル|オリジナル曲|オリジナル曲PV|PV|MV|Official|Music\s*Video|公式|新曲)+$",
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

def detect_vocals(text: str) -> str:
    text_low = text.lower()
    found = []
    for canonical, syns in VOCAL_SYNONYMS.items():
        for syn in syns:
            if syn.lower() in text_low:
                found.append(canonical)
                break
    return "・".join(dict.fromkeys(found))[:25] if found else "VOCALOID / 合成音声"

def is_valid_vocaloid_mv(title: str, description: str = "", tags: str = "", duration_sec: int = 180) -> bool:
    if duration_sec < 90 or duration_sec > 420:
        return False

    t_low = title.lower()
    d_low = description.lower()
    tags_low = tags.lower()

    for ng in NG_KEYWORDS:
        if ng in t_low or ng in tags_low:
            return False

    if "#shorts" in d_low or "mikumikudance" in d_low or "yyb式" in d_low or "tda式" in d_low:
        return False

    combined_low = f"{title} {tags} {description[:300]}".lower()
    has_vocal = any(
        syn.lower() in combined_low
        for syns in VOCAL_SYNONYMS.values()
        for syn in syns
    ) or any(
        k in combined_low for k in ["vocaloid", "ボカロ", "보컬로이드", "synthesizer v", "synthv", "cevio", "utau", "voicevox"]
    )
    return has_vocal

def normalize_compare_str(s: str) -> str:
    return re.sub(r"[\s\*\-\_・／/!！?？'\"pPチャンネルchannelofficialmv]", "", s.lower())

def clean_song_title(raw_title: str, producer: str = "") -> str:
    """日・韓・英の多様なMVタイトルから純粋な楽曲名を抽出"""
    t = raw_title.strip()
    t = re.sub(r"【[^】]*】|\[[^\]]*\]", " ", t).strip()

    # [MV] ABM - 'ヤラララ' (YARARARA) feat. 重音テト のようなシングルクォート形式に対応
    m_single = re.search(r"'([^']{2,40})'\s*(\([^)]{2,40}\))?", t)
    if m_single:
        base = m_single.group(1).strip()
        sub = m_single.group(2).strip() if m_single.group(2) else ""
        if not META_BRACKET_RE.match(base):
            return f"{base} {sub}".strip()

    def replace_quotes(m):
        inner = m.group(1).strip()
        if META_BRACKET_RE.match(re.sub(r"[\s・&＆/／]", "", inner)):
            return " "
        return f" 「{inner}」 "

    t = re.sub(r"[『「]([^』」]+)[』」]", replace_quotes, t)
    quoted_titles = re.findall(r"「([^」]+)」", t)
    if len(quoted_titles) == 1 and len(quoted_titles[0]) >= 2:
        cand = quoted_titles[0].strip()
        if not META_BRACKET_RE.match(cand):
            return cand

    t = t.replace("「", "").replace("」", "")
    t = re.sub(r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\([^)]*(?:MV|Official|Music Video|初音ミク|重音テト|Kasane Teto|Hatsune Miku|카사네 테토|하츠네 미쿠|可不|GUMI|flower|足立レイ|歌愛ユキ)[^)]*\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"#\S+", "", t)

    prod_norm = normalize_compare_str(producer) if producer else ""
    for sep in [" / ", " ／ ", " - ", " ― ", " – "]:
        if sep in t:
            parts = [p.strip() for p in t.split(sep) if p.strip()]
            if len(parts) >= 2:
                filtered = []
                for p in parts:
                    p_norm = normalize_compare_str(p)
                    if prod_norm and (p_norm == prod_norm or p_norm in prod_norm or prod_norm in p_norm):
                        continue
                    if META_BRACKET_RE.match(re.sub(r"[\s・]", "", p)):
                        continue
                    filtered.append(p)
                if filtered:
                    t = filtered[0]
                    break

    t = re.sub(r"^(?:公式|Official\s*MV|MV|PV)\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*(?:オリジナル曲PV|オリジナル曲|オリジナルPV|Official\s*MV|Music\s*Video|MV|PV)$", "", t, flags=re.IGNORECASE)
    return t.strip() or raw_title.strip()

def lookup_vocadb_by_pv(service: str, pv_id: str) -> dict:
    if not pv_id:
        return {}
    url = "https://vocadb.net/api/songs/byPv"
    params = {
        "pvService": service,
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
            if data.get("songType", "") not in ["Original", "Remaster", "Remix", ""]:
                return {}

            yt_id = ""
            nc_id = ""
            for pv in data.get("pvs", []):
                if pv.get("pvType") == "Original" and not pv.get("disabled", False):
                    if pv.get("service") == "Youtube" and not yt_id:
                        yt_id = pv.get("pvId", "")
                    elif pv.get("service") == "NicoNicoDouga" and not nc_id:
                        nc_id = pv.get("pvId", "")

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

def search_niconico_by_title(title: str, producer: str) -> str:
    """曲名とボカロP名からニコニコ動画のsm番号を検索"""
    headers = {"User-Agent": USER_AGENT}
    snap_url = "https://api.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
    params = {
        "q": f"{title} {producer}".strip(),
        "targets": "title,tags",
        "fields": "contentId,title",
        "_sort": "-viewCounter",
        "_limit": 3,
        "_context": USER_AGENT
    }
    try:
        res = requests.get(snap_url, params=params, headers=headers, timeout=8)
        if res.status_code == 200:
            for item in res.json().get("data", []):
                if normalize_compare_str(title) in normalize_compare_str(item.get("title", "")):
                    return item.get("contentId", "")
    except Exception:
        pass

    # RSS検索フォールバック
    try:
        q_enc = requests.utils.quote(f"{title} {producer}".strip())
        res = requests.get(
            f"https://www.nicovideo.jp/search/{q_enc}",
            params={"sort": "v", "order": "d", "rss": "2.0"},
            headers=headers,
            timeout=8
        )
        if res.status_code == 200:
            root = ET.fromstring(res.text)
            for item in root.findall("./channel/item")[:3]:
                t_cand = item.findtext("title", "")
                link = item.findtext("link", "")
                if normalize_compare_str(title) in normalize_compare_str(t_cand):
                    m = NC_ID_PATTERN.search(link)
                    if m:
                        return m.group(1)
    except Exception:
        pass
    return ""

def search_youtube_official_mv(youtube, title: str, producer: str) -> str:
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
            if any(ng in cand_low for ng in ["歌ってみた", "cover", "カラオケ", "#shorts", "mmd", "マイクラ", "1 hour"]):
                continue
            if title.lower() in cand_low or normalize_compare_str(title) in normalize_compare_str(cand_title):
                return vid
    except Exception as e:
        print(f"YouTube search warning ({title}): {e}")
    return ""

def crawl_niconico_candidates() -> list:
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
    d14 = (now - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00+09:00")
    d45 = (now - timedelta(days=45)).strftime("%Y-%m-%dT00:00:00+09:00")

    for sp in [
        {"_sort": "-mylistCounter", "filters[startTime][gte]": d14, "_limit": 45},
        {"_sort": "-viewCounter", "filters[startTime][gte]": d14, "_limit": 45},
        {"_sort": "-mylistCounter", "filters[startTime][gte]": d45, "_limit": 40},
    ]:
        params = {"q": "VOCALOID", "targets": "tagsExact", "fields": "contentId", "_context": USER_AGENT, **sp}
        try:
            res = requests.get(snap_url, params=params, headers=headers, timeout=10)
            if res.status_code == 200:
                for item in res.json().get("data", []):
                    cid = item.get("contentId")
                    if cid and cid not in nc_ids:
                        nc_ids.append(cid)
        except Exception:
            pass

    return nc_ids[:100]

def crawl_global_youtube_vocaloid(youtube) -> list:
    """日・韓・英の多言語クエリでYouTube上のグローバル・ボカロヒット＆新譜を探索"""
    now = datetime.now(timezone.utc)
    d14 = (now - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z")
    d90 = (now - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")
    d300 = (now - timedelta(days=300)).strftime("%Y-%m-%dT00:00:00Z")

    plans = [
        # 韓国ボカロP・韓国語圏のバイラル曲（카사네 테토 / 하츠네 미쿠 / 보컬로이드）
        {"q": '"카사네 테토" OR "하츠네 미쿠" OR "보컬로이드" MV -cover -커버 -shorts', "after": d300, "max": 25},
        {"q": '"카사네 테토" OR "하츠네 미쿠" -cover -커버 -shorts', "after": d90, "max": 20},
        # 英語圏・グローバルのボカロ曲（Kasane Teto / Hatsune Miku / Synthesizer V）
        {"q": '"Kasane Teto" OR "Hatsune Miku" OR "Synthesizer V" MV -cover -shorts -MMD', "after": d300, "max": 25},
        {"q": '"feat. Kasane Teto" OR "feat. Hatsune Miku" OR "feat. 重音テト" MV -cover -shorts', "after": d300, "max": 25},
        # 国内＋グローバルの直近14日新譜
        {"q": '"初音ミク" OR "重音テト" OR "可不" OR "足立レイ" MV -歌ってみた -cover -shorts -MMD', "after": d14, "max": 25},
    ]

    yt_ids = []
    for plan in plans:
        try:
            res = youtube.search().list(
                part="id",
                q=plan["q"],
                type="video",
                videoDuration="medium",
                order="viewCount",
                publishedAfter=plan["after"],
                maxResults=plan["max"]
            ).execute()
            for item in res.get("items", []):
                vid = item["id"].get("videoId")
                if vid and vid not in yt_ids:
                    yt_ids.append(vid)
        except Exception as e:
            print(f"Global YouTube search plan warning: {e}")

    return yt_ids

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("エラー: YOUTUBE_API_KEY が設定されていません。")
        return

    youtube = build("youtube", "v3", developerKey=api_key)

    raw_pool = []
    if MASTER_FILE.exists():
        try:
            with open(MASTER_FILE, "r", encoding="utf-8") as f:
                raw_pool = json.load(f)
        except json.JSONDecodeError:
            raw_pool = []

    # シード曲と既存プールをマージ
    combined_seeds = GLOBAL_AND_DOMESTIC_SEEDS + raw_pool

    clean_pool = []
    by_yt = {}
    by_nc = {}
    by_title_prod = {}
    yt_search_calls = 0
    MAX_YT_SEARCH = 45

    for s in combined_seeds:
        yid = s.get("youtube_id", "")
        nid = s.get("niconico_id", "")
        title = s.get("title", "")
        producer = s.get("producer", "")

        if (yid and yid in by_yt) or (nid and nid in by_nc):
            continue

        # VocaDB双方向照会
        vdb = {}
        if nid:
            vdb = lookup_vocadb_by_pv("NicoNicoDouga", nid)
        elif yid:
            vdb = lookup_vocadb_by_pv("Youtube", yid)

        if vdb:
            title = vdb.get("title") or title
            if vdb.get("producer") and (not producer or producer == "ボカロP"):
                producer = vdb["producer"]
            if not yid and vdb.get("youtube_id"):
                yid = vdb["youtube_id"]
            if not nid and vdb.get("niconico_id"):
                nid = vdb["niconico_id"]

        # IDが欠けている新譜・シード曲を検索補完
        if not nid and title:
            nid = search_niconico_by_title(title, producer)
        if not yid and nid:
            nc_info = get_niconico_thumbinfo(nid)
            if nc_info:
                m = YT_ID_PATTERN.search(nc_info["description"])
                if m:
                    yid = m.group(1)
        if not yid and title and yt_search_calls < MAX_YT_SEARCH:
            yid = search_youtube_official_mv(youtube, title, producer)
            yt_search_calls += 1

        if not yid and not nid:
            continue

        title = clean_song_title(title, producer)
        tp_key = f"{normalize_compare_str(title)}::{normalize_compare_str(producer)}"
        if tp_key in by_title_prod:
            existing = by_title_prod[tp_key]
            if yid and not existing.get("youtube_id"):
                existing["youtube_id"] = yid
                by_yt[yid] = existing
            if nid and not existing.get("niconico_id"):
                existing["niconico_id"] = nid
                by_nc[nid] = existing
            continue

        entry = {
            "song_id": s.get("song_id") or f"song_{nid if nid else yid}",
            "title": title,
            "producer": producer or "ボカロP",
            "vocal": s.get("vocal", "VOCALOID"),
            "youtube_id": yid,
            "niconico_id": nid
        }
        clean_pool.append(entry)
        by_title_prod[tp_key] = entry
        if yid:
            by_yt[yid] = entry
        if nid:
            by_nc[nid] = entry

    # 2. ニコニコ動画トレンド候補の追加
    nc_candidates = crawl_niconico_candidates()
    new_nc_ids = [cid for cid in nc_candidates if cid not in by_nc]
    print(f"ニコニコ動画トレンド探索: 新規候補 {len(new_nc_ids)} 件")

    for cid in new_nc_ids:
        nc_info = get_niconico_thumbinfo(cid)
        if not nc_info or not is_valid_vocaloid_mv(nc_info["title"], nc_info["description"], nc_info["tags"], nc_info["duration_sec"]):
            continue

        vdb = lookup_vocadb_by_pv("NicoNicoDouga", cid)
        producer = vdb.get("producer") or nc_info["producer"] or "ボカロP"
        title = vdb.get("title") or clean_song_title(nc_info["title"], producer)
        vocal = detect_vocals(f"{nc_info['title']} {nc_info['tags']}")

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

    # 3. グローバルYouTubeトレンド候補（韓国・英語圏・YouTube発ヒット）の追加
    yt_candidates = crawl_global_youtube_vocaloid(youtube)
    new_yt_ids = [vid for vid in yt_candidates if vid not in by_yt]
    print(f"グローバルYouTubeトレンド探索: 新規候補 {len(new_yt_ids)} 件")

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

                if not is_valid_vocaloid_mv(raw_title, desc, tags, dur_sec):
                    continue

                vdb = lookup_vocadb_by_pv("Youtube", vid)
                producer = vdb.get("producer") or channel
                title = vdb.get("title") or clean_song_title(raw_title, producer)
                vocal = detect_vocals(f"{raw_title} {tags} {desc[:200]}")

                nc_id = vdb.get("niconico_id", "")
                if not nc_id:
                    m = NC_ID_PATTERN.search(desc)
                    if m:
                        nc_id = m.group(1)

                if nc_id and nc_id in by_nc:
                    by_nc[nc_id]["youtube_id"] = vid
                    by_yt[vid] = by_nc[nc_id]
                    continue

                entry = {
                    "song_id": f"song_{nc_id if nc_id else vid}",
                    "title": title,
                    "producer": producer,
                    "vocal": vocal,
                    "youtube_id": vid,
                    "niconico_id": nc_id
                }
                clean_pool.append(entry)
                by_yt[vid] = entry
                if nc_id:
                    by_nc[nc_id] = entry
        except Exception as e:
            print(f"Global YouTube batch error: {e}")

    MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_pool, f, ensure_ascii=False, indent=2)

    print(f"グローバルトラッキングプール更新完了: 全 {len(clean_pool)} 曲を監視中")

if __name__ == "__main__":
    main()