import json
import shutil
import socket
import subprocess
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import BASE_DIR, DRAFT_FILE, PUBLIC_LATEST
from export_blog import generate_markdown_from_data, export_markdown_file
from publish_chart import main as publish_to_public_site, get_release_datetime_jst, is_chart_released
from build_draft import generate_private_owner_report

JST = timezone(timedelta(hours=9))
START_PORT = 8765
BACKUP_FILE = DRAFT_FILE.parent / "weekly_draft.backup.json"
REPORT_FILE = BASE_DIR / "data" / "reports" / "latest_private_report.md"


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
        base_data["overall_commentary"] = u_sum

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
    さらに水曜13:00前の場合はフライング公開データの自動ロールバック保護も実行する。
    """
    backup_data = load_json_safely(BACKUP_FILE)
    current_data = load_json_safely(DRAFT_FILE)

    run_git(["rebase", "--abort"], check=False)
    run_git(["merge", "--abort"], check=False)

    after_abort_data = load_json_safely(DRAFT_FILE) or current_data or backup_data
    clean_data = merge_user_edits(after_abort_data, backup_data)
    if current_data:
        clean_data = merge_user_edits(clean_data, current_data)

    if clean_data and "songs" in clean_data:
        DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DRAFT_FILE, "w", encoding="utf-8") as f:
            json.dump(clean_data, f, ensure_ascii=False, indent=2)
        shutil.copyfile(DRAFT_FILE, BACKUP_FILE)
        # publish_to_public_site() 内で水曜13:00チェックおよびフライング公開の自動ロールバックを実施
        publish_to_public_site(force_publish=False)
        export_markdown_file()
        generate_private_owner_report(clean_data)
        print("✨ Git競合状態のクリーンアップ・原稿復元・水曜13:00解禁ゲートチェックが完了しました。")


def conflict_free_save_and_push(new_data: dict, do_push: bool, force_publish: bool = False) -> tuple:
    """
    【無衝突保存＆水曜13:00予約プッシュエンジン】
    水曜13:00より前にプッシュした場合は、本番サイトの表示データ(public/data/latest_ranking.json)は
    前週のまま維持し、執筆済みの weekly_draft.json だけを GitHub に予約プッシュする。
    毎週水曜13:00になると GitHub Actions が予約された weekly_draft.json を自動で本番サイトへ公開する。
    """
    try:
        new_data["overall_commentary"] = new_data.get("weeklySummary", "")
        new_data["ranking"] = new_data.get("songs", [])

        DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)

        if do_push:
            run_git(["rebase", "--abort"], check=False)
            run_git(["merge", "--abort"], check=False)

            fetch_res = run_git(["fetch", "origin", "main"], check=False)
            if fetch_res.returncode == 0:
                run_git(["reset", "--hard", "origin/main"], check=False)

        with open(DRAFT_FILE, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
        with open(BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)

        alt_draft = BASE_DIR / "data" / "weekly_draft.json"
        if alt_draft.resolve() != DRAFT_FILE.resolve():
            alt_draft.parent.mkdir(parents=True, exist_ok=True)
            with open(alt_draft, "w", encoding="utf-8") as f:
                json.dump(new_data, f, ensure_ascii=False, indent=2)

        # 水曜13:00に到達しているか（または強制即時公開か）に応じて公開ファイルを制御
        published_now = publish_to_public_site(force_publish=force_publish)
        md_path = export_markdown_file()
        report_path = generate_private_owner_report(new_data)
        release_dt = get_release_datetime_jst(new_data)
        release_str = release_dt.strftime("%Y/%m/%d (水) %H:%M")

        if not do_push:
            if published_now:
                return True, f"PCへの保存と本番用JSONの更新が完了しました。（{md_path.name} / {report_path.name} 更新済）"
            return (
                True,
                f"PCの手元用ドラフトに保存しました！（解禁日時 {release_str} までは手元プレビューでのみ閲覧可能です）",
            )

        run_git(["add", "-A"], check=True)
        status = run_git(["status", "--porcelain"], check=False)
        if status.stdout.strip():
            commit_msg = (
                "執筆スタジオから解説記事を本番公開"
                if published_now
                else f"執筆スタジオから水曜13:00公開用の予約原稿を更新 ({new_data.get('publishDate', '')}分)"
            )
            run_git(["commit", "-m", commit_msg], check=True)

        push_res = run_git(["push", "origin", "main"], check=False)
        if push_res.returncode != 0:
            push_res = run_git(["push", "--force-with-lease", "origin", "main"], check=True)

        if published_now:
            return True, "🚀 GitHubへのプッシュが完了しました！約1分で本番Webサイトに最新ランキングと解説が反映されます。"
        else:
            return (
                True,
                f"🕒 GitHubへの【水曜13:00 予約プッシュ】が完了しました！\n\n"
                f"・現在の本番Webサイトは前週のランキングが維持されています（フライング公開も自動解除済）。\n"
                f"・今回執筆した内容は {release_str} に GitHub Actions によって自動で本番Webサイトへ公開されます。\n"
                f"・自分の手元では上部の「👁️ 手元で本番プレビュー」からいつでも最新状態を確認できます。",
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
      --amber: #f59e0b;
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
      background: rgba(15, 23, 42, 0.96);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }
    .title-area h1 { font-size: 1.18rem; font-weight: 800; }
    .title-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 4px; }
    .title-area span { font-size: 0.82rem; color: var(--sub); }
    .schedule-badge {
      display: inline-block;
      padding: 2px 9px;
      border-radius: 4px;
      font-size: 0.76rem;
      font-weight: 700;
      background: rgba(245, 158, 11, 0.16);
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.45);
    }
    .schedule-badge.released {
      background: rgba(34, 197, 94, 0.16);
      color: #4ade80;
      border-color: rgba(34, 197, 94, 0.45);
    }
    .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    button, .btn-link {
      border: none;
      border-radius: 6px;
      padding: 9px 14px;
      font-size: 0.84rem;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.2s;
    }
    .btn-save { background: var(--accent); color: #0f172a; }
    .btn-save:hover { opacity: 0.9; }
    .btn-publish { background: var(--green); color: #052e16; }
    .btn-publish.scheduled { background: var(--amber); color: #1c1917; }
    .btn-publish:hover { opacity: 0.9; }
    .btn-md { background: #334155; color: var(--text); border: 1px solid var(--accent); }
    .btn-md:hover { background: #475569; }
    .btn-preview { background: #1e293b; color: #38bdf8; border: 1px solid #38bdf8; }
    .btn-preview:hover { background: rgba(56, 189, 248, 0.15); }
    .status-toast {
      font-size: 0.84rem;
      font-weight: 700;
      color: var(--green);
      opacity: 0;
      transition: opacity 0.3s;
    }
    .status-toast.show { opacity: 1; }

    main { max-width: 1060px; margin: 24px auto; padding: 0 20px; }
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
      max-width: 900px;
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
      min-height: 440px;
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
      <div class="title-meta">
        <span id="period-label">読み込み中...</span>
        <span id="schedule-badge" class="schedule-badge">確認中...</span>
      </div>
    </div>
    <div class="actions">
      <span id="toast" class="status-toast">✅ 保存完了！</span>
      <a href="/preview?preview=1" target="_blank" class="btn-link btn-preview" onclick="saveDraft(false)">👁️ 手元で本番プレビュー</a>
      <button type="button" class="btn-md" onclick="openReportModal()">📊 手元用詳細レポート</button>
      <button type="button" class="btn-md" onclick="openMarkdownModal()">📝 ブログ用MD</button>
      <button type="button" class="btn-save" onclick="saveDraft(false)">💾 手元に保存 (Ctrl+S)</button>
      <button type="button" id="publish-btn" class="btn-publish scheduled" onclick="saveDraft(true)">🕒 水曜13:00公開用に予約プッシュ</button>
    </div>
  </header>

  <main>
    <div class="summary-card">
      <h2>📈 今週のチャート総括（「ランキングインサイト・解説」タブの今週のトレンド総評に反映されます）</h2>
      <div class="helper">※水曜13:00より前にプッシュしても本番サイトには出ず、毎週水曜13:00に自動で本番Webサイトへ反映されます。手元での表示確認は右上の「👁️ 手元で本番プレビュー」から行えます。</div>
      <textarea id="weekly-summary" rows="4" placeholder="今週のチャート全体の傾向や1位楽曲のポイントなどを入力..."></textarea>
    </div>

    <div id="songs-list"></div>
  </main>

  <div id="md-modal" class="modal-backdrop">
    <div class="modal-box">
      <div class="modal-header">
        <h3 id="modal-title">📝 プレビュー</h3>
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
      const payload = await res.json();
      draftData = payload.draft || payload;
      const isReleased = Boolean(payload.isReleased);
      const releaseStr = payload.releaseAtFormatted || (draftData.publishDate + ' 13:00 JST');

      document.getElementById('period-label').textContent =
        `${draftData.publishDate} 公開分（集計期間: ${draftData.period}）`;

      const badgeEl = document.getElementById('schedule-badge');
      const pubBtn = document.getElementById('publish-btn');
      if (isReleased) {
        badgeEl.textContent = `✅ 解禁日時到達済（${releaseStr}）`;
        badgeEl.classList.add('released');
        pubBtn.textContent = '🚀 保存して本番Webサイトへ即時公開 (Git Push)';
        pubBtn.classList.remove('scheduled');
      } else {
        badgeEl.textContent = `🔒 本番解禁前：${releaseStr} に自動公開（現在は手元のみ閲覧可）`;
        badgeEl.classList.remove('released');
        pubBtn.textContent = '🕒 保存して水曜13:00公開用に予約プッシュ (Git Push)';
        pubBtn.classList.add('scheduled');
      }

      document.getElementById('weekly-summary').value = draftData.weeklySummary || '';

      const container = document.getElementById('songs-list');
      container.innerHTML = '';

      (draftData.songs || []).forEach((s, idx) => {
        const total = s.total_pt || 1;
        const pts = s.pts || {};
        const ytPt = s.yt_total_pt !== undefined ? s.yt_total_pt : (pts.yt_total || 0);
        const ncPt = s.nc_total_pt !== undefined ? s.nc_total_pt : (pts.nc_total || 0);
        const ytShare = ((ytPt / total) * 100).toFixed(1);
        const ncShare = ((ncPt / total) * 100).toFixed(1);
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
              <span>【指標動向・楽曲解説】（各曲の「詳細を見る」内 ＆ 2つ目のタブ「ランキングインサイト・解説」に反映されます）</span>
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
      const summaryVal = document.getElementById('weekly-summary').value.trim();
      draftData.weeklySummary = summaryVal;
      draftData.overall_commentary = summaryVal;
      document.querySelectorAll('[data-idx]').forEach(el => {
        const idx = Number(el.getAttribute('data-idx'));
        const field = el.getAttribute('data-field');
        draftData.songs[idx][field] = el.value.trim();
      });
      draftData.ranking = draftData.songs;
      return draftData;
    }

    async function saveDraft(doPush = false) {
      const payload = collectFormData();
      const toast = document.getElementById('toast');
      toast.textContent = doPush ? '⏳ GitHubへ同期・プッシュ中...' : '⏳ 手元に保存中...';
      toast.classList.add('show');

      const res = await fetch('/api/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: payload, push: doPush })
      });
      const result = await res.json();

      if (res.ok && result.status === 'ok') {
        toast.textContent = doPush ? '✅ GitHubプッシュ完了！' : '✅ 手元保存完了！';
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
      document.getElementById('modal-title').textContent = '📝 ブログ投稿用 Markdown（data/exports/ にも保存されています）';
      document.getElementById('md-preview').value = data.markdown || '';
      document.getElementById('md-modal').classList.add('open');
    }

    async function openReportModal() {
      await saveDraft(false);
      const res = await fetch('/api/report?t=' + Date.now(), { cache: 'no-store' });
      const data = await res.json();
      document.getElementById('modal-title').textContent = '📊 運営者手元用・ランキング詳細レポート（data/reports/latest_private_report.md）';
      document.getElementById('md-preview').value = data.report || '';
      document.getElementById('md-modal').classList.add('open');
    }

    function closeMarkdownModal() {
      document.getElementById('md-modal').classList.remove('open');
    }

    async function copyMarkdown() {
      const textarea = document.getElementById('md-preview');
      textarea.select();
      await navigator.clipboard.writeText(textarea.value);
      alert('クリップボードにコピーしました！');
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

    def _serve_static_file(self, file_path: Path, content_type: str):
        if not file_path.exists() or not file_path.is_file():
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def do_GET(self):
        clean_path = self.path.split("?")[0]

        if clean_path == "/" or clean_path == "/index":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(EDITOR_HTML.encode("utf-8"))

        elif clean_path == "/preview" or clean_path == "/preview/":
            # 手元で本番Webサイトと全く同じデザインをプレビューできるエンドポイント
            html_file = BASE_DIR / "index.html"
            if not html_file.exists():
                html_file = BASE_DIR / "public" / "index.html"
            self._serve_static_file(html_file, "text/html; charset=utf-8")

        elif clean_path in ("/style.css", "/css/style.css"):
            css_file = BASE_DIR / "style.css"
            if not css_file.exists():
                css_file = BASE_DIR / "public" / "style.css"
            self._serve_static_file(css_file, "text/css; charset=utf-8")

        elif clean_path in ("/app.js", "/js/app.js"):
            js_file = BASE_DIR / "app.js"
            if not js_file.exists():
                js_file = BASE_DIR / "public" / "app.js"
            self._serve_static_file(js_file, "application/javascript; charset=utf-8")

        elif clean_path.startswith("/data/") or clean_path.startswith("/public/data/"):
            # 手元プレビュー時に latest_ranking.json がリクエストされたら、最新の weekly_draft.json を返す
            if clean_path.endswith("latest_ranking.json") or clean_path.endswith("weekly_draft.json"):
                data = load_json_safely(DRAFT_FILE) or load_json_safely(BACKUP_FILE)
                content = json.dumps(data, ensure_ascii=False, indent=2)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
                return

            rel = clean_path.lstrip("/")
            cand1 = BASE_DIR / rel
            cand2 = BASE_DIR / "public" / rel
            target = cand1 if cand1.exists() else cand2
            self._serve_static_file(target, "application/json; charset=utf-8")

        elif clean_path.startswith("/api/draft"):
            data = load_json_safely(DRAFT_FILE) or load_json_safely(BACKUP_FILE)
            now_dt = datetime.now(JST)
            rel_dt = get_release_datetime_jst(data)
            payload = {
                "draft": data,
                "isReleased": is_chart_released(data, now_dt),
                "releaseAtFormatted": rel_dt.strftime("%Y/%m/%d (水) %H:%M JST"),
            }
            content = json.dumps(payload, ensure_ascii=False, indent=2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif clean_path.startswith("/api/markdown"):
            data = load_json_safely(DRAFT_FILE) or load_json_safely(BACKUP_FILE)
            md_text = generate_markdown_from_data(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({"markdown": md_text}, ensure_ascii=False).encode("utf-8"))

        elif clean_path.startswith("/api/report"):
            data = load_json_safely(DRAFT_FILE) or load_json_safely(BACKUP_FILE)
            report_path = generate_private_owner_report(data)
            report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({"report": report_text}, ensure_ascii=False).encode("utf-8"))

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
                force_pub = bool(req_json.get("forcePublish", False))
            else:
                new_data = req_json
                do_push = False
                force_pub = False

            ok, msg = conflict_free_save_and_push(new_data, do_push, force_publish=force_pub)
            status_str = "ok" if ok else "error"

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            resp = json.dumps({"status": status_str, "message": msg}, ensure_ascii=False)
            self.wfile.write(resp.encode("utf-8"))


def main():
    repair_state_and_rescue_draft()

    if not DRAFT_FILE.exists():
        print(f"エラー: {DRAFT_FILE} が見つかりません。")
        return

    port = find_free_port(START_PORT)
    server = HTTPServer(("127.0.0.1", port), EditorHandler)

    url = f"http://localhost:{port}"
    preview_url = f"http://localhost:{port}/preview?preview=1"
    print("=" * 68)
    print(f" ✍️ 執筆スタジオを起動しました: {url}")
    print(f" 👁️ 手元専用のWebサイトプレビュー: {preview_url}")
    print(" 🕒 水曜13:00より前のプッシュは自動的に「予約プッシュ」となり、")
    print("    毎週水曜13:00にGitHub Actionsで本番サイトへ自動公開されます。")
    print(" 終了する時は Ctrl + C を押してください。")
    print("=" * 68)

    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n執筆スタジオを終了しました。")
        server.server_close()


if __name__ == "__main__":
    main()