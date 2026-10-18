import json
import shutil
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import DRAFT_FILE
from export_blog import generate_markdown_from_data, export_markdown_file

PORT = 8765
BACKUP_FILE = DRAFT_FILE.parent / "weekly_draft.backup.json"

EDITOR_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>執筆スタジオ | 週刊VOCALOID複合ランキング</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: #1e293b;
      --input-bg: #0b1120;
      --text: #f8fafc;
      --sub: #94a3b8;
      --accent: #38bdf8;
      --green: #22c55e;
      --border: #334155;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: "Helvetica Neue", Arial, "Hiragino Kaku Gothic ProN", "Hiragino Sans", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding-bottom: 80px;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 100;
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }
    .title-area h1 { font-size: 1.2rem; font-weight: 800; }
    .title-area span { font-size: 0.82rem; color: var(--sub); }
    .actions { display: flex; gap: 10px; align-items: center; }
    button {
      border: none;
      border-radius: 6px;
      padding: 9px 16px;
      font-size: 0.88rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s;
    }
    .btn-save { background: var(--accent); color: #0f172a; }
    .btn-save:hover { opacity: 0.9; transform: translateY(-1px); }
    .btn-md { background: #334155; color: var(--text); border: 1px solid var(--accent); }
    .btn-md:hover { background: #475569; }
    .status-toast {
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--green);
      opacity: 0;
      transition: opacity 0.3s;
    }
    .status-toast.show { opacity: 1; }

    main { max-width: 1040px; margin: 24px auto; padding: 0 20px; }
    .summary-card, .song-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
      margin-bottom: 18px;
    }
    .summary-card h2 {
      font-size: 1.05rem;
      color: var(--accent);
      margin-bottom: 8px;
    }
    .helper { font-size: 0.8rem; color: var(--sub); margin-bottom: 10px; }
    textarea, input[type="text"] {
      width: 100%;
      background: var(--input-bg);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px 12px;
      font-size: 0.92rem;
      font-family: inherit;
      line-height: 1.6;
    }
    textarea:focus, input[type="text"]:focus {
      outline: none;
      border-color: var(--accent);
    }
    .song-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--border);
    }
    .rank-badge {
      font-size: 1.3rem;
      font-weight: 900;
      color: var(--accent);
      min-width: 56px;
    }
    .stats-summary { font-size: 0.82rem; color: var(--sub); }
    .stats-summary strong { color: var(--text); font-size: 0.95rem; }
    .links a {
      font-size: 0.78rem;
      color: var(--accent);
      text-decoration: none;
      margin-left: 10px;
    }
    .meta-inputs {
      display: grid;
      grid-template-columns: 2fr 1.5fr 1.5fr;
      gap: 10px;
      margin-bottom: 12px;
    }
    .field-label {
      font-size: 0.75rem;
      color: var(--sub);
      margin-bottom: 4px;
      display: flex;
      justify-content: space-between;
    }

    /* Markdownモーダル */
    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.75);
      z-index: 200;
      justify-content: center;
      align-items: center;
      padding: 20px;
    }
    .modal-backdrop.open { display: flex; }
    .modal-box {
      background: var(--card);
      border: 1px solid var(--accent);
      border-radius: 12px;
      width: 100%;
      max-width: 860px;
      max-height: 88vh;
      display: flex;
      flex-direction: column;
      padding: 20px;
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    #md-preview {
      flex: 1;
      min-height: 420px;
      font-family: Consolas, Monaco, monospace;
      font-size: 0.85rem;
      white-space: pre-wrap;
    }
  </style>
</head>
<body>
  <header>
    <div class="title-area">
      <h1>✍️ 週刊VOCALOID複合ランキング 執筆スタジオ</h1>
      <span id="period-label">読み込み中...</span>
    </div>
    <div class="actions">
      <span id="toast" class="status-toast">✅ 保存＆Markdown出力完了！</span>
      <button type="button" class="btn-md" onclick="openMarkdownModal()">📝 ブログ用Markdownを表示・コピー</button>
      <button type="button" class="btn-save" onclick="saveDraft()">💾 下書きJSONを安全に保存 (Ctrl+S)</button>
    </div>
  </header>

  <main>
    <div class="summary-card">
      <h2>📈 今週のチャート総括（weeklySummary）</h2>
      <div class="helper">※「上位楽曲解説・トレンド分析」タブの先頭や、ブログ記事の導入に表示される全体総括です。改行や「"」「,」も自由に使えます。</div>
      <textarea id="weekly-summary" rows="4" placeholder="今週のチャート全体の傾向や1位楽曲のポイントなどを入力..."></textarea>
    </div>

    <div id="songs-list"></div>
  </main>

  <div id="md-modal" class="modal-backdrop">
    <div class="modal-box">
      <div class="modal-header">
        <h3>📝 ブログ投稿用 Markdown（data/exports/ にも保存されています）</h3>
        <div style="display:flex; gap:8px;">
          <button type="button" class="btn-save" onclick="copyMarkdown()">📋 全文をコピー</button>
          <button type="button" class="btn-md" onclick="closeMarkdownModal()">閉じる</button>
        </div>
      </div>
      <textarea id="md-preview" readonly></textarea>
    </div>
  </div>

  <script>
    let draftData = null;

    async function loadDraft() {
      const res = await fetch('/api/draft');
      draftData = await res.json();
      document.getElementById('period-label').textContent =
        `${draftData.publishDate} 公開分（集計期間: ${draftData.period}）`;
      document.getElementById('weekly-summary').value = draftData.weeklySummary || '';

      const container = document.getElementById('songs-list');
      container.innerHTML = '';

      (draftData.songs || []).forEach((s, idx) => {
        const total = s.total_pt || 1;
        const ytShare = (((s.yt_total_pt || 0) / total) * 100).toFixed(1);
        const ncShare = (((s.nc_total_pt || 0) / total) * 100).toFixed(1);
        const raw = s.raw || {};

        const ytUrl = s.youtube_id ? `https://www.youtube.com/watch?v=${s.youtube_id}` : '';
        const ncUrl = s.niconico_id ? `https://www.nicovideo.jp/watch/${s.niconico_id}` : '';

        const card = document.createElement('div');
        card.className = 'song-card';
        card.innerHTML = `
          <div class="song-top">
            <div>
              <span class="rank-badge">${s.rank}位</span>
              <span class="stats-summary">
                総合 <strong>${(s.total_pt || 0).toLocaleString()} pt</strong>
                （YT: ${ytShare}% / ニコ動: ${ncShare}%）
                ｜ YT再生+${(raw.yt_views||0).toLocaleString()} / 高評価+${(raw.yt_likes||0).toLocaleString()} / ニコ再生+${(raw.nc_views||0).toLocaleString()} / マイリス+${(raw.nc_mylist||0).toLocaleString()}
              </span>
            </div>
            <div class="links">
              ${ytUrl ? `<a href="${ytUrl}" target="_blank" rel="noopener">▶ YouTubeを開く</a>` : ''}
              ${ncUrl ? `<a href="${ncUrl}" target="_blank" rel="noopener">▶ ニコ動を開く</a>` : ''}
            </div>
          </div>

          <div class="meta-inputs">
            <div>
              <div class="field-label"><span>楽曲タイトル</span></div>
              <input type="text" data-idx="${idx}" data-field="title" value="${escapeHtml(s.title || '')}">
            </div>
            <div>
              <div class="field-label"><span>ボカロP名</span></div>
              <input type="text" data-idx="${idx}" data-field="producer" value="${escapeHtml(s.producer || '')}">
            </div>
            <div>
              <div class="field-label"><span>Vocal表記</span></div>
              <input type="text" data-idx="${idx}" data-field="vocal" value="${escapeHtml(s.vocal || '')}">
            </div>
          </div>

          <div>
            <div class="field-label">
              <span>【指標動向・楽曲解説】（空欄の場合は自動でポイント構成比の標準解説が表示されます）</span>
              <span id="char-count-${idx}">${(s.commentary || '').length} 文字</span>
            </div>
            <textarea rows="3" data-idx="${idx}" data-field="commentary"
              oninput="document.getElementById('char-count-${idx}').textContent = this.value.length + ' 文字'"
              placeholder="${s.rank}位「${escapeHtml(s.title)}」の解説やトレンド背景を入力...">${escapeHtml(s.commentary || '')}</textarea>
          </div>
        `;
        container.appendChild(card);
      });
    }

    function escapeHtml(str) {
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function collectFormData() {
      draftData.weeklySummary = document.getElementById('weekly-summary').value.trim();
      document.querySelectorAll('[data-idx]').forEach(el => {
        const idx = Number(el.getAttribute('data-idx'));
        const field = el.getAttribute('data-field');
        draftData.songs[idx][field] = el.value.trim();
      });
      return draftData;
    }

    async function saveDraft() {
      const payload = collectFormData();
      const res = await fetch('/api/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const toast = document.getElementById('toast');
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3000);
      } else {
        alert('保存中にエラーが発生しました。');
      }
    }

    async function openMarkdownModal() {
      await saveDraft();
      const res = await fetch('/api/markdown');
      const data = await res.json();
      document.getElementById('md-preview').value = data.markdown || '';
      document.getElementById('md-modal').classList.add('open');
    }

    function closeMarkdownModal() {
      document.getElementById('md-modal').classList.remove('open');
    }

    async function copyMarkdown() {
      const textarea = document.getElementById('md-preview');
      textarea.select();
      await navigator.clipboard.writeText(textarea.value);
      alert('ブログ用Markdownをクリップボードにコピーしました！noteやはてなブログにそのまま貼り付けられます。');
    }

    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        saveDraft();
      }
    });

    loadDraft();
  </script>
</body>
</html>
"""

class EditorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # ターミナル出力を 깔끔 に保つ

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(EDITOR_HTML.encode("utf-8"))

        elif self.path == "/api/draft":
            with open(DRAFT_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif self.path == "/api/markdown":
            with open(DRAFT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            md_text = generate_markdown_from_data(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"markdown": md_text}, ensure_ascii=False).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/save":
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8")
            new_data = json.loads(raw_body)

            # 直前のファイルをバックアップ
            if DRAFT_FILE.exists():
                shutil.copyfile(DRAFT_FILE, BACKUP_FILE)

            # 安全なJSONフォーマットで保存
            with open(DRAFT_FILE, "w", encoding="utf-8") as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)

            # 同時にMarkdownファイルも自動更新
            md_path = export_markdown_file()
            print(f"[保存完了] weekly_draft.json と {md_path.name} を更新しました。")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')


def main():
    if not DRAFT_FILE.exists():
        print(f"エラー: {DRAFT_FILE} が見つかりません。先に git pull を行ってください。")
        return

    url = f"http://localhost:{PORT}"
    print("=" * 60)
    print(f" ✍️ 執筆スタジオを起動しました: {url}")
    print(" ブラウザが自動で開きます。終了する時は Ctrl + C を押してください。")
    print("=" * 60)
    webbrowser.open(url)

    server = HTTPServer(("127.0.0.1", PORT), EditorHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n執筆スタジオを終了しました。")
        server.server_close()

if __name__ == "__main__":
    main()