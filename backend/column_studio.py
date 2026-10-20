import json
import shutil
import socket
import subprocess
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import (
    BASE_DIR,
    ARTICLES_MASTER_FILE,
    ARTICLES_BACKUP_FILE,
    PUBLIC_ARTICLES_FILE,
)
from publish_chart import sync_published_articles, sync_frontend_assets

JST = timezone(timedelta(hours=9))
START_PORT = 8766

DEFAULT_SPEAKERS = [
    {
        "id": "spk_host",
        "name": "チャート分析班",
        "side": "left",
        "icon": "🎧",
        "color": "#00d2ff",
    },
    {
        "id": "spk_guest",
        "name": "ボカロ解説員",
        "side": "right",
        "icon": "✨",
        "color": "#f97316",
    },
]


def run_git(args: list, check: bool = False):
    return subprocess.run(
        ["git"] + args,
        cwd=BASE_DIR,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def ensure_articles_store() -> dict:
    ARTICLES_MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    if ARTICLES_MASTER_FILE.exists():
        try:
            with open(ARTICLES_MASTER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                if "articles" not in data or not isinstance(data["articles"], list):
                    data["articles"] = []
                if "speakers" not in data or not isinstance(data["speakers"], list) or not data["speakers"]:
                    data["speakers"] = DEFAULT_SPEAKERS
                return data
            elif isinstance(data, list):
                return {"articles": data, "speakers": DEFAULT_SPEAKERS}
        except Exception:
            pass

    initial_store = {"articles": [], "speakers": DEFAULT_SPEAKERS}
    with open(ARTICLES_MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(initial_store, f, ensure_ascii=False, indent=2)
    sync_published_articles(datetime.now(JST))
    return initial_store


def save_articles_and_push(store_data: dict, do_push: bool) -> tuple:
    """
    記事・コラムデータの無衝突保存＆GitHubプッシュエンジン
    """
    try:
        ARTICLES_MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ARTICLES_BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(store_data, f, ensure_ascii=False, indent=2)

        if do_push:
            run_git(["rebase", "--abort"], check=False)
            run_git(["merge", "--abort"], check=False)
            fetch_res = run_git(["fetch", "origin", "main"], check=False)
            if fetch_res.returncode == 0:
                run_git(["reset", "--hard", "origin/main"], check=False)

        with open(ARTICLES_MASTER_FILE, "w", encoding="utf-8") as f:
            json.dump(store_data, f, ensure_ascii=False, indent=2)
        with open(ARTICLES_BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(store_data, f, ensure_ascii=False, indent=2)

        now_dt = datetime.now(JST)
        sync_frontend_assets()
        published_list = sync_published_articles(now_dt)

        if not do_push:
            return (
                True,
                f"PCに保存しました！（現在公開中の記事: {len(published_list)} 件 / 全保存記事: {len(store_data.get('articles', []))} 件）",
            )

        run_git(["add", "-A"], check=True)
        status = run_git(["status", "--porcelain"], check=False)
        if status.stdout.strip():
            run_git(
                ["commit", "-m", f"記事・コラム執筆スタジオから記事データを更新 (公開中: {len(published_list)}件)"],
                check=True,
            )

        push_res = run_git(["push", "origin", "main"], check=False)
        if push_res.returncode != 0:
            run_git(["push", "--force-with-lease", "origin", "main"], check=True)

        return (
            True,
            f"🚀 GitHubへのプッシュが完了しました！\n公開設定の記事（{len(published_list)} 件）が約1分で本番Webサイトの「記事・コラム」タブに反映されます。",
        )

    except Exception as e:
        err_msg = getattr(e, "stderr", "") or getattr(e, "stdout", "") or str(e)
        return False, f"保存またはプッシュ中にエラーが発生しました: {err_msg}"


def find_free_port(start_port: int) -> int:
    port = start_port
    while port < start_port + 20:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    return start_port


STUDIO_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>記事・コラム執筆スタジオ | 週刊VOCALOID複合ランキング</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #161f33;
      --card: #1e293b;
      --input-bg: #0b1120;
      --text: #f8fafc;
      --sub: #94a3b8;
      --accent: #00d2ff;
      --green: #22c55e;
      --amber: #f59e0b;
      --danger: #ef4444;
      --border: #26334d;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: "Segoe UI", "Hiragino Kaku Gothic ProN", "Meiryo", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 100;
      background: rgba(15, 23, 42, 0.96);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      padding: 12px 22px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
    }
    .header-title h1 { font-size: 1.15rem; font-weight: 800; color: var(--text); }
    .header-title span { font-size: 0.78rem; color: var(--sub); }
    .header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    button, .btn-link {
      border: none;
      border-radius: 4px;
      padding: 8px 14px;
      font-size: 0.83rem;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      transition: all 0.15s;
    }
    .btn-primary { background: var(--accent); color: #0f172a; }
    .btn-publish { background: var(--green); color: #052e16; }
    .btn-outline { background: #1e293b; color: var(--accent); border: 1px solid var(--accent); }
    .btn-danger { background: rgba(239, 68, 68, 0.16); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.45); }
    .btn-sub { background: #334155; color: var(--text); }
    .toast-msg { font-size: 0.84rem; font-weight: 700; color: var(--green); opacity: 0; transition: opacity 0.25s; }
    .toast-msg.show { opacity: 1; }

    .studio-layout {
      display: grid;
      grid-template-columns: 290px 1fr 440px;
      gap: 16px;
      max-width: 1720px;
      margin: 16px auto;
      padding: 0 16px 60px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 16px;
    }
    .panel-title {
      font-size: 0.96rem;
      font-weight: 800;
      color: var(--accent);
      margin-bottom: 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .article-list-item {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 10px 12px;
      margin-bottom: 8px;
      cursor: pointer;
      transition: border-color 0.15s;
    }
    .article-list-item:hover, .article-list-item.active {
      border-color: var(--accent);
      background: rgba(0, 210, 255, 0.08);
    }
    .item-status {
      display: inline-block;
      font-size: 0.68rem;
      font-weight: 800;
      padding: 1px 6px;
      border-radius: 2px;
      margin-right: 6px;
    }
    .st-published { background: rgba(34, 197, 94, 0.2); color: #4ade80; }
    .st-draft { background: rgba(148, 163, 184, 0.2); color: #cbd5e1; }
    .st-scheduled { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
    .item-title { font-size: 0.88rem; font-weight: 700; margin-top: 4px; }
    .item-meta { font-size: 0.73rem; color: var(--sub); margin-top: 2px; }

    .form-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
    .form-grid-3 { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 12px; margin-bottom: 12px; }
    .field-group { margin-bottom: 12px; }
    .field-label { font-size: 0.76rem; color: var(--sub); margin-bottom: 4px; display: block; font-weight: 700; }
    input[type="text"], input[type="datetime-local"], select, textarea {
      width: 100%;
      background: var(--input-bg);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 8px 10px;
      font-size: 0.88rem;
      font-family: inherit;
    }
    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--accent);
    }

    /* ソシャゲなう風 対話クイック挿入ビルダー */
    .talk-builder-box {
      background: #11192b;
      border: 1px solid rgba(0, 210, 255, 0.35);
      border-radius: 6px;
      padding: 12px;
      margin-bottom: 14px;
    }
    .speakers-bar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .speaker-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 4px 11px;
      font-size: 0.78rem;
      font-weight: 700;
      cursor: pointer;
    }
    .speaker-chip.selected {
      border-color: var(--accent);
      background: rgba(0, 210, 255, 0.16);
      color: var(--accent);
    }
    .toolbar-btns {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }
    .toolbar-btns button {
      padding: 5px 10px;
      font-size: 0.76rem;
      background: #1e293b;
      color: #e2e8f0;
      border: 1px solid var(--border);
    }
    .toolbar-btns button:hover {
      border-color: var(--accent);
      color: var(--accent);
    }

    /* リアルタイムプレビュー枠 */
    .preview-panel {
      position: sticky;
      top: 72px;
      max-height: calc(100vh - 90px);
      overflow-y: auto;
    }
    .preview-header-title { font-size: 1.25rem; font-weight: 800; margin: 8px 0; }
    .preview-lead {
      background: rgba(0, 210, 255, 0.06);
      border-left: 3px solid var(--accent);
      padding: 8px 10px;
      font-size: 0.84rem;
      color: #cbd5e1;
      margin-bottom: 14px;
    }
    .talk-row { display: flex; align-items: flex-start; gap: 10px; margin: 14px 0; }
    .talk-row.talk-right { flex-direction: row-reverse; }
    .talk-speaker-col { display: flex; flex-direction: column; align-items: center; width: 62px; flex-shrink: 0; text-align: center; }
    .talk-avatar {
      width: 46px; height: 46px; border-radius: 50%; background: #0b1120;
      border: 2px solid var(--accent); display: flex; align-items: center; justify-content: center;
      overflow: hidden; font-size: 1.25rem;
    }
    .talk-avatar img { width: 100%; height: 100%; object-fit: cover; }
    .talk-speaker-name { font-size: 0.68rem; color: var(--sub); margin-top: 3px; font-weight: 700; }
    .talk-bubble {
      background: #111a2e; border: 1px solid var(--speaker-color, #26334d);
      border-radius: 8px; padding: 9px 12px; max-width: calc(100% - 76px); font-size: 0.86rem;
    }
    .talk-row.talk-right .talk-bubble { background: rgba(0, 210, 255, 0.09); }
    .preview-body h2 {
      font-size: 1.05rem; border-left: 3px solid var(--accent); padding-left: 8px; margin: 16px 0 8px;
    }
    .preview-body h3 { font-size: 0.95rem; color: var(--accent); margin: 12px 0 6px; }
    .preview-body p { font-size: 0.88rem; margin-bottom: 10px; }
    .article-point-box {
      background: #0b1120; border: 1px solid var(--accent); padding: 10px 12px; margin: 12px 0; font-size: 0.85rem;
    }

    @media (max-width: 1200px) {
      .studio-layout { grid-template-columns: 1fr; }
      .preview-panel { position: static; max-height: none; }
    }
  </style>
</head>
<body>
  <header>
    <div class="header-title">
      <h1>📰 記事・コラム執筆スタジオ（対話システム搭載）</h1>
      <span>Billboard Japan × ソシャゲなう風レイアウト対応 ｜ 週刊VOCALOID™複合ランキング</span>
    </div>
    <div class="header-actions">
      <span id="toast" class="toast-msg">✅ 保存完了！</span>
      <a href="/preview#tab-articles" target="_blank" class="btn-link btn-outline" onclick="saveStore(false)">👁️ 本番サイト画面でプレビュー</a>
      <button type="button" class="btn-primary" onclick="saveStore(false)">💾 PCに保存 (Ctrl+S)</button>
      <button type="button" class="btn-publish" onclick="saveStore(true)">🚀 保存して本番Webサイトへ公開 (Git Push)</button>
    </div>
  </header>

  <div class="studio-layout">
    <!-- 左パネル：記事一覧＆話し手（アイコン）管理 -->
    <aside class="panel">
      <div class="panel-title">
        <span>📚 記事・コラム一覧</span>
        <button type="button" class="btn-primary" style="padding:5px 10px;font-size:0.76rem;" onclick="createNewArticle()">＋ 新規記事</button>
      </div>
      <div id="articles-sidebar-list"></div>

      <hr style="border:none;border-top:1px solid var(--border);margin:16px 0;">

      <div class="panel-title">
        <span>🗣️ 対話キャラ登録・編集</span>
      </div>
      <div class="field-group">
        <label class="field-label">名前（話し手）</label>
        <input type="text" id="spk-name" placeholder="例: チャート分析班 / ミク好き編集員">
      </div>
      <div class="form-grid-2">
        <div>
          <label class="field-label">立ち位置</label>
          <select id="spk-side">
            <option value="left">⬅️ 左側（進行役）</option>
            <option value="right">➡️ 右側（相方・解説）</option>
          </select>
        </div>
        <div>
          <label class="field-label">枠カラー</label>
          <input type="text" id="spk-color" value="#00d2ff" placeholder="#00d2ff">
        </div>
      </div>
      <div class="field-group">
        <label class="field-label">アイコン（絵文字 または 画像URL）</label>
        <input type="text" id="spk-icon" value="🎧" placeholder="🎧 または https://.../icon.png">
      </div>
      <button type="button" class="btn-outline" style="width:100%;" onclick="addOrUpdateSpeaker()">＋ この話し手を登録</button>
    </aside>

    <!-- 中央パネル：記事エディタ ＆ 左右対話クイック挿入 -->
    <main class="panel">
      <div class="panel-title">
        <span id="editor-heading">✍️ 記事の編集</span>
        <button type="button" class="btn-danger" style="padding:5px 10px;font-size:0.75rem;" onclick="deleteCurrentArticle()">🗑️ この記事を削除</button>
      </div>

      <div class="field-group">
        <label class="field-label">記事タイトル</label>
        <input type="text" id="art-title" placeholder="例: 【徹底分析】重音テトSV楽曲がYouTubeとニコ動の双方で急伸している理由とは？" oninput="syncCurrentForm()">
      </div>

      <div class="form-grid-3">
        <div>
          <label class="field-label">カテゴリ</label>
          <select id="art-category" onchange="syncCurrentForm()">
            <option value="チャート分析">チャート分析</option>
            <option value="ボカロP特集">ボカロP特集</option>
            <option value="楽曲レビュー">楽曲レビュー</option>
            <option value="対談・コラム">対談・コラム</option>
          </select>
        </div>
        <div>
          <label class="field-label">公開ステータス</label>
          <select id="art-status" onchange="syncCurrentForm()">
            <option value="published">✅ 公開（本番に表示）</option>
            <option value="draft">📝 下書き（手元のみ・非公開）</option>
          </select>
        </div>
        <div>
          <label class="field-label">ピックアップ枠（最上部大型表示）</label>
          <select id="art-featured" onchange="syncCurrentForm()">
            <option value="false">通常カード表示</option>
            <option value="true">⭐ PICK UP 特集に指定</option>
          </select>
        </div>
      </div>

      <div class="form-grid-3">
        <div>
          <label class="field-label">公開日表示 (YYYY-MM-DD)</label>
          <input type="text" id="art-pubdate" placeholder="2026-10-21" oninput="syncCurrentForm()">
        </div>
        <div>
          <label class="field-label">予約解禁日時（空欄なら即時公開可）</label>
          <input type="text" id="art-publish-at" placeholder="例: 2026-10-21T13:00:00+09:00" oninput="syncCurrentForm()">
        </div>
        <div>
          <label class="field-label">執筆者名</label>
          <input type="text" id="art-author" placeholder="週刊VOCALOID複合チャート編集部" oninput="syncCurrentForm()">
        </div>
      </div>

      <div class="form-grid-2">
        <div>
          <label class="field-label">サムネイル用 YouTube動画ID（入力すると自動で高画質サムネ取得）</label>
          <input type="text" id="art-ytid" placeholder="例: dQw4w9WgXcQ (11文字のID)" oninput="syncCurrentForm()">
        </div>
        <div>
          <label class="field-label">または 任意のサムネイル画像URL / タグ（カンマ区切り）</label>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
            <input type="text" id="art-thumb" placeholder="画像URL (任意)" oninput="syncCurrentForm()">
            <input type="text" id="art-tags" placeholder="初音ミク, 重音テト, 分析" oninput="syncCurrentForm()">
          </div>
        </div>
      </div>

      <div class="field-group">
        <label class="field-label">リード文・要約（一覧カードおよび記事冒頭の概要枠に表示されます）</label>
        <textarea id="art-summary" rows="2" placeholder="記事の導入や要約を2〜3行で入力..." oninput="syncCurrentForm()"></textarea>
      </div>

      <!-- ソシャゲなう風 左右対話クイック挿入ボックス -->
      <div class="talk-builder-box">
        <label class="field-label" style="color:var(--accent);">💬 左右対話吹き出しクイック挿入（話し手を選んでセリフを入力 → 「本文へ挿入」）</label>
        <div id="speakers-chip-bar" class="speakers-bar"></div>
        <div style="display:flex;gap:8px;">
          <textarea id="quick-talk-text" rows="2" placeholder="ここに話し手のセリフを入力...（改行や **太字** も使えます）"></textarea>
          <button type="button" class="btn-primary" style="white-space:nowrap;padding:0 16px;" onclick="insertTalkBlock()">💬 吹き出しを挿入</button>
        </div>
      </div>

      <!-- リッチパーツ挿入ツールバー -->
      <div class="toolbar-btns">
        <button type="button" onclick="insertSnippet('## 見出しタイトル\\n')">＋ 大見出し (H2)</button>
        <button type="button" onclick="insertSnippet('### 小見出しタイトル\\n')">＋ 小見出し (H3)</button>
        <button type="button" onclick="insertSnippet('**強調テキスト**')">＋ 太字強調</button>
        <button type="button" onclick="insertSnippet('[point title=\"ここが注目ポイント\"]\\nまとめテキストを入力\\n[/point]\\n')">💡 ポイント枠を挿入</button>
        <button type="button" onclick="insertSnippet('[video yt=\"YouTubeのID\" nc=\"smXXXXXXX\" title=\"楽曲名 / ボカロP名\"]\\n')">🎵 楽曲視聴リンクカードを挿入</button>
      </div>

      <div class="field-group">
        <label class="field-label">記事本文（Markdown ＋ [talk]...[/talk] 対話タグ対応）</label>
        <textarea id="art-body" rows="16" placeholder="ここに記事本文や対話ブロックを入力します..." oninput="syncCurrentForm()"></textarea>
      </div>
    </main>

    <!-- 右パネル：リアルタイム吹き出しプレビュー -->
    <aside class="panel preview-panel">
      <div class="panel-title">
        <span>👁️ リアルタイム表示プレビュー</span>
      </div>
      <div id="live-preview-box"></div>
    </aside>
  </div>

  <script>
    let store = { articles: [], speakers: [] };
    let currentIdx = -1;
    let selectedSpeakerIdx = 0;

    function escapeHtml(str) {
      return String(str || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    async function loadStore() {
      const res = await fetch('/api/store?t=' + Date.now(), { cache: 'no-store' });
      store = await res.json();
      if (!Array.isArray(store.articles)) store.articles = [];
      if (!Array.isArray(store.speakers) || !store.speakers.length) {
        store.speakers = [
          { id: 'spk_1', name: 'チャート分析班', side: 'left', icon: '🎧', color: '#00d2ff' },
          { id: 'spk_2', name: 'ボカロ解説員', side: 'right', icon: '✨', color: '#f97316' }
        ];
      }
      renderSpeakersBar();
      renderSidebarList();
      if (store.articles.length > 0) {
        selectArticle(0);
      } else {
        createNewArticle();
      }
    }

    function renderSpeakersBar() {
      const bar = document.getElementById('speakers-chip-bar');
      bar.innerHTML = store.speakers.map((s, idx) => `
        <div class="speaker-chip ${idx === selectedSpeakerIdx ? 'selected' : ''}" onclick="selectSpeaker(${idx})">
          <span>${escapeHtml(s.icon)}</span>
          <span>${escapeHtml(s.name)} (${s.side === 'right' ? '右' : '左'})</span>
        </div>
      `).join('');
    }

    function selectSpeaker(idx) {
      selectedSpeakerIdx = idx;
      const spk = store.speakers[idx];
      if (spk) {
        document.getElementById('spk-name').value = spk.name || '';
        document.getElementById('spk-side').value = spk.side || 'left';
        document.getElementById('spk-icon').value = spk.icon || '💬';
        document.getElementById('spk-color').value = spk.color || '#00d2ff';
      }
      renderSpeakersBar();
    }

    function addOrUpdateSpeaker() {
      const name = document.getElementById('spk-name').value.trim();
      const side = document.getElementById('spk-side').value;
      const icon = document.getElementById('spk-icon').value.trim() || '💬';
      const color = document.getElementById('spk-color').value.trim() || '#00d2ff';
      if (!name) {
        alert('話し手の名前を入力してください');
        return;
      }
      const existingIdx = store.speakers.findIndex(s => s.name === name);
      const obj = { id: 'spk_' + Date.now(), name, side, icon, color };
      if (existingIdx >= 0) {
        store.speakers[existingIdx] = obj;
        selectedSpeakerIdx = existingIdx;
      } else {
        store.speakers.push(obj);
        selectedSpeakerIdx = store.speakers.length - 1;
      }
      renderSpeakersBar();
    }

    function renderSidebarList() {
      const listEl = document.getElementById('articles-sidebar-list');
      if (!store.articles.length) {
        listEl.innerHTML = '<div style="font-size:0.8rem;color:var(--sub);">まだ記事がありません。「＋ 新規記事」から作成してください。</div>';
        return;
      }
      listEl.innerHTML = store.articles.map((a, idx) => {
        const isDraft = a.status === 'draft';
        const isScheduled = !isDraft && a.publishAt && Date.parse(a.publishAt) > Date.now();
        const badgeClass = isDraft ? 'st-draft' : (isScheduled ? 'st-scheduled' : 'st-published');
        const badgeText = isDraft ? '下書き' : (isScheduled ? '予約中' : '公開');
        return `
          <div class="article-list-item ${idx === currentIdx ? 'active' : ''}" onclick="selectArticle(${idx})">
            <div>
              <span class="item-status ${badgeClass}">${badgeText}</span>
              <span style="font-size:0.74rem;color:var(--accent);">${escapeHtml(a.category || 'コラム')}</span>
            </div>
            <div class="item-title">${escapeHtml(a.title || '(無題の記事)')}</div>
            <div class="item-meta">${escapeHtml(a.publishedAt || '')}</div>
          </div>
        `;
      }).join('');
    }

    function createNewArticle() {
      const today = new Date().toISOString().slice(0, 10);
      const newArt = {
        id: 'col_' + Date.now(),
        title: '',
        category: '対談・コラム',
        status: 'published',
        featured: store.articles.length === 0,
        publishedAt: today,
        publishAt: '',
        author: '週刊VOCALOID複合チャート編集部',
        youtubeId: '',
        thumbnail: '',
        tags: ['ボカロ', 'コラム'],
        summary: '',
        body: ''
      };
      store.articles.unshift(newArt);
      selectArticle(0);
    }

    function selectArticle(idx) {
      currentIdx = idx;
      const a = store.articles[idx];
      if (!a) return;
      document.getElementById('art-title').value = a.title || '';
      document.getElementById('art-category').value = a.category || '対談・コラム';
      document.getElementById('art-status').value = a.status || 'published';
      document.getElementById('art-featured').value = a.featured ? 'true' : 'false';
      document.getElementById('art-pubdate').value = a.publishedAt || '';
      document.getElementById('art-publish-at').value = a.publishAt || '';
      document.getElementById('art-author').value = a.author || '';
      document.getElementById('art-ytid').value = a.youtubeId || '';
      document.getElementById('art-thumb').value = a.thumbnail || '';
      document.getElementById('art-tags').value = Array.isArray(a.tags) ? a.tags.join(', ') : (a.tags || '');
      document.getElementById('art-summary').value = a.summary || '';
      document.getElementById('art-body').value = a.body || '';
      renderSidebarList();
      renderLivePreview();
    }

    function syncCurrentForm() {
      if (currentIdx < 0 || !store.articles[currentIdx]) return;
      const a = store.articles[currentIdx];
      a.title = document.getElementById('art-title').value.trim();
      a.category = document.getElementById('art-category').value;
      a.status = document.getElementById('art-status').value;
      a.featured = document.getElementById('art-featured').value === 'true';
      a.publishedAt = document.getElementById('art-pubdate').value.trim();
      a.publishAt = document.getElementById('art-publish-at').value.trim();
      a.author = document.getElementById('art-author').value.trim();
      a.youtubeId = document.getElementById('art-ytid').value.trim();
      a.thumbnail = document.getElementById('art-thumb').value.trim();
      a.tags = document.getElementById('art-tags').value.split(',').map(t => t.trim()).filter(Boolean);
      a.summary = document.getElementById('art-summary').value;
      a.body = document.getElementById('art-body').value;
      a.updatedAt = new Date().toISOString();
      renderSidebarList();
      renderLivePreview();
    }

    function insertSnippet(snippet) {
      const ta = document.getElementById('art-body');
      const start = ta.selectionStart || ta.value.length;
      const end = ta.selectionEnd || ta.value.length;
      const before = ta.value.slice(0, start);
      const after = ta.value.slice(end);
      const prefix = before && !before.endsWith('\\n') ? '\\n\\n' : '';
      ta.value = before + prefix + snippet + after;
      syncCurrentForm();
      ta.focus();
    }

    function insertTalkBlock() {
      const spk = store.speakers[selectedSpeakerIdx] || store.speakers[0];
      const msgEl = document.getElementById('quick-talk-text');
      const text = msgEl.value.trim();
      if (!text) {
        alert('挿入するセリフを入力してください');
        return;
      }
      const block = `[talk side="${spk.side}" name="${spk.name}" icon="${spk.icon}" color="${spk.color || '#00d2ff'}"]\\n${text}\\n[/talk]\\n`;
      insertSnippet(block);
      msgEl.value = '';
    }

    function deleteCurrentArticle() {
      if (currentIdx < 0 || !store.articles[currentIdx]) return;
      const title = store.articles[currentIdx].title || '(無題の記事)';
      if (!confirm(`記事「${title}」を削除してもよろしいですか？`)) return;
      store.articles.splice(currentIdx, 1);
      if (store.articles.length > 0) {
        selectArticle(0);
      } else {
        currentIdx = -1;
        createNewArticle();
      }
    }

    function renderLivePreview() {
      const box = document.getElementById('live-preview-box');
      if (currentIdx < 0 || !store.articles[currentIdx]) {
        box.innerHTML = '';
        return;
      }
      const a = store.articles[currentIdx];
      let bodyText = escapeHtml(a.body || '');

      // [talk]...[/talk] のプレビュー変換
      bodyText = bodyText.replace(
        /\\[talk\\s+side=&quot;(left|right)&quot;\\s+name=&quot;([^&]*)&quot;\\s+icon=&quot;([^&]*)&quot;(?:\\s+color=&quot;([^&]*)&quot;)?\\]([\\s\\S]*?)\\[\\/talk\\]/gi,
        (_, side, name, icon, color, inner) => {
          const isImg = icon.startsWith('http') || icon.startsWith('/');
          const avatarHtml = isImg ? `<img src="${icon}" alt="${name}">` : `<span>${icon || '💬'}</span>`;
          const col = color || '#00d2ff';
          return `
            <div class="talk-row talk-${side}">
              <div class="talk-speaker-col">
                <div class="talk-avatar" style="border-color:${col};">${avatarHtml}</div>
                <span class="talk-speaker-name">${name}</span>
              </div>
              <div class="talk-bubble" style="--speaker-color:${col};">
                ${inner.trim().replace(/\\n/g, '<br>')}
              </div>
            </div>
          `;
        }
      );

      bodyText = bodyText
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
        .replace(/\\[point\\s+title=&quot;([^&]*)&quot;\\]([\\s\\S]*?)\\[\\/point\\]/gi, '<div class="article-point-box"><strong>💡 $1</strong><br>$2</div>')
        .replace(/\\n\\n+/g, '</p><p>');

      box.innerHTML = `
        <div style="font-size:0.75rem;color:var(--accent);font-weight:700;">${escapeHtml(a.category)} ｜ ${escapeHtml(a.publishedAt)}</div>
        <div class="preview-header-title">${escapeHtml(a.title || '(タイトル未入力)')}</div>
        ${a.summary ? `<div class="preview-lead">${escapeHtml(a.summary).replace(/\\n/g, '<br>')}</div>` : ''}
        <div class="preview-body"><p>${bodyText}</p></div>
      `;
    }

    async function saveStore(doPush = false) {
      syncCurrentForm();
      // タイトルが空の新規記事は除外して保存
      const cleanArticles = store.articles.filter(a => (a.title || '').trim() !== '' || (a.body || '').trim() !== '');
      const payload = { articles: cleanArticles, speakers: store.speakers };

      const toast = document.getElementById('toast');
      toast.textContent = doPush ? '⏳ GitHubへプッシュ中...' : '⏳ 保存中...';
      toast.classList.add('show');

      const res = await fetch('/api/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ store: payload, push: doPush })
      });
      const result = await res.json();
      if (res.ok && result.status === 'ok') {
        toast.textContent = doPush ? '🚀 本番公開完了！' : '✅ 保存完了！';
        if (doPush && result.message) alert(result.message);
        setTimeout(() => toast.classList.remove('show'), 3500);
      } else {
        toast.textContent = '⚠️ エラー';
        alert(result.message || 'エラーが発生しました');
      }
    }

    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        saveStore(false);
      }
    });

    loadStore();
  </script>
</body>
</html>
"""


class ColumnStudioHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _serve_file(self, path: Path, content_type: str):
        if not path.exists() or not path.is_file():
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def do_GET(self):
        clean_path = self.path.split("?")[0]

        if clean_path == "/" or clean_path == "/index":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(STUDIO_HTML.encode("utf-8"))

        elif clean_path == "/preview" or clean_path == "/preview/":
            html_file = BASE_DIR / "index.html"
            if not html_file.exists():
                html_file = BASE_DIR / "public" / "index.html"
            self._serve_file(html_file, "text/html; charset=utf-8")

        elif clean_path in ("/style.css", "/css/style.css"):
            css_file = BASE_DIR / "style.css"
            if not css_file.exists():
                css_file = BASE_DIR / "public" / "style.css"
            self._serve_file(css_file, "text/css; charset=utf-8")

        elif clean_path in ("/app.js", "/js/app.js"):
            js_file = BASE_DIR / "app.js"
            if not js_file.exists():
                js_file = BASE_DIR / "public" / "app.js"
            self._serve_file(js_file, "application/javascript; charset=utf-8")

        elif clean_path.startswith("/data/") or clean_path.startswith("/public/data/"):
            rel = clean_path.lstrip("/")
            cand1 = BASE_DIR / rel
            cand2 = BASE_DIR / "public" / rel
            target = cand1 if cand1.exists() else cand2
            self._serve_file(target, "application/json; charset=utf-8")

        elif clean_path == "/api/store":
            store = ensure_articles_store()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(store, ensure_ascii=False, indent=2).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/save":
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8")
            req = json.loads(raw_body)
            store_data = req.get("store", {"articles": [], "speakers": DEFAULT_SPEAKERS})
            do_push = bool(req.get("push", False))

            ok, msg = save_articles_and_push(store_data, do_push)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps({"status": "ok" if ok else "error", "message": msg}, ensure_ascii=False).encode("utf-8")
            )


def main():
    ensure_articles_store()
    port = find_free_port(START_PORT)
    server = HTTPServer(("127.0.0.1", port), ColumnStudioHandler)
    url = f"http://localhost:{port}"

    print("=" * 68)
    print(f" 📰 記事・コラム執筆スタジオを起動しました: {url}")
    print(" 💬 左右対話吹き出しビルダー・予約公開・無衝突Git Pushが有効です。")
    print(" 終了する時は Ctrl + C を押してください。")
    print("=" * 68)

    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n記事・コラム執筆スタジオを終了しました。")
        server.server_close()


if __name__ == "__main__":
    main()