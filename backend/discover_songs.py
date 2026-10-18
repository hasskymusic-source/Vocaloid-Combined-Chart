import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from config import MASTER_FILE, LATEST_SNAPSHOT

USER_AGENT = "Mozilla/5.0 (compatible; VocaloidCombinedChartBot/7.0)"

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

# 【防衛ロック1】非楽曲コンテンツ（旅行・車載・トーク・実況・料理・MMD・Shorts等）を完全排除するNGワード
NG_KEYWORDS = [
    # 歌ってみた・二次創作・Shorts
    "歌ってみた", "踊ってみた", "演奏してみた", "叩いてみた", "弾いてみた",
    "切り抜き", "まとめ", "メドレー", "カラオケ", "off vocal", "instrumental",
    "reaction", "リアクション", "プロセカ", "プロジェクトセカイ", "譜面",
    "耐久", "1時間", "1 hour", "作業用", "解説", "ランキング", "比較",
    "mmd", "mikumikudance", "yyb", "tda", "モデル", "モーション",
    "マイクラ", "マインクラフト", "minecraft", "再現", "レッドストーン", "音ブロック",
    "同時視聴", "初見", "配信", "live", "ライブ", "チャンネル登録", "万人ありがとう",
    "#shorts", "shorts", "ショート", "tiktok", "違い", "感性プレイ", "ホロドリ", "藤井風",
    "cover", "covered by", "커버", "불러보았다", "piano tutorial", "sheet music",
    # 合成音声トーク・旅行・車載・実況・劇場系（今回の「歩道」のような動画を100%遮断）
    "旅行", "車載", "散歩", "ツーリング", "ドライブ", "鉄道", "夜景", "ゲートブリッジ",
    "行ってみた", "行ってみない", "食べてみた", "作ってみた", "描いてみた", "買ってみた",
    "ソフトウェアトーク", "voiceroid", "voicepeak", "a.i.voice", "ボイロ", "ゆっくり",
    "実況", "プレイ動画", "ゲーム実況", "料理", "キッチン", "劇場", "茶番", "ラジオ", "雑談",
    "重音テトが行く", "講座", "検証", "紹介", "レビュー", "ニュース"
]

# 【防衛ロック2】ニコニコ動画で「ボカロ楽曲」と認めるための必須音楽タグ群
# （単なる「重音テト」等のキャラ名タグしかない旅行・トーク動画はここで100%弾かれる）
REQUIRED_MUSIC_INDICATORS = [
    "vocaloid", "ボカロ", "보컬로이드", "ボカロオリジナル曲", "オリジナル曲",
    "synthesizerv", "synthesizer_v", "synthesizer v", "synthv",
    "synthesizervオリジナル曲", "utauオリジナル曲", "cevioオリジナル曲", "voicevoxオリジナル曲",
    "ミクオリジナル曲", "テトオリジナル曲", "重音テトsv", "可不オリジナル曲", "gumiオリジナル曲",
    "リンオリジナル曲", "レンオリジナル曲", "ルカオリジナル曲", "flowerオリジナル曲",
    "ユキオリジナル曲", "レイオリジナル曲", "ウナオリジナル曲", "ゆかりオリジナル曲",
    "vocarock", "ボカコレ", "vocacolle", "vocaloid新曲リンク", "vocaloid殿堂入り", "vocaloid伝説入り",
    "music video", "official mv", "【mv】", "[mv]"
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

def is_valid_vocaloid_mv(
    title: str,
    description: str = "",
    tags: str = "",
    duration_sec: int = 180,
    is_niconico: bool = False,
    yt_category_id: str = "10"
) -> bool:
    """
    ボーカロイド楽曲（オリジナルMV）かどうかを厳格に判定するシステム
    """
    # 1. 再生時間チェック（90秒未満のShorts・ジングル、420秒超のトーク・配信・まとめを除外）
    if duration_sec < 90 or duration_sec > 420:
        return False

    t_low = title.lower()
    d_low = description.lower()
    tags_low = tags.lower()

    # 2. タイトル・タグに非楽曲ワード（旅行・車載・トーク・実況・MMD・カバー等）があれば即除外
    for ng in NG_KEYWORDS:
        if ng in t_low or ng in tags_low:
            return False

    if "#shorts" in d_low or "mikumikudance" in d_low or "yyb式" in d_low or "tda式" in d_low:
        return False

    # 3. ニコニコ動画の場合：キャラ名だけでなく「ボカロ音楽系タグ」の含有を必須とする
    title_and_tags_low = f"{t_low} {tags_low}"
    if is_niconico:
        has_music_tag = any(ind in title_and_tags_low for ind in REQUIRED_MUSIC_INDICATORS)
        if not has_music_tag:
            return False

    # 4. YouTubeの場合：ゲーム実況(20)・ブログ(22)・旅行(19)・エンタメ雑談等で音楽指標がないものを除外
    if not is_niconico and yt_category_id not in ["10", ""]:
        if not any(ind in f"{t_low} {tags_low} {d_low[:200]}" for ind in REQUIRED_MUSIC_INDICATORS):
            return False

    # 5. 合成音声キャラクターまたは歌声合成エンジンの存在確認
    combined_low = f"{title} {tags} {description[:300]}".lower()
    has_vocal = any(
        syn.lower() in combined_low
        for syns in VOCAL_SYNONYMS.values()
        for syn in syns
    ) or any(
        k in combined_low for k in ["vocaloid", "ボカロ", "보컬로이드", "synthesizer v", "synthv", "cevio", "utau"]
    )
    return has_vocal

def normalize_compare_str(s: str) -> str:
    return re.sub(r"[\s\*\-\_・／/!！?？'\"「」『』【】\[\]()（）pPチャンネルchannelofficialmvpv]", "", s.lower())

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

    # カギ括弧の抽出は「ハチ MV「砂の惑星」」のように括弧以外の残り文字が短い（ボカロP名やMV表記のみの）場合だけに限定
    quoted_titles = re.findall(r"「([^」]+)」", t)
    if len(quoted_titles) == 1 and len(quoted_titles[0]) >= 2:
        cand = quoted_titles[0].strip()
        outside = re.sub(r"「[^」]+」", "", t).strip()
        if len(outside) <= 12 and not META_BRACKET_RE.match(cand):
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

def extract_vocadb_song_info(data: dict) -> dict:
    if not data or not isinstance(data, dict):
        return {}
    # カバーやドラマPV等を弾き、純粋なオリジナル曲のみに限定
    if data.get("songType", "") not in ["Original", "Remaster", "Remix"]:
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
    results = []
    now = datetime.now(timezone.utc)
    for days in [14, 45, 120, 365, 1800]:
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
                for item in res.json().get("items", []):
                    info = extract_vocadb_song_info(item)
                    if info and (info.get("youtube_id") or info.get("niconico_id")):
                        results.append(info)
        except Exception as e:
            print(f"VocaDB window({days}d) fetch warning: {e}")

    print(f"VocaDB グローバル＆国内トレンド収集: {len(results)} 件取得")
    return results

def crawl_niconico_comprehensive() -> list:
    """音楽・ボカロオリジナル曲タグに厳格限定してニコ動トレンドを収集"""
    nc_ids = []
    headers = {"User-Agent": USER_AGENT}

    # 単なる「重音テト」タグ（旅行・トーク動画が混じる）を廃止し、音楽タグのみを巡回
    rss_urls = [
        "https://www.nicovideo.jp/tag/VOCALOID?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/VOCALOID?sort=m&order=d&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E3%83%9C%E3%82%AB%E3%83%AD%E3%82%AA%E3%83%AA%E3%82%B8%E3%83%8A%E3%83%AB%E6%9B%B2?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E3%83%9F%E3%82%AF%E3%82%AA%E3%83%AA%E3%82%B8%E3%83%8A%E3%83%AB%E6%9B%B2?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/%E3%83%86%E3%83%88%E3%82%AA%E3%83%AA%E3%82%B8%E3%83%8A%E3%83%AB%E6%9B%B2?sort=h&rss=2.0&lang=ja-jp",
        "https://www.nicovideo.jp/tag/SynthesizerV%E3%82%AA%E3%83%AA%E3%82%B8%E3%83%8A%E3%83%AB%E6%9B%B2?sort=h&rss=2.0&lang=ja-jp"
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
    ]
    for sp in snap_plans:
        params = {
            "q": "VOCALOID OR ボカロオリジナル曲 OR SynthesizerVオリジナル曲 OR テトオリジナル曲",
            "targets": "tagsExact",
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

def search_youtube_id_web_strict(target_title: str, target_producer: str, existing_yt_ids: set) -> str:
    """
    【防衛ロック3】無条件フォールバック(matches[0][0])を完全撤廃。
    タイトルとボカロP名が厳密に整合し、かつ他曲で使われていないYouTube IDのみを返す。
    """
    norm_title = normalize_compare_str(target_title)
    norm_prod = normalize_compare_str(target_producer)
    if len(norm_title) < 2:
        return ""

    url = "https://www.youtube.com/results"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    query = f'"{target_title}" {target_producer} MV'
    try:
        res = requests.get(url, params={"search_query": query}, headers=headers, timeout=10)
        if res.status_code == 200:
            matches = re.findall(
                r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})".*?"title":\{"runs":\[\{"text":"([^"]+)"',
                res.text
            )
            for vid, vtitle in matches[:5]:
                # すでに他の曲に登録されているYouTube IDは絶対に割り当てない（肆足歩行ハイジャック防止）
                if vid in existing_yt_ids:
                    continue
                v_low = vtitle.lower()
                if any(ng in v_low for ng in NG_KEYWORDS):
                    continue
                norm_vtitle = normalize_compare_str(vtitle)
                # 曲名が動画タイトルに完全に含まれていることを必須化
                if norm_title in norm_vtitle:
                    # 2文字以下の短い曲名の場合は、ボカロP名もタイトルに含まれていることを必須化
                    if len(norm_title) <= 2 and norm_prod and norm_prod not in norm_vtitle:
                        continue
                    return vid
    except Exception:
        pass
    return ""

def crawl_youtube_multilingual_zero_quota() -> list:
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

def verify_and_purge_existing_pool(youtube, raw_items: list) -> list:
    """
    【防衛ロック5】既存データの総点検＆汚染データ自動パージ
    1. ニコ動IDを持つ曲は getthumbinfo でタグを再検証し、旅行動画・トーク動画等を完全削除
    2. 同じ youtube_id が複数の曲に重複割り当てされている場合、タイトルが一致しない偽物を削除
    """
    yt_ids = list(dict.fromkeys([x.get("youtube_id") for x in raw_items if x.get("youtube_id")]))
    yt_meta = {}
    for i in range(0, len(yt_ids), 50):
        chunk = yt_ids[i:i+50]
        try:
            res = youtube.videos().list(part="snippet,contentDetails", id=",".join(chunk)).execute()
            for item in res.get("items", []):
                yt_meta[item["id"]] = item
        except Exception:
            pass

    verified = []
    for item in raw_items:
        yid = (item.get("youtube_id") or "").strip()
        nid = (item.get("niconico_id") or "").strip()
        title = item.get("title", "")

        # ニコ動側の再検証（旅行動画「歩道」などはここで音楽タグ不在＆NGワードにより確実に削除される）
        if nid:
            nc_info = get_niconico_thumbinfo(nid)
            if nc_info:
                if not is_valid_vocaloid_mv(
                    nc_info["title"], nc_info["description"], nc_info["tags"],
                    nc_info["duration_sec"], is_niconico=True
                ):
                    print(f"非楽曲ニコ動エントリをパージしました: {nc_info['title']} ({nid})")
                    continue

        # YouTube側の再検証（カテゴリ・動画尺・タイトル整合性チェック）
        if yid and yid in yt_meta:
            y_item = yt_meta[yid]
            snippet = y_item.get("snippet", {})
            dur_sec = parse_iso_duration_seconds(y_item.get("contentDetails", {}).get("duration", ""))
            cat_id = snippet.get("categoryId", "10")
            y_title = snippet.get("title", "")
            y_desc = snippet.get("description", "")
            y_tags = " ".join(snippet.get("tags", []))

            if not is_valid_vocaloid_mv(y_title, y_desc, y_tags, dur_sec, is_niconico=False, yt_category_id=cat_id):
                print(f"非楽曲YouTubeエントリをパージしました: {y_title} ({yid})")
                continue

            # もしニコ動曲なのにYouTubeタイトルと曲名が全くかすりもしない（誤結合）ならYouTube IDを剥奪
            if nid and title:
                norm_t = normalize_compare_str(title)
                norm_yt = normalize_compare_str(y_title)
                if len(norm_t) >= 2 and norm_t not in norm_yt and norm_yt not in norm_t:
                    vdb = lookup_vocadb_by_pv("NicoNicoDouga", nid)
                    if vdb.get("youtube_id") != yid:
                        print(f"不正なYouTube紐付けを解除しました: {title} != {y_title}")
                        item["youtube_id"] = ""

        verified.append(item)
    return verified

def main():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("エラー: YOUTUBE_API_KEY が設定されていません。")
        return

    youtube = build("youtube", "v3", developerKey=api_key)

    raw_loaded = []
    for path in [MASTER_FILE, LATEST_SNAPSHOT]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw_loaded.extend(json.load(f))
            except Exception:
                pass

    # Step 1: 既存プールの汚染データ（「歩道」等の非楽曲や重複ID）を自動パージ
    verified_existing = verify_and_purge_existing_pool(youtube, raw_loaded)

    pool = []
    by_yt = {}
    by_nc = {}
    by_tp = {}

    def upsert_song(entry: dict):
        """【防衛ロック4】ID一意性制約付きマージ：他曲で使用済みのYouTube IDの横取りを完全防止"""
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
            # 他の曲で使われていないIDのみを補完
            if yid and not target.get("youtube_id") and yid not in by_yt:
                target["youtube_id"] = yid
                by_yt[yid] = target
            if nid and not target.get("niconico_id") and nid not in by_nc:
                target["niconico_id"] = nid
                by_nc[nid] = target
            if title and (not target.get("title") or target["title"] == target.get("producer")):
                target["title"] = title
            if producer and producer != "ボカロP" and target.get("producer") == "ボカロP":
                target["producer"] = producer
            return

        # 新規追加時、もし yid が既に別曲で使われていたら yid を無効化
        if yid and yid in by_yt:
            yid = ""
        if nid and nid in by_nc:
            nid = ""
        if not yid and not nid:
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

    for item in verified_existing:
        upsert_song(item)

    # Step 2: 3大コレクターから収集
    for v_item in crawl_vocadb_global_and_domestic():
        upsert_song(v_item)

    nc_candidates = crawl_niconico_comprehensive()
    new_nc_ids = [cid for cid in nc_candidates if cid not in by_nc]
    for cid in new_nc_ids:
        nc_info = get_niconico_thumbinfo(cid)
        if not nc_info or not is_valid_vocaloid_mv(
            nc_info["title"], nc_info["description"], nc_info["tags"],
            nc_info["duration_sec"], is_niconico=True
        ):
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
                cat_id = snippet.get("categoryId", "10")
                raw_title = snippet.get("title", "")
                desc = snippet.get("description", "")
                tags = " ".join(snippet.get("tags", []))
                channel = snippet.get("channelTitle", "ボカロP")

                if not is_valid_vocaloid_mv(raw_title, desc, tags, dur_sec, is_niconico=False, yt_category_id=cat_id):
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

    # Step 3: 片側IDの厳格補完（重複ID割り当て禁止＆タイトル一致必須）
    repaired_count = 0
    for song in pool:
        yid = song.get("youtube_id", "")
        nid = song.get("niconico_id", "")

        if nid and not yid:
            vdb = lookup_vocadb_by_pv("NicoNicoDouga", nid)
            cand_yid = vdb.get("youtube_id", "")
            if not cand_yid:
                nc_info = get_niconico_thumbinfo(nid)
                if nc_info:
                    m = YT_ID_PATTERN.search(nc_info["description"])
                    if m:
                        cand_yid = m.group(1)
            if not cand_yid and song.get("title"):
                cand_yid = search_youtube_id_web_strict(song["title"], song["producer"], set(by_yt.keys()))
            if cand_yid and cand_yid not in by_yt:
                song["youtube_id"] = cand_yid
                by_yt[cand_yid] = song
                repaired_count += 1

        elif yid and not nid:
            vdb = lookup_vocadb_by_pv("Youtube", yid)
            cand_nid = vdb.get("niconico_id", "")
            if cand_nid and cand_nid not in by_nc:
                song["niconico_id"] = cand_nid
                by_nc[cand_nid] = song
                repaired_count += 1

    MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

    both_paired = sum(1 for s in pool if s.get("youtube_id") and s.get("niconico_id"))
    print(f"厳格検証プール更新完了: 全 {len(pool)} 曲 (両サイトペア済: {both_paired} 曲 / 新規補完: {repaired_count} 曲)")

if __name__ == "__main__":
    main()