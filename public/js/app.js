let chartInstance = null;
let currentData = null;

const DEFAULT_WEIGHTS = {
  yt_views: 1,
  yt_likes: 50,
  yt_comments: 100,
  nc_views: 5,
  nc_mylist: 100,
  nc_comments: 10
};

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    const tabName = btn.getAttribute('data-tab');
    document.getElementById(`tab-${tabName}`).classList.add('active');

    if (tabName === 'insight' && currentData) {
      renderTop5InsightChart(currentData);
    }
  });
});

async function initApp() {
  try {
    const indexRes = await fetch(`./data/archive_index.json?t=${Date.now()}`);
    if (indexRes.ok) {
      const archiveList = await indexRes.json();
      if (Array.isArray(archiveList) && archiveList.length > 0) {
        renderArchiveSelector(archiveList);
      }
    }
    await loadChartData('./data/latest_ranking.json');
  } catch (err) {
    console.error('データの読み込みに失敗しました:', err);
  }
}

function renderArchiveSelector(archiveList) {
  const select = document.getElementById('archive-select');
  if (!select) return;

  select.innerHTML = archiveList.map((item, idx) => {
    const path = idx === 0
      ? './data/latest_ranking.json'
      : `./data/archives/${item.archiveId}.json`;
    return `<option value="${path}">${item.label}</option>`;
  }).join('');

  select.addEventListener('change', (e) => {
    loadChartData(e.target.value);
  });
}

async function loadChartData(jsonPath) {
  const res = await fetch(`${jsonPath}?t=${Date.now()}`);
  const data = await res.json();

  if (!data || !data.songs || data.songs.length === 0) {
    document.getElementById('chart-title').textContent = '現在集計データがありません';
    return;
  }

  currentData = data;
  renderRankingView(data);
  renderTop5InsightChart(data);
}

function calcSongPoints(song, weights) {
  const w = weights || DEFAULT_WEIGHTS;
  const raw = song.raw || {};
  const pts = song.pts || {
    yt_views: (raw.yt_views || 0) * w.yt_views,
    yt_likes: (raw.yt_likes || 0) * w.yt_likes,
    yt_comments: (raw.yt_comments || 0) * w.yt_comments,
    nc_views: (raw.nc_views || 0) * w.nc_views,
    nc_mylist: (raw.nc_mylist || 0) * w.nc_mylist,
    nc_comments: (raw.nc_comments || 0) * w.nc_comments
  };
  const yt_total = pts.yt_views + pts.yt_likes + pts.yt_comments;
  const nc_total = pts.nc_views + pts.nc_mylist + pts.nc_comments;
  const total = yt_total + nc_total || 1;

  return {
    pts,
    yt_total,
    nc_total,
    total: song.total_pt || (yt_total + nc_total),
    yt_share: ((yt_total / total) * 100).toFixed(1),
    nc_share: ((nc_total / total) * 100).toFixed(1),
    seg: {
      yt_views: ((pts.yt_views / total) * 100).toFixed(2),
      yt_likes: ((pts.yt_likes / total) * 100).toFixed(2),
      yt_comments: ((pts.yt_comments / total) * 100).toFixed(2),
      nc_views: ((pts.nc_views / total) * 100).toFixed(2),
      nc_mylist: ((pts.nc_mylist / total) * 100).toFixed(2),
      nc_comments: ((pts.nc_comments / total) * 100).toFixed(2)
    }
  };
}

function formatDiff(rank, prev) {
  if (!prev || prev === "NEW") return `<div class="rank-diff diff-new">NEW</div>`;
  const diff = prev - rank;
  if (diff > 0) return `<div class="rank-diff diff-up">▲${diff}</div>`;
  if (diff < 0) return `<div class="rank-diff diff-down">▼${Math.abs(diff)}</div>`;
  return `<div class="rank-diff" style="color:#94a3b8;">→</div>`;
}

function renderRankingView(data) {
  document.getElementById('chart-title').textContent =
    `${data.publishDate || ''} 公開（集計期間：${data.period || ''}）`;

  document.getElementById('weekly-summary-text').textContent =
    data.weeklySummary || '今週のYouTube・ニコニコ動画6指標による複合ランキング結果です。';

  const container = document.getElementById('ranking-container');
  const analysisContainer = document.getElementById('analysis-container');
  container.innerHTML = '';
  analysisContainer.innerHTML = '';

  const songs = data.songs.slice(0, 20);

  songs.forEach(song => {
    const c = calcSongPoints(song, data.weights);
    const rankClass = song.rank <= 3 ? `rank-${song.rank}` : '';
    const commentaryText = song.commentary && song.commentary.trim() !== ''
      ? song.commentary
      : `YouTube指標 ${c.yt_share}%（${c.yt_total.toLocaleString()}pt）、ニコニコ動画指標 ${c.nc_share}%（${c.nc_total.toLocaleString()}pt）を獲得し総合${song.rank}位にランクイン。`;

    const ytLink = song.youtube_id
      ? `<a class="ext-btn yt" href="https://www.youtube.com/watch?v=${song.youtube_id}" target="_blank" rel="noopener">▶ YouTubeで視聴</a>`
      : '';
    const ncLink = song.niconico_id
      ? `<a class="ext-btn nc" href="https://www.nicovideo.jp/watch/${song.niconico_id}" target="_blank" rel="noopener">▶ ニコニコ動画で視聴</a>`
      : '';

    const card = document.createElement('div');
    card.className = 'rank-card';

    card.innerHTML = `
      <div class="rank-header">
        <div class="rank-num-box">
          <div class="rank-num ${rankClass}">${song.rank}</div>
          ${formatDiff(song.rank, song.prevRank)}
        </div>
        <div class="song-info">
          <div class="song-title-row">
            <h3>${song.title}</h3>
            <button type="button" class="detail-toggle-btn">詳細を見る ▾</button>
          </div>
          <div class="song-meta">
            <span>P: <strong>${song.producer}</strong></span>
            <span>Vocal: ${song.vocal || '-'}</span>
          </div>
        </div>
        <div class="point-box">
          <div class="total-pt">${c.total.toLocaleString()}<span>pt</span></div>
        </div>
      </div>

      <div class="share-bar-wrap">
        <div class="share-bar">
          <div class="seg-yt-views" style="width:${c.seg.yt_views}%" title="YT再生: ${c.pts.yt_views.toLocaleString()}pt"></div>
          <div class="seg-yt-likes" style="width:${c.seg.yt_likes}%" title="YT高評価: ${c.pts.yt_likes.toLocaleString()}pt"></div>
          <div class="seg-yt-comments" style="width:${c.seg.yt_comments}%" title="YTコメント: ${c.pts.yt_comments.toLocaleString()}pt"></div>
          <div class="seg-nc-views" style="width:${c.seg.nc_views}%" title="ニコ動再生: ${c.pts.nc_views.toLocaleString()}pt"></div>
          <div class="seg-nc-mylist" style="width:${c.seg.nc_mylist}%" title="ニコ動マイリス: ${c.pts.nc_mylist.toLocaleString()}pt"></div>
          <div class="seg-nc-comments" style="width:${c.seg.nc_comments}%" title="ニコ動コメント: ${c.pts.nc_comments.toLocaleString()}pt"></div>
        </div>
        <div class="share-labels">
          <span>YouTube計: ${c.yt_share}% (${c.yt_total.toLocaleString()} pt)</span>
          <span>ニコ動計: ${c.nc_share}% (${c.nc_total.toLocaleString()} pt)</span>
        </div>
      </div>

      <div class="detail-panel">
        <div class="ext-links">${ytLink}${ncLink}</div>
        <div class="metrics-grid">
          <div class="metric-box" style="border-left-color: var(--c-yt-views)">
            <div class="metric-name">YouTube 週間再生 (×1)</div>
            <div class="metric-raw">+${(song.raw.yt_views || 0).toLocaleString()}回</div>
            <div class="metric-pt">${c.pts.yt_views.toLocaleString()} pt</div>
          </div>
          <div class="metric-box" style="border-left-color: var(--c-yt-likes)">
            <div class="metric-name">YouTube 週間高評価 (×50)</div>
            <div class="metric-raw">+${(song.raw.yt_likes || 0).toLocaleString()}件</div>
            <div class="metric-pt">${c.pts.yt_likes.toLocaleString()} pt</div>
          </div>
          <div class="metric-box" style="border-left-color: var(--c-yt-comments)">
            <div class="metric-name">YouTube 週間コメント (×100)</div>
            <div class="metric-raw">+${(song.raw.yt_comments || 0).toLocaleString()}件</div>
            <div class="metric-pt">${c.pts.yt_comments.toLocaleString()} pt</div>
          </div>
          <div class="metric-box" style="border-left-color: var(--c-nc-views)">
            <div class="metric-name">ニコ動 週間再生 (×5)</div>
            <div class="metric-raw">+${(song.raw.nc_views || 0).toLocaleString()}回</div>
            <div class="metric-pt">${c.pts.nc_views.toLocaleString()} pt</div>
          </div>
          <div class="metric-box" style="border-left-color: var(--c-nc-mylist)">
            <div class="metric-name">ニコ動 週間マイリス (×100)</div>
            <div class="metric-raw">+${(song.raw.nc_mylist || 0).toLocaleString()}件</div>
            <div class="metric-pt">${c.pts.nc_mylist.toLocaleString()} pt</div>
          </div>
          <div class="metric-box" style="border-left-color: var(--c-nc-comments)">
            <div class="metric-name">ニコ動 週間コメント (×10)</div>
            <div class="metric-raw">+${(song.raw.nc_comments || 0).toLocaleString()}件</div>
            <div class="metric-pt">${c.pts.nc_comments.toLocaleString()} pt</div>
          </div>
        </div>
        <div class="commentary-box">
          <strong>【指標動向・楽曲解説】</strong> ${commentaryText}
        </div>
      </div>
    `;

    // 「詳細を見る」ボタンのクリックイベントを設定
    const detailBtn = card.querySelector('.detail-toggle-btn');
    detailBtn.addEventListener('click', () => {
      const isOpen = card.classList.toggle('open');
      detailBtn.textContent = isOpen ? '詳細を閉じる ▴' : '詳細を見る ▾';
    });

    container.appendChild(card);

    analysisContainer.innerHTML += `
      <h2>${song.rank}位：${song.producer}「${song.title}」（${c.total.toLocaleString()} pt）</h2>
      <p>${commentaryText}</p>
      <p style="font-size:0.85rem; color:#94a3b8;">
        内訳：YT再生 ${c.pts.yt_views.toLocaleString()}pt / YT高評価 ${c.pts.yt_likes.toLocaleString()}pt / YTコメ ${c.pts.yt_comments.toLocaleString()}pt / ニコ動再生 ${c.pts.nc_views.toLocaleString()}pt / ニコ動マイリス ${c.pts.nc_mylist.toLocaleString()}pt / ニコ動コメ ${c.pts.nc_comments.toLocaleString()}pt
      </p>
    `;
  });
}

function renderTop5InsightChart(data) {
  const canvas = document.getElementById('top5Chart');
  const tableContainer = document.getElementById('insight-table-container');
  if (!canvas || typeof Chart === 'undefined') return;

  const top5 = data.songs.slice(0, 5);

  if (chartInstance) {
    chartInstance.destroy();
  }

  const labels = top5.map(s => `${s.rank}位: ${s.title}`);
  const calcList = top5.map(s => calcSongPoints(s, data.weights));

  chartInstance = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'YT再生(×1)', data: calcList.map(c => c.pts.yt_views), backgroundColor: '#ef4444' },
        { label: 'YT高評価(×50)', data: calcList.map(c => c.pts.yt_likes), backgroundColor: '#f97316' },
        { label: 'YTコメ(×100)', data: calcList.map(c => c.pts.yt_comments), backgroundColor: '#eab308' },
        { label: 'ニコ再生(×5)', data: calcList.map(c => c.pts.nc_views), backgroundColor: '#3b82f6' },
        { label: 'ニコマイリス(×100)', data: calcList.map(c => c.pts.nc_mylist), backgroundColor: '#06b6d4' },
        { label: 'ニココメ(×10)', data: calcList.map(c => c.pts.nc_comments), backgroundColor: '#8b5cf6' }
      ]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          stacked: true,
          ticks: { color: '#94a3b8' },
          grid: { color: 'rgba(148, 163, 184, 0.15)' }
        },
        y: {
          stacked: true,
          ticks: { color: '#f8fafc', font: { size: 13, weight: 'bold' } },
          grid: { display: false }
        }
      },
      plugins: {
        legend: { labels: { color: '#f8fafc' } },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${Number(ctx.raw).toLocaleString()} pt`
          }
        }
      }
    }
  });

  if (tableContainer) {
    const rows = top5.map((s, idx) => {
      const c = calcList[idx];
      return `
        <tr>
          <td><strong>${s.rank}位</strong></td>
          <td>${s.title} <span style="color:#94a3b8;font-size:0.8rem;">(${s.producer})</span></td>
          <td><strong>${c.total.toLocaleString()} pt</strong></td>
          <td style="color:#f87171;">${c.yt_share}% (${c.yt_total.toLocaleString()} pt)</td>
          <td style="color:#60a5fa;">${c.nc_share}% (${c.nc_total.toLocaleString()} pt)</td>
        </tr>
      `;
    }).join('');

    tableContainer.innerHTML = `
      <table class="rule-table">
        <thead>
          <tr>
            <th>順位</th>
            <th>楽曲名 (ボカロP)</th>
            <th>総合ポイント</th>
            <th>YouTube比率 (獲得pt)</th>
            <th>ニコニコ動画比率 (獲得pt)</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }
}

document.addEventListener('DOMContentLoaded', initApp);