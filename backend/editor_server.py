import json
import shutil
import socket
import subprocess
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import BASE_DIR, DRAFT_FILE, PUBLIC_LATEST
from export_blog import generate_markdown_from_data, export_markdown_file
from publish_chart import main as publish_to_public_site

START_PORT = 8765
BACKUP_FILE = DRAFT_FILE.parent / "weekly_draft.backup.json"


def rescue_from_backup_if_needed():
    """
    weekly_draft.backup.json に執筆済みの解説文や総括が残っており、
    現在の weekly_draft.json 側が未記入の場合は自動的に救出・マージして本番ファイルへも反映する。
    """
    if not DRAFT_FILE.exists() or not BACKUP_FILE.exists():
        return

    try:
        with open(DRAFT_FILE, "r", encoding="utf-8") as f:
            current = json.load(f)
        with open(BACKUP_FILE, "r", encoding="utf-8") as f:
            backup = json.load(f)

        rescued = False

        # 全体総括の救出
        b_sum = (backup.get("weeklySummary") or "").strip()
        c_sum = (current.get("weeklySummary") or "").strip()
        if b_sum and b_sum != c_sum and "初回公開）。日本国内のボカロ新譜から" in c_sum:
            current["weeklySummary"] = b_sum
            rescued = True

        # 各楽曲の解説文(commentary)の救出
        backup_map = {}
        for s in backup.get("songs", []):
            key = s.get("song_id") or s.get("title")
            if key and (s.get("commentary") or "").strip():
                backup_map[key] = s["commentary"].strip()

        for s in current.get("songs", []):
            key = s.get("song_id") or s.get("title")
            if key in backup_map and not (s.get("commentary") or "").strip():
                s["commentary"] = backup_map[key]
                rescued = True

        if rescued:
            with open(DRAFT_FILE, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            publish_to_public_site()
            export_markdown_file()
            print("✨ weekly_draft.backup.json から執筆済みの原稿を救出し、本番用データに反映しました！")
    except Exception as e:
        print(f"バックアップ確認スキップ: {e}")


def find_free_port(start_port: int) -> int:
    port = start_port
    while port < start_port + 20:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    return start_port


def git_push_changes() -> tuple:
    """ローカルで保存した変更をGitHubへ自動プッシュする"""
    try:
        subprocess.run(["git", "add", "."], cwd=BASE_DIR, check=True, capture_output=True, text=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=BASE_DIR, capture_output=True, text=True)
        if not status.stdout.strip():
            return True, "変更はすでに最新状態でプッシュ済みです。"

        subprocess.run(
            ["git", "commit", "-m", "執筆スタジオから解説記事を更新・公開"],
            cwd=BASE_DIR,
            check=True,
            capture_output=True,
            text=True
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=BASE_DIR, check=True, capture_output=True, text=True)
        return True, "GitHubへのプッシュが完了しました！約1分でCloudflare Pages / 本番サイトに反映されます。"
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr or e.stdout or str(e)
        return False, f"Gitプッシュ中にエラーが発生しました: {err_msg}"


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
    .actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    button {
      border: none;
      border-radius: 6px;
      padding: 9px 15px;
      font-size: 0.86rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s;
    }
    .btn-save { background: var(--accent); color: #0f172a; }
    .btn-save:hover { opacity: 0.9; }
    .btn-publish { background: var(--green); color: #052e16; }
    .btn-publish:hover { opacity: 0.9; }
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
      <span id="toast" class="status-toast">✅ 保存完了！</span>
      <button type="button" class="btn-md" onclick="openMarkdownModal()">📝 Markdown表示・コピー</button>
      <button type="button" class="btn-save" onclick="saveDraft(false)">💾 PCに保存 (Ctrl+S)</button>
      <button type="button" class="btn-publish" onclick="saveDraft(true)">🚀 保存して本番Webサイトへ公開 (Git Push)</button>
    </div>
  </header>

  <main>
    <div class="summary-card">
      <h2>📈 今週のチャート総括（3つ目のタブ「今週のチャート総括」に反映されます）</h2>
      <div class="helper">※「上位楽曲解説・トレンド分析」タブの先頭およびブログ記事の導入に表示される全体総括です。</div>
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
      const res = await fetch('/api/draft?t=' + Date.now(), { cache: 'no-store' });
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
              <span>【指標動向・楽曲解説】（各曲の「詳細を見る」内 ＆ 3つ目のタブ「上位楽曲解説・トレンド分析」に反映されます）</span>
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

    async function saveDraft(doPush = false) {
      const payload = collectFormData();
      const toast = document.getElementById('toast');
      toast.textContent = doPush ? '⏳ 保存＆GitHubへプッシュ中...' : '⏳ 保存中...';
      toast.classList.add('show');

      const res = await fetch('/api/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: payload, push: doPush })
      });
      const result = await res.json();

      if (res.ok && result.status === 'ok') {
        toast.textContent = doPush ? '🚀 本番公開(Git Push)完了！' : '✅ PC保存＆サイト用データ更新完了！';
        if (doPush && result.message) {
          alert(result.message);
        }
        setTimeout(() => toast.classList.remove('show'), 4000);
      } else {
        toast.textContent = '⚠️ エラーが発生しました';
        alert(result.message || '保存中にエラーが発生しました。');
      }
    }

    async function openMarkdownModal() {
      await saveDraft(false);
      const res = await fetch('/api/markdown?t=' + Date.now(), { cache: 'no-store' });
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
      alert('ブログ用Markdownをクリップボードにコピーしました！');
    }

    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        saveDraft(false);
      }
    });

    loadDraft();
  </script>
</body>
</html>
"""


class EditorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(EDITOR_HTML.encode("utf-8"))

        elif self.path.startswith("/api/draft"):
            with open(DRAFT_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif self.path.startswith("/api/markdown"):
            with open(DRAFT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            md_text = generate_markdown_from_data(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({"markdown": md_text}, ensure_ascii=False).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/save":
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8")
            req_json = json.loads(raw_body)

            # 旧形式・新形式どちらのリクエストにも対応
            if "data" in req_json and "songs" in req_json["data"]:
                new_data = req_json["data"]
                do_push = bool(req_json.get("push", False))
            else:
                new_data = req_json
                do_push = False

            if DRAFT_FILE.exists():
                shutil.copyfile(DRAFT_FILE, BACKUP_FILE)

            # 1. 下書きファイル(weekly_draft.json)を更新
            with open(DRAFT_FILE, "w", encoding="utf-8") as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)

            # 2. 本番サイト用ファイル(public/data/latest_ranking.json と archives/)を確実に上書き更新
            publish_to_public_site()
            shutil.copyfile(DRAFT_FILE, PUBLIC_LATEST)

            # 3. ブログ用Markdownファイルも自動更新
            md_path = export_markdown_file()
            print(f"[保存完了] public/data/latest_ranking.json と {md_path.name} を更新しました。")

            # 4. 「保存して本番Webサイトへ公開」ボタンが押された場合は自動で git push まで実行
            msg = "保存が完了しました。"
            status_str = "ok"
            if do_push:
                ok, push_msg = git_push_changes()
                msg = push_msg
                if not ok:
                    status_str = "error"

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            resp = json.dumps({"status": status_str, "message": msg}, ensure_ascii=False)
            self.wfile.write(resp.encode("utf-8"))


def main():
    if not DRAFT_FILE.exists():
        print(f"エラー: {DRAFT_FILE} が見つかりません。先に git pull を行ってください。")
        return

    # 起動時に backup.json から原稿を自動救出して本番ファイルへ反映
    rescue_from_backup_if_needed()

    port = find_free_port(START_PORT)
    server = HTTPServer(("127.0.0.1", port), EditorHandler)

    url = f"http://localhost:{port}"
    print("=" * 64)
    print(f" ✍️ 執筆スタジオを起動しました: {url}")
    print(" 画面右上の「🚀 保存して本番Webサイトへ公開」を押すと、")
    print(" Git Pushまで自動実行され、Cloudflare Pagesのサイトに反映されます。")
    print(" 終了する時は Ctrl + C を押してください。")
    print("=" * 64)

    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n執筆スタジオを終了しました。")
        server.server_close()


if __name__ == "__main__":
    main()