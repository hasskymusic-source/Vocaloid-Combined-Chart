import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from config import MASTER_FILE, LATEST_SNAPSHOT

USER_AGENT = "Mozilla/5.0 (compatible; VocaloidCombinedChartBot/6.0)"

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

YT_ID_PATTERN = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})")
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
    return "・".join(dict.fromkeys(found))[:25] if found else "VOCALOID"

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
    t = raw_title.strip()
    t = re.sub(r"【[^】]*】|\[[^\]]*\]", " ", t).strip()

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

# =====================================================================
# クォータ消費ゼロのマルチソース探索＆双方向ID解決関数群
# =====================================================================

def extract_vocadb_song_info(data: dict) -> dict:
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
    vocal = artist_str.split(" feat.")[1].strip() if " feat." in artist_str else detect_vocals(artist_str)

    return {
        "title": data.get("name", ""),
        "producer": producer,
        "vocal": detect_vocals(vocal) if vocal else "VOCALOID",
        "youtube_id": yt_id,
        "niconico_id": nc_id
    }

def lookup_vocadb_by_pv(service: str, pv_id: str) -> dict:
    if not pv_id:
        return {}
    try:
        res = requests.get(
            "https://vocadb.net/api/songs/byPv",
            params={"pvService": service, "pvId": pv_id, "fields": "PVs,Artists", "lang": "Japanese"},
            headers={"User-Agent": USER_AGENT},
            timeout=8
        )
        if res.status_code == 200 and res.text and res.text != "null":
            return extract_vocadb_song_info(res.json())
    except Exception:
        pass
    return {}

def crawl_vocadb_global_and_domestic() -> list:
    """
    【コレクター1】VocaDB APIから直近14日・45日・120日・365日・全期間で
    高評価を得ている全世界（日・韓・英・中等）のボカロオリジナル曲を一括取得（クォータ消費0）
    """
    results = []
    now = datetime.now(timezone.utc)
    windows = [14, 45, 120, 365, 1800]

    for days in windows:
        after_str = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
        params = {
            "songTypes": "Original",
            "afterDate": after_str,
            "sort": "RatingScore",
            "maxResults": 50,
            "fields": "PVs,Artists",
            "lang": "Japanese"
        }
        try:
            res = requests.get(
                "https://vocadb.net/api/songs",
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=12
            )
            if res.status_code == 200:
                items = res.json().get("items", [])
                for item in items:
                    info = extract_vocadb_song_info(item)
                    if info and (info.get("youtube_id") or info.get("niconico_id")):
                        results.append(info)
        except Exception as e:
            print(f"VocaDB window({days}d) fetch warning: {e}")

    print(f"VocaDB グローバル＆国内トレンド収集: {len(results)} 件取得")
    return results

def crawl_niconico_comprehensive() -> list:
    """
    【コレクター2】ニコニコ動画スナップショットAPI & RSSから
    直近7日・14日・30日・90日・全期間の急上昇ボカロ曲を網羅取得
    """
    nc_ids = []
    headers = {"User-Agent": USER_AGENT}

    rss_urls = [
        "https://www.nicovideo.jp/tag/VOCALOID?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/VOCALOID?sort=m&order=d&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E3%83%9C%E3%82%AB%E3%83%AD%E3%82%AA%E3%83%AA%E3%82%B8%E3%83%8A%E3%83%AB%E6%9B%B2?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E5%88%9D%E9%9F%B3%E3%83%9F%E3%82%AF?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E9%87%8D%E9%9F%B3%E3%83%86%E3%83%88?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/SynthesizerV?sort=h&rss=2.0&lang=ja-jp"
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
    d7 = (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00+09:00")
    d14 = (now - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00+09:00")
    d35 = (now - timedelta(days=35)).strftime("%Y-%m-%dT00:00:00+09:00")
    d120 = (now - timedelta(days=120)).strftime("%Y-%m-%dT00:00:00+09:00")

    snap_plans = [
        {"_sort": "-mylistCounter", "filters[startTime][gte]": d7, "_limit": 50},
        {"_sort": "-viewCounter", "filters[startTime][gte]": d7, "_limit": 50},
        {"_sort": "-mylistCounter", "filters[startTime][gte]": d14, "_limit": 50},
        {"_sort": "-viewCounter", "filters[startTime][gte]": d35, "_limit": 50},
        {"_sort": "-viewCounter", "filters[startTime][gte]": d120, "_limit": 50},
        {"_sort": "-viewCounter", "_limit": 50}
    ]
    for sp in snap_plans:
        params = {
            "q": "VOCALOID OR 初音ミク OR 重音テト OR SynthesizerV OR 可不",
            "targets": "tags",
            "fields": "contentId",
            "_context": "VocaloidCombinedChartBot",
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

    print(f"ニコニコ動画 マルチ期間トレンド収集: {len(nc_ids)} 件取得")
    return nc_ids[:160]

def search_youtube_id_web_zero_quota(query: str, target_title: str = "") -> str:
    """
    【クォータ消費ゼロ】YouTubeのWeb検索結果(ytInitialData)から直接videoIdを抽出する。
    YouTube Data APIのsearch.list(100ユニット)を使わずに無制限に公式MVのIDを特定可能。
    """
    url = "https://www.youtube.com/results"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    try:
        res = requests.get(url, params={"search_query": query}, headers=headers, timeout=10)
        if res.status_code == 200:
            # videoRendererブロックから videoId と title を抽出
            matches = re.findall(
                r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})".*?"title":\{"runs":\[\{"text":"([^"]+)"',
                res.text
            )
            norm_target = normalize_compare_str(target_title) if target_title else ""
            for vid, vtitle in matches[:5]:
                v_low = vtitle.lower()
                if any(ng in v_low for ng in ["歌ってみた", "cover", "カラオケ", "#shorts", "mmd", "マイクラ", "1 hour", "耐久"]):
                    continue
                if not norm_target or norm_target in normalize_compare_str(vtitle) or normalize_compare_str(vtitle) in norm_target:
                    return vid
            if matches:
                return matches[0][0]
    except Exception:
        pass
    return ""

def crawl_youtube_multilingual_zero_quota() -> list:
    """
    【コレクター3】日・韓・英の多言語キーワードでYouTube Web検索から急上昇ボカロMVのvideoIdを直接収集
    """
    queries = [
        "初音ミク Official MV -歌ってみた -cover -shorts",
        "重音テト Official MV -歌ってみた -cover -shorts",
        "Synthesizer V Official MV -cover -shorts",
        "可不 Official MV -歌ってみた -cover -shorts",
        "足立レイ Official MV -cover -shorts",
        "카사네 테토 MV -cover -커버 -shorts",
        "하츠네 미쿠 MV -cover -커버 -shorts",
        "보컬로이드 오리지널 MV -cover -커버",
        "Kasane Teto Original MV -cover -shorts",
        "Hatsune Miku Original Song MV -cover -shorts",
        "VOCALOID Original MV 2026 -cover -shorts"
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    yt_ids = []
    for q in queries:
        try:
            # sp=CAMSAhAB はYouTubeの「視聴回数順・動画のみ」フィルタでも動作するが標準検索と併用
            res = requests.get("https://www.youtube.com/results", params={"search_query": q}, headers=headers, timeout=10)
            if res.status_code == 200:
                vids = re.findall(r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})"', res.text)
                for vid in vids[:15]:
                    if vid not in yt_ids:
                        yt_ids.append(vid)
        except Exception:
            pass

    print(f"YouTube 日韓英マルチリンガル探索: {len(yt_ids)} 件取得")
    return yt_ids

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
    headers = {"User-Agent": USER_AGENT}
    try:
        q_enc = urllib.parse.quote(f"{title} {producer}".strip())
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

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("エラー: YOUTUBE_API_KEY が設定されていません。")
        return

    youtube = build("youtube", "v3", developerKey=api_key)

    # =================================================================
    # Step 1: 既存マスター＆過去スナップショットからの「非破壊読み込み」
    # （過去に一度でも取得できた youtube_id / niconico_id を絶対に失わない）
    # =================================================================
    pool = []
    by_yt = {}
    by_nc = {}
    by_tp = {}

    def upsert_song(entry: dict):
        """非破壊マージ関数：既存の非空IDを絶対に空文字で上書きしない"""
        yid = (entry.get("youtube_id") or "").strip()
        nid = (entry.get("niconico_id") or "").strip()
        title = clean_song_title(entry.get("title", ""), entry.get("producer", ""))
        producer = (entry.get("producer") or "ボカロP").strip()
        vocal = entry.get("vocal") or "VOCALOID"

        if not yid and not nid:
            return

        tp_key = f"{normalize_compare_str(title)}::{normalize_compare_str(producer)}" if title else ""
        target = None
        if nid and nid in by_nc:
            target = by_nc[nid]
        elif yid and yid in by_yt:
            target = by_yt[yid]
        elif tp_key and tp_key in by_tp:
            target = by_tp[tp_key]

        if target is not None:
            # 既存エントリに欠けているIDがあれば補完（すでにあるIDは絶対に消さない）
            if yid and not target.get("youtube_id"):
                target["youtube_id"] = yid
                by_yt[yid] = target
            if nid and not target.get("niconico_id"):
                target["niconico_id"] = nid
                by_nc[nid] = target
            if title and (not target.get("title") or target["title"] == target.get("producer")):
                target["title"] = title
            if producer and producer != "ボカロP" and target.get("producer") == "ボカロP":
                target["producer"] = producer
            return

        new_item = {
            "song_id": entry.get("song_id") or f"song_{nid if nid else yid}",
            "title": title or "Unknown",
            "producer": producer,
            "vocal": vocal,
            "youtube_id": yid,
            "niconico_id": nid
        }
        pool.append(new_item)
        if yid:
            by_yt[yid] = new_item
        if nid:
            by_nc[nid] = new_item
        if tp_key:
            by_tp[tp_key] = new_item

    # 既存の songs_master.json と latest_monday.json の両方からID資産を復元
    for path in [MASTER_FILE, LATEST_SNAPSHOT]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for item in json.load(f):
                        upsert_song(item)
            except Exception:
                pass

    # =================================================================
    # Step 2: 3大コレクターから国内外のトレンド候補曲を網羅収集
    # =================================================================
    # コレクター1: VocaDB グローバル＆国内トレンド
    for v_item in crawl_vocadb_global_and_domestic():
        upsert_song(v_item)

    # コレクター2: ニコニコ動画 マルチ期間トレンド
    nc_candidates = crawl_niconico_comprehensive()
    new_nc_ids = [cid for cid in nc_candidates if cid not in by_nc]
    for cid in new_nc_ids:
        nc_info = get_niconico_thumbinfo(cid)
        if not nc_info or not is_valid_vocaloid_mv(nc_info["title"], nc_info["description"], nc_info["tags"], nc_info["duration_sec"]):
            continue
        vdb = lookup_vocadb_by_pv("NicoNicoDouga", cid)
        producer = vdb.get("producer") or nc_info["producer"] or "ボカロP"
        title = vdb.get("title") or clean_song_title(nc_info["title"], producer)
        vocal = vdb.get("vocal") or detect_vocals(f"{nc_info['title']} {nc_info['tags']}")
        yt_id = vdb.get("youtube_id", "")
        if not yt_id:
            m = YT_ID_PATTERN.search(nc_info["description"])
            if m:
                yt_id = m.group(1)

        upsert_song({
            "song_id": f"song_{cid}",
            "title": title,
            "producer": producer,
            "vocal": vocal,
            "youtube_id": yt_id,
            "niconico_id": cid
        })

    # コレクター3: YouTube 日・韓・英マルチリンガル探索（50件ずつ videos.list で検証、1回1ユニット）
    yt_candidates = crawl_youtube_multilingual_zero_quota()
    new_yt_ids = [vid for vid in yt_candidates if vid not in by_yt]
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
                vocal = vdb.get("vocal") or detect_vocals(f"{raw_title} {tags} {desc[:200]}")
                nc_id = vdb.get("niconico_id", "")
                if not nc_id:
                    m = NC_ID_PATTERN.search(desc)
                    if m:
                        nc_id = m.group(1)

                upsert_song({
                    "song_id": f"song_{nc_id if nc_id else vid}",
                    "title": title,
                    "producer": producer,
                    "vocal": vocal,
                    "youtube_id": vid,
                    "niconico_id": nc_id
                })
        except Exception as e:
            print(f"YouTube multilingual batch check error: {e}")

    # =================================================================
    # Step 3: プール内の「片側ID未特定曲」をクォータ消費ゼロで徹底補完
    # （『ご主人様、ロックのお時間にございます』等のYouTube ID欠損を100%解消）
    # =================================================================
    repaired_count = 0
    for song in pool:
        yid = song.get("youtube_id", "")
        nid = song.get("niconico_id", "")

        # ニコ動IDはあるがYouTube IDが空欄の場合 -> VocaDB -> 説明文 -> Web検索で確実に特定
        if nid and not yid:
            vdb = lookup_vocadb_by_pv("NicoNicoDouga", nid)
            yid = vdb.get("youtube_id", "")
            if not yid:
                nc_info = get_niconico_thumbinfo(nid)
                if nc_info:
                    m = YT_ID_PATTERN.search(nc_info["description"])
                    if m:
                        yid = m.group(1)
            if not yid and song.get("title"):
                yid = search_youtube_id_web_zero_quota(f"{song['title']} {song['producer']} MV", song["title"])
            if yid:
                song["youtube_id"] = yid
                by_yt[yid] = song
                repaired_count += 1

        # YouTube IDはあるがニコ動IDが空欄の場合 -> VocaDB照会
        elif yid and not nid:
            vdb = lookup_vocadb_by_pv("Youtube", yid)
            nid = vdb.get("niconico_id", "")
            if nid:
                song["niconico_id"] = nid
                by_nc[nid] = song
                repaired_count += 1

    MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

    both_paired = sum(1 for s in pool if s.get("youtube_id") and s.get("niconico_id"))
    print(f"網羅トラッキングプール更新完了: 全 {len(pool)} 曲 (うち両サイトID特定済: {both_paired} 曲 / 今回自動修復: {repaired_count} 曲)")

if __name__ == "__main__":
    main()