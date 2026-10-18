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


def run_git(args: list, check: bool = False):
    """Gitコマンドを安全に実行するヘルパー"""
    return subprocess.run(
        ["git"] + args,
        cwd=BASE_DIR,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )


def load_json_safely(path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def merge_user_edits(base_data: dict, user_data: dict) -> dict:
    """ベースデータにユーザーが執筆した総括・解説文・表記修正を確実に統合する"""
    if not base_data:
        return user_data
    if not user_data:
        return base_data

    u_sum = (user_data.get("weeklySummary") or "").strip()
    if u_sum and "初回公開）。日本国内のボカロ新譜から" not in u_sum:
        base_data["weeklySummary"] = u_sum

    user_songs_by_id = {}
    user_songs_by_rank = {}
    for s in user_data.get("songs", []):
        if s.get("song_id"):
            user_songs_by_id[s["song_id"]] = s
        if s.get("rank"):
            user_songs_by_rank[s["rank"]] = s

    for s in base_data.get("songs", []):
        u_song = user_songs_by_id.get(s.get("song_id")) or user_songs_by_rank.get(s.get("rank"))
        if u_song:
            if (u_song.get("commentary") or "").strip():
                s["commentary"] = u_song["commentary"].strip()
            for field in ["title", "producer", "vocal"]:
                if (u_song.get(field) or "").strip():
                    s[field] = u_song[field].strip()

    return base_data


def repair_state_and_rescue_draft():
    """
    起動時にコンフリクト中断状態(rebase/merge)があれば自動解除し、
    バックアップから執筆原稿を100%救出して正常なJSONに復元する。
    """
    backup_data = load_json_safely(BACKUP_FILE)
    current_data = load_json_safely(DRAFT_FILE)

    # 進行中の rebase / merge ロックを強制解除
    run_git(["rebase", "--abort"], check=False)
    run_git(["merge", "--abort"], check=False)

    # 解除後にもう一度読み込み、バックアップの執筆内容と統合
    after_abort_data = load_json_safely(DRAFT_FILE) or current_data or backup_data
    clean_data = merge_user_edits(after_abort_data, backup_data)
    if current_data:
        clean_data = merge_user_edits(clean_data, current_data)

    if clean_data and "songs" in clean_data:
        with open(DRAFT_FILE, "w", encoding="utf-8") as f:
            json.dump(clean_data, f, ensure_ascii=False, indent=2)
        shutil.copyfile(DRAFT_FILE, BACKUP_FILE)
        publish_to_public_site()
        shutil.copyfile(DRAFT_FILE, PUBLIC_LATEST)
        export_markdown_file()
        print("✨ Git競合状態のクリーンアップと執筆原稿の復元が完了しました。")


def conflict_free_save_and_push(new_data: dict, do_push: bool) -> tuple:
    """
    【無衝突保存＆プッシュエンジン】
    Gitの行マージ(pull --rebase)を使わず、メモリ上に原稿を保持したまま
    Gitツリーを origin/main の最新状態に合わせた上でファイルを書き出してプッシュする。
    """
    try:
        # 1. まずローカルのバックアップに編集データを確実に退避
        DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)

        if do_push:
            # 2. 宙ぶらりんの rebase / merge があれば解除
            run_git(["rebase", "--abort"], check=False)
            run_git(["merge", "--abort"], check=False)

            # 3. クラウド(origin/main)の最新コミットを取得し、履歴の先端に合わせる（競合を物理的にゼロにする）
            fetch_res = run_git(["fetch", "origin", "main"], check=False)
            if fetch_res.returncode == 0:
                run_git(["reset", "--hard", "origin/main"], check=False)

        # 4. 最新履歴の上から、今回の編集データ(new_data)を全ターゲットファイルへ書き出す
        with open(DRAFT_FILE, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
        with open(BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)

        publish_to_public_site()
        shutil.copyfile(DRAFT_FILE, PUBLIC_LATEST)
        md_path = export_markdown_file()
        print(f"[保存完了] public/data/latest_ranking.json と {md_path.name} を更新しました。")

        if not do_push:
            return True, "PCへの保存とサイト表示用JSONの更新が完了しました。"

        # 5. 変更をステージングしてコミット＆プッシュ
        run_git(["add", "-A"], check=True)
        status = run_git(["status", "--porcelain"], check=False)
        if status.stdout.strip():
            run_git(["commit", "-m", "執筆スタジオから解説記事を更新・公開"], check=True)

        push_res = run_git(["push", "origin", "main"], check=False)
        if push_res.returncode != 0:
            # 万が一リモート側で直前に別コミットが入った場合でも確実に通すフォールバック
            push_res = run_git(["push", "--force-with-lease", "origin", "main"], check=True)

        return True, "GitHubへのプッシュが完了しました！約1分でCloudflare Pages / 本番サイトに反映されます。"

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
      toast.textContent = doPush ? '⏳ 同期＆GitHubへプッシュ中...' : '⏳ 保存中...';
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
            data = load_json_safely(DRAFT_FILE) or load_json_safely(BACKUP_FILE)
            content = json.dumps(data, ensure_ascii=False, indent=2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif self.path.startswith("/api/markdown"):
            data = load_json_safely(DRAFT_FILE) or load_json_safely(BACKUP_FILE)
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

            if "data" in req_json and "songs" in req_json["data"]:
                new_data = req_json["data"]
                do_push = bool(req_json.get("push", False))
            else:
                new_data = req_json
                do_push = False

            ok, msg = conflict_free_save_and_push(new_data, do_push)
            status_str = "ok" if ok else "error"

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            resp = json.dumps({"status": status_str, "message": msg}, ensure_ascii=False)
            self.wfile.write(resp.encode("utf-8"))


def main():
    # 起動時にGitの競合ロック解除と原稿救出を自動実行
    repair_state_and_rescue_draft()

    if not DRAFT_FILE.exists():
        print(f"エラー: {DRAFT_FILE} が見つかりません。")
        return

    port = find_free_port(START_PORT)
    server = HTTPServer(("127.0.0.1", port), EditorHandler)

    url = f"http://localhost:{port}"
    print("=" * 64)
    print(f" ✍️ 執筆スタジオを起動しました: {url}")
    print(" 競合ゼロの自動同期エンジンが有効です。")
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