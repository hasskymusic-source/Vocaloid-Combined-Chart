import json
from pathlib import Path
from config import DRAFT_FILE, WEIGHTS

EXPORT_DIR = DRAFT_FILE.parent.parent / "exports"

def format_diff_md(rank: int, prev) -> str:
    if not prev or prev == "NEW":
        return "🆕 NEW"
    try:
        diff = int(prev) - int(rank)
        if diff > 0:
            return f"▲+{diff} (前週{prev}位)"
        elif diff < 0:
            return f"▼{diff} (前週{prev}位)"
        return f"→ (前週{prev}位)"
    except Exception:
        return "🆕 NEW"

def generate_markdown_from_data(data: dict) -> str:
    """weekly_draft.json の辞書データからブログ記事用Markdownテキストを生成する"""
    publish_date = data.get("publishDate", "")
    archive_id = data.get("archiveId", "latest")
    period = data.get("period", "")
    summary = data.get("weeklySummary", "")
    songs = data.get("songs", [])
    w = data.get("weights", WEIGHTS)

    lines = []
    # 記事タイトル・導入
    lines.append(f"# 週刊VOCALOID複合ランキング TOP 20（{archive_id}公開 / 集計期間：{period}）")
    lines.append("")
    lines.append(
        "YouTubeとニコニコ動画の6指標（週間再生数・高評価数・マイリスト数・コメント数）を統合し、"
        "国内外のボーカロイド（合成音声）音楽シーンのトレンドを可視化する**『週刊VOCALOID複合ランキング』**。"
    )
    lines.append(f"本記事では、集計期間（**{period}**）のデータに基づく最新TOP 20チャートと注目楽曲の指標動向を解説します。")
    lines.append("")
    lines.append("> 🔗 **インタラクティブ版チャート（6指標グラフ・過去アーカイブ切替）はこちら**")
    lines.append("> https://weekly-vocaloid-combined-chart.com/")
    lines.append("")

    # 今週のチャート総括
    lines.append("---")
    lines.append("")
    lines.append("## 📈 今週のチャート総括")
    lines.append("")
    lines.append(summary if summary else "今週のYouTube・ニコニコ動画6指標による週間複合ランキング結果です。")
    lines.append("")

    # TOP 20 一覧テーブル
    lines.append("---")
    lines.append("")
    lines.append("## 🏆 週間VOCALOID複合ランキング TOP 20 一覧")
    lines.append("")
    lines.append("| 順位 | 前週比 | 楽曲名 | ボカロP | Vocal | 週間総合pt | YT比率 / ニコ動比率 |")
    lines.append("| :---: | :---: | :--- | :--- | :--- | ---: | :---: |")

    for s in songs[:20]:
        rank = s.get("rank", 0)
        diff_str = format_diff_md(rank, s.get("prevRank", "NEW"))
        title = s.get("title", "").replace("|", "｜")
        producer = s.get("producer", "").replace("|", "｜")
        vocal = s.get("vocal", "-").replace("|", "｜")
        total_pt = s.get("total_pt", 0)
        yt_pt = s.get("yt_total_pt", 0)
        nc_pt = s.get("nc_total_pt", 0)
        denom = total_pt if total_pt > 0 else 1
        yt_share = (yt_pt / denom) * 100
        nc_share = (nc_pt / denom) * 100

        lines.append(
            f"| **{rank}位** | {diff_str} | **{title}** | {producer} | {vocal} | "
            f"**{total_pt:,} pt** | YT {yt_share:.1f}% / ニコ {nc_share:.1f}% |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🔍 上位楽曲・ピックアップ指標解説")
    lines.append("")
    lines.append("TOP 5楽曲および今週の注目楽曲（個別解説付き楽曲）のポイント構成と動向です。")
    lines.append("")

    # TOP 5 または 個別解説(commentary)が書かれている楽曲を詳細出力
    for s in songs[:20]:
        rank = s.get("rank", 0)
        commentary = (s.get("commentary") or "").strip()
        if rank > 5 and not commentary:
            continue

        title = s.get("title", "")
        producer = s.get("producer", "")
        vocal = s.get("vocal", "-")
        total_pt = s.get("total_pt", 0)
        yt_pt = s.get("yt_total_pt", 0)
        nc_pt = s.get("nc_total_pt", 0)
        denom = total_pt if total_pt > 0 else 1
        yt_share = (yt_pt / denom) * 100
        nc_share = (nc_pt / denom) * 100

        raw = s.get("raw", {})
        pts = s.get("pts", {})
        yid = s.get("youtube_id", "")
        nid = s.get("niconico_id", "")

        lines.append(f"### {rank}位：{producer}『{title}』（{total_pt:,} pt）")
        lines.append("")
        lines.append(f"- **Vocal:** {vocal} ｜ **前週比:** {format_diff_md(rank, s.get('prevRank', 'NEW'))}")
        lines.append(f"- **プラットフォーム構成比:** YouTube **{yt_share:.1f}%**（{yt_pt:,} pt） / ニコニコ動画 **{nc_share:.1f}%**（{nc_pt:,} pt）")
        lines.append(
            f"- **YouTube内訳:** 週間再生 +{raw.get('yt_views', 0):,}回（{pts.get('yt_views', 0):,} pt） / "
            f"週間高評価 +{raw.get('yt_likes', 0):,}件（{pts.get('yt_likes', 0):,} pt） / "
            f"週間コメ +{raw.get('yt_comments', 0):,}件（{pts.get('yt_comments', 0):,} pt）"
        )
        lines.append(
            f"- **ニコニコ動画内訳:** 週間再生 +{raw.get('nc_views', 0):,}回（{pts.get('nc_views', 0):,} pt） / "
            f"週間マイリス +{raw.get('nc_mylist', 0):,}件（{pts.get('nc_mylist', 0):,} pt） / "
            f"週間コメ +{raw.get('nc_comments', 0):,}件（{pts.get('nc_comments', 0):,} pt）"
        )

        link_parts = []
        if yid:
            link_parts.append(f"[▶ YouTubeで視聴](https://www.youtube.com/watch?v={yid})")
        if nid:
            link_parts.append(f"[▶ ニコニコ動画で視聴](https://www.nicovideo.jp/watch/{nid})")
        if link_parts:
            lines.append(f"- **視聴リンク:** {' / '.join(link_parts)}")

        lines.append("")
        if commentary:
            lines.append(commentary)
        else:
            lines.append(
                f"YouTube指標 {yt_share:.1f}%（{yt_pt:,} pt）、ニコニコ動画指標 {nc_share:.1f}%（{nc_pt:,} pt）を獲得し、"
                f"週間総合 {total_pt:,} pt で{rank}位にランクイン。"
            )
        lines.append("")

    # 集計方法フッター
    lines.append("---")
    lines.append("")
    lines.append("## 📋 ランキング集計方法（6指標と補正係数）")
    lines.append("")
    lines.append("毎週月曜日0:00から日曜日23:59までの7日間における各指標の純増数を取得し、以下の補正係数を乗じて合算した総合ポイント順で上位20曲（TOP 20）を算出しています。")
    lines.append("")
    lines.append(f"- **YouTube:** 週間再生数 **×{w.get('yt_views', 1)}** / 週間高評価数 **×{w.get('yt_likes', 50)}** / 週間コメント数 **×{w.get('yt_comments', 100)}**")
    lines.append(f"- **ニコニコ動画:** 週間再生数 **×{w.get('nc_views', 5)}** / 週間マイリスト数 **×{w.get('nc_mylist', 100)}** / 週間コメント数 **×{w.get('nc_comments', 10)}**")
    lines.append("")

    return "\n".join(lines)

def export_markdown_file() -> Path:
    if not DRAFT_FILE.exists():
        raise FileNotFoundError(f"{DRAFT_FILE} が見つかりません。")

    with open(DRAFT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    md_text = generate_markdown_from_data(data)
    archive_id = data.get("archiveId", "latest")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = EXPORT_DIR / f"blog_{archive_id}.md"
    latest_path = EXPORT_DIR / "latest_blog.md"

    with open(dated_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    return dated_path

def main():
    out_path = export_markdown_file()
    print(f"ブログ用Markdown記事を生成しました: {out_path}")

if __name__ == "__main__":
    main()