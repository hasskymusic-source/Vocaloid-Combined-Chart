let insightChartInstance = null;
let currentChartData = null;
let archiveHistoryCache = [];

const WEIGHTS = {
  yt_views: 1,
  yt_likes: 50,
  yt_comments: 100,
  nc_views: 5,
  nc_mylists: 100,
  nc_comments: 10,
};

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initChartApp();
});

function initTabs() {
  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabContents = document.querySelectorAll(".tab-content");

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-tab");
      tabButtons.forEach((b) => b.classList.remove("active"));
      tabContents.forEach((c) => c.classList.remove("active"));

      btn.classList.add("active");
      const targetEl = document.getElementById(targetId);
      if (targetEl) {
        targetEl.classList.add("active");
      }

      if (targetId === "tab-insight" && currentChartData) {
        renderTop5InsightChart(currentChartData.ranking || []);
      }
    });
  });
}

async function fetchJsonWithFallback(urls) {
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (res.ok) {
        return await res.json();
      }
    } catch (_) {
      // 次の候補URLを試行
    }
  }
  return null;
}

function getSongIdentityKeys(song) {
  const keys = [];
  if (song.song_id) keys.push(`id:${song.song_id}`);
  if (song.id) keys.push(`id:${song.id}`);
  if (song.youtube_id) keys.push(`yt:${song.youtube_id}`);
  if (song.niconico_id) keys.push(`nc:${song.niconico_id}`);
  if (song.title && song.producer) keys.push(`tp:${song.title}__${song.producer}`);
  return keys;
}

async function loadArchiveHistory() {
  const indexData = await fetchJsonWithFallback([
    "data/archives/archive_index.json",
    "public/data/archives/archive_index.json",
    "data/archive_index.json",
  ]);

  const selectEl = document.getElementById("archive-select");
  if (!indexData || !Array.isArray(indexData.archives)) {
    return;
  }

  // アーカイブプルダウンの構築
  if (selectEl) {
    indexData.archives.forEach((item) => {
      const opt = document.createElement("option");
      opt.value = item.file || item.path || item.id;
      opt.textContent = item.label || item.period || item.id;
      selectEl.appendChild(opt);
    });

    selectEl.addEventListener("change", async (e) => {
      const val = e.target.value;
      if (val === "latest") {
        await loadAndRenderChart();
      } else {
        const archiveData = await fetchJsonWithFallback([
          `data/archives/${val}`,
          `public/data/archives/${val}`,
          val,
        ]);
        if (archiveData) {
          enrichWithHistory(archiveData);
          currentChartData = archiveData;
          renderAllViews(archiveData);
        }
      }
    });
  }

  // 過去アーカイブを読み込んでチャートイン回数・前週比のフロントエンド補完用キャッシュを作成
  const loadedArchives = [];
  for (const item of indexData.archives) {
    const file = item.file || item.path || item.id;
    if (!file) continue;
    const data = await fetchJsonWithFallback([
      `data/archives/${file}`,
      `public/data/archives/${file}`,
      file,
    ]);
    if (data && Array.isArray(data.ranking)) {
      loadedArchives.push(data);
    }
  }
  archiveHistoryCache = loadedArchives;
}

function enrichWithHistory(chartData) {
  if (!chartData || !Array.isArray(chartData.ranking)) return;

  // 過去アーカイブキャッシュがある場合は通算回数と前週ポイントを補完
  const targetPeriod = chartData.period || chartData.updated_at || "";
  const olderCharts = archiveHistoryCache.filter((c) => {
    const p = c.period || c.updated_at || "";
    return p && targetPeriod ? p < targetPeriod : false;
  });

  const prevChart = olderCharts.length > 0 ? olderCharts[olderCharts.length - 1] : null;

  chartData.ranking.forEach((song) => {
    const keys = getSongIdentityKeys(song);

    // 1. チャートイン回数の補完（JSONに chart_in_count があればそれを優先、なければ履歴から算出）
    if (typeof song.chart_in_count !== "number" || song.chart_in_count < 1) {
      let count = 1;
      olderCharts.forEach((past) => {
        const matched = (past.ranking || []).slice(0, 20).some((ps) => {
          const pKeys = getSongIdentityKeys(ps);
          return keys.some((k) => pKeys.includes(k));
        });
        if (matched) count += 1;
      });
      song.chart_in_count = count;
    }

    // 2. 前週ポイント・ポイント前週比率の補完
    if (song.prev_total_pt === undefined && prevChart) {
      const prevSong = (prevChart.ranking || []).find((ps) => {
        const pKeys = getSongIdentityKeys(ps);
        return keys.some((k) => pKeys.includes(k));
      });
      if (prevSong && typeof prevSong.total_pt === "number") {
        song.prev_total_pt = prevSong.total_pt;
      }
    }

    if (
      (song.pt_ratio === undefined || song.pt_ratio === null) &&
      typeof song.prev_total_pt === "number" &&
      song.prev_total_pt > 0
    ) {
      song.pt_ratio = Math.round((song.total_pt / song.prev_total_pt) * 100);
    }
  });
}

async function initChartApp() {
  await loadArchiveHistory();
  await loadAndRenderChart();
}

async function loadAndRenderChart() {
  const data = await fetchJsonWithFallback([
    "data/latest_ranking.json",
    "public/data/latest_ranking.json",
    "data/drafts/weekly_draft.json",
    "weekly_draft.json",
    "latest_ranking.json",
  ]);

  if (!data) {
    const container = document.getElementById("ranking-container");
    if (container) {
      container.innerHTML = `<div class="error-state">ランキングデータの読み込みに失敗しました。</div>`;
    }
    return;
  }

  enrichWithHistory(data);
  currentChartData = data;
  renderAllViews(data);
}

function renderAllViews(data) {
  const periodEl = document.getElementById("chart-period");
  if (periodEl) {
    periodEl.textContent = data.period || data.updated_at || "最新チャート";
  }

  const ranking = Array.isArray(data.ranking) ? data.ranking : [];
  renderRankingView(ranking);
  renderTop5InsightChart(ranking);
  renderInsightTable(ranking);
  renderCommentaryView(data, ranking);
}

function getPointsBreakdown(song) {
  const raw = song.raw || {};
  const pts = song.pts || {};

  const yt_views = pts.yt_views !== undefined ? pts.yt_views : (raw.yt_views || 0) * WEIGHTS.yt_views;
  const yt_likes = pts.yt_likes !== undefined ? pts.yt_likes : (raw.yt_likes || 0) * WEIGHTS.yt_likes;
  const yt_comments = pts.yt_comments !== undefined ? pts.yt_comments : (raw.yt_comments || 0) * WEIGHTS.yt_comments;

  const nc_views = pts.nc_views !== undefined ? pts.nc_views : (raw.nc_views || 0) * WEIGHTS.nc_views;
  const nc_mylists = pts.nc_mylists !== undefined ? pts.nc_mylists : (raw.nc_mylists || 0) * WEIGHTS.nc_mylists;
  const nc_comments = pts.nc_comments !== undefined ? pts.nc_comments : (raw.nc_comments || 0) * WEIGHTS.nc_comments;

  const yt_total = pts.yt_total !== undefined ? pts.yt_total : yt_views + yt_likes + yt_comments;
  const nc_total = pts.nc_total !== undefined ? pts.nc_total : nc_views + nc_mylists + nc_comments;
  const total_pt = song.total_pt !== undefined ? song.total_pt : yt_total + nc_total;

  return {
    yt_views,
    yt_likes,
    yt_comments,
    nc_views,
    nc_mylists,
    nc_comments,
    yt_total,
    nc_total,
    total_pt,
  };
}

function formatRankDiffBadge(song) {
  const prev = song.prev_rank;
  const curr = song.rank;
  if (!prev || prev === null) {
    return `<span class="rank-diff diff-new">NEW</span>`;
  }
  if (prev > curr) {
    return `<span class="rank-diff diff-up">▲${prev - curr} (前週${prev}位)</span>`;
  }
  if (prev < curr) {
    return `<span class="rank-diff diff-down">▼${curr - prev} (前週${prev}位)</span>`;
  }
  return `<span class="rank-diff diff-stay">→ KEEP (前週${prev}位)</span>`;
}

/**
 * ポイント前週比率のフォーマット
 * 例: 2,000,000pt -> 3,000,000pt の場合は緑色で「∧150%」
 * ポイントが下がっていた場合は赤色で「∨75%」
 */
function formatPointRatioHTML(song) {
  let ratio = song.pt_ratio;
  if (
    (ratio === undefined || ratio === null) &&
    typeof song.prev_total_pt === "number" &&
    song.prev_total_pt > 0
  ) {
    ratio = Math.round((song.total_pt / song.prev_total_pt) * 100);
  }

  if (ratio === undefined || ratio === null || isNaN(ratio)) {
    return `<span class="pt-ratio-new">NEW</span>`;
  }

  const roundedRatio = Math.round(ratio);
  const isUp =
    typeof song.prev_total_pt === "number"
      ? song.total_pt > song.prev_total_pt
      : roundedRatio > 100;
  const isDown =
    typeof song.prev_total_pt === "number"
      ? song.total_pt < song.prev_total_pt
      : roundedRatio < 100;

  if (isUp) {
    return `<span class="pt-ratio-up">∧${roundedRatio}%</span>`;
  } else if (isDown) {
    return `<span class="pt-ratio-down">∨${roundedRatio}%</span>`;
  } else {
    return `<span class="pt-ratio-stay">→${roundedRatio}%</span>`;
  }
}

function renderRankingView(ranking) {
  const container = document.getElementById("ranking-container");
  if (!container) return;

  if (!ranking.length) {
    container.innerHTML = `<div class="empty-state">表示できるランキングデータがありません。</div>`;
    return;
  }

  container.innerHTML = ranking
    .slice(0, 20)
    .map((song) => {
      const bd = getPointsBreakdown(song);
      const raw = song.raw || {};
      const ytPercent = bd.total_pt > 0 ? ((bd.yt_total / bd.total_pt) * 100).toFixed(1) : "0.0";
      const ncPercent = bd.total_pt > 0 ? ((bd.nc_total / bd.total_pt) * 100).toFixed(1) : "0.0";
      const chartInCount = song.chart_in_count || 1;
      const thumbUrl =
        song.thumbnail ||
        (song.youtube_id ? `https://i.ytimg.com/vi/${song.youtube_id}/mqdefault.jpg` : "");

      return `
      <article class="rank-card rank-${song.rank}" data-rank="${song.rank}">
        <div class="rank-card-summary" onclick="toggleRankDetail(${song.rank})">
          <div class="rank-number-col">
            <span class="rank-number">${song.rank}<small>位</small></span>
            ${formatRankDiffBadge(song)}
            <span class="chart-in-mini">${chartInCount}週目</span>
          </div>

          ${
            thumbUrl
              ? `<div class="rank-thumb-col">
                   <img src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(song.title)}" class="rank-thumb" loading="lazy" />
                 </div>`
              : ""
          }

          <div class="rank-info-col">
            <h3 class="song-title">${escapeHtml(song.title)}</h3>
            <div class="song-meta">
              <span class="song-producer">${escapeHtml(song.producer)}</span>
              ${song.vocal ? `<span class="song-vocal">feat. ${escapeHtml(song.vocal)}</span>` : ""}
            </div>
            <div class="platform-bar">
              <div class="platform-bar-yt" style="width: ${ytPercent}%" title="YouTube ${ytPercent}%"></div>
              <div class="platform-bar-nc" style="width: ${ncPercent}%" title="ニコニコ動画 ${ncPercent}%"></div>
            </div>
          </div>

          <div class="rank-points-col">
            <div class="total-points">${Number(bd.total_pt).toLocaleString()} <small>pt</small></div>
            <div class="points-sub-row">
              <span>前週比: ${formatPointRatioHTML(song)}</span>
              <span class="platform-split-text">YT ${ytPercent}% / NC ${ncPercent}%</span>
            </div>
          </div>
        </div>

        <div id="detail-panel-${song.rank}" class="rank-detail-panel">
          <div class="detail-grid">
            <div class="detail-box yt-detail-box">
              <h4>YouTube 指標内訳 (${Number(bd.yt_total).toLocaleString()} pt / ${ytPercent}%)</h4>
              <ul>
                <li><span>週間再生数:</span> <strong>+${Number(raw.yt_views || 0).toLocaleString()}</strong> (${Number(bd.yt_views).toLocaleString()} pt)</li>
                <li><span>週間高評価数:</span> <strong>+${Number(raw.yt_likes || 0).toLocaleString()}</strong> (${Number(bd.yt_likes).toLocaleString()} pt)</li>
                <li><span>週間コメント数:</span> <strong>+${Number(raw.yt_comments || 0).toLocaleString()}</strong> (${Number(bd.yt_comments).toLocaleString()} pt)</li>
              </ul>
              ${
                song.youtube_id
                  ? `<a href="https://www.youtube.com/watch?v=${encodeURIComponent(song.youtube_id)}" target="_blank" rel="noopener noreferrer" class="video-link yt-link">▶ YouTubeで視聴する</a>`
                  : ""
              }
            </div>

            <div class="detail-box nc-detail-box">
              <h4>ニコニコ動画 指標内訳 (${Number(bd.nc_total).toLocaleString()} pt / ${ncPercent}%)</h4>
              <ul>
                <li><span>週間再生数:</span> <strong>+${Number(raw.nc_views || 0).toLocaleString()}</strong> (${Number(bd.nc_views).toLocaleString()} pt)</li>
                <li><span>週間マイリスト数:</span> <strong>+${Number(raw.nc_mylists || 0).toLocaleString()}</strong> (${Number(bd.nc_mylists).toLocaleString()} pt)</li>
                <li><span>週間コメント数:</span> <strong>+${Number(raw.nc_comments || 0).toLocaleString()}</strong> (${Number(bd.nc_comments).toLocaleString()} pt)</li>
              </ul>
              ${
                song.niconico_id
                  ? `<a href="https://www.nicovideo.jp/watch/${encodeURIComponent(song.niconico_id)}" target="_blank" rel="noopener noreferrer" class="video-link nc-link">▶ ニコニコ動画で視聴する</a>`
                  : ""
              }
            </div>
          </div>

          ${
            song.commentary
              ? `<div class="commentary-box">
                   <h5>楽曲解説・チャート分析</h5>
                   <p>${escapeHtml(song.commentary).replace(/\n/g, "<br>")}</p>
                 </div>`
              : ""
          }
        </div>
      </article>
      `;
    })
    .join("");
}

window.toggleRankDetail = function (rank) {
  const panel = document.getElementById(`detail-panel-${rank}`);
  if (panel) {
    panel.classList.toggle("open");
  }
};

/**
 * ランキングインサイト：TOP 10 の積み上げ棒グラフを描画
 */
function renderTop5InsightChart(ranking) {
  const canvas = document.getElementById("top5Chart");
  if (!canvas || typeof Chart === "undefined") return;

  const top10 = ranking.slice(0, 10);
  const labels = top10.map((s) => `${s.rank}位: ${s.title}`);
  const breakdowns = top10.map((s) => getPointsBreakdown(s));

  if (insightChartInstance) {
    insightChartInstance.destroy();
  }

  const ctx = canvas.getContext("2d");
  insightChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "YouTube 再生",
          data: breakdowns.map((b) => b.yt_views),
          backgroundColor: "#ef4444",
        },
        {
          label: "YouTube 高評価",
          data: breakdowns.map((b) => b.yt_likes),
          backgroundColor: "#f87171",
        },
        {
          label: "YouTube コメント",
          data: breakdowns.map((b) => b.yt_comments),
          backgroundColor: "#fca5a5",
        },
        {
          label: "ニコ動 再生",
          data: breakdowns.map((b) => b.nc_views),
          backgroundColor: "#2563eb",
        },
        {
          label: "ニコ動 マイリス",
          data: breakdowns.map((b) => b.nc_mylists),
          backgroundColor: "#60a5fa",
        },
        {
          label: "ニコ動 コメント",
          data: breakdowns.map((b) => b.nc_comments),
          backgroundColor: "#93c5fd",
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          stacked: true,
          ticks: { color: "#94a3b8" },
          grid: { color: "rgba(148, 163, 184, 0.12)" },
        },
        y: {
          stacked: true,
          ticks: { color: "#f8fafc", font: { weight: "600" } },
          grid: { display: false },
        },
      },
      plugins: {
        legend: {
          labels: { color: "#e2e8f0" },
        },
        tooltip: {
          callbacks: {
            label: function (context) {
              const val = Number(context.raw || 0).toLocaleString();
              return `${context.dataset.label}: ${val} pt`;
            },
          },
        },
      },
    },
  });
}

/**
 * ランキングインサイト：TOP 10 プラットフォーム別・指標構成比データ テーブルを描画
 * 列構成: 順位 | 楽曲名 (ボカロP) | 総合ポイント | ポイント前週比率 | チャートイン回数 | YouTube比率 (獲得pt) | ニコニコ動画比率 (獲得pt)
 */
function renderInsightTable(ranking) {
  const tbody =
    document.getElementById("insight-table-body") ||
    document.querySelector("#insight-table-container tbody");
  if (!tbody) return;

  const top10 = ranking.slice(0, 10);
  if (!top10.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="loading-cell">データがありません。</td></tr>`;
    return;
  }

  tbody.innerHTML = top10
    .map((song) => {
      const bd = getPointsBreakdown(song);
      const ytRatio = bd.total_pt > 0 ? ((bd.yt_total / bd.total_pt) * 100).toFixed(1) : "0.0";
      const ncRatio = bd.total_pt > 0 ? ((bd.nc_total / bd.total_pt) * 100).toFixed(1) : "0.0";
      const chartInCount = song.chart_in_count || 1;

      return `
        <tr>
          <td class="col-rank">${song.rank}位</td>
          <td class="col-song">
            <span class="insight-song-title">${escapeHtml(song.title)}</span>
            <span class="insight-song-producer">(${escapeHtml(song.producer)})</span>
          </td>
          <td class="col-total-pt">${Number(bd.total_pt).toLocaleString()} pt</td>
          <td class="col-pt-ratio">${formatPointRatioHTML(song)}</td>
          <td class="col-chart-in">${chartInCount}回</td>
          <td class="col-yt-ratio">${ytRatio}% (${Number(bd.yt_total).toLocaleString()} pt)</td>
          <td class="col-nc-ratio">${ncRatio}% (${Number(bd.nc_total).toLocaleString()} pt)</td>
        </tr>
      `;
    })
    .join("");
}

function renderCommentaryView(data, ranking) {
  const overallEl = document.getElementById("overall-commentary");
  if (overallEl) {
    const overallText = data.overall_commentary || data.trend_analysis || "";
    overallEl.innerHTML = overallText
      ? `<p>${escapeHtml(overallText).replace(/\n/g, "<br>")}</p>`
      : `<p class="muted-text">今週の全体総評はまだ登録されていません。</p>`;
  }

  const listEl = document.getElementById("commentary-container");
  if (!listEl) return;

  const commentedSongs = ranking.filter((s) => s.commentary && String(s.commentary).trim() !== "");
  if (!commentedSongs.length) {
    listEl.innerHTML = `<div class="empty-state">楽曲別の解説はまだ登録されていません。</div>`;
    return;
  }

  listEl.innerHTML = commentedSongs
    .map(
      (song) => `
      <div class="commentary-card">
        <div class="commentary-card-header">
          <span class="commentary-rank-badge">${song.rank}位</span>
          <h3 class="commentary-song-title">${escapeHtml(song.title)} <small>/ ${escapeHtml(song.producer)}</small></h3>
          <span class="commentary-song-pt">${Number(song.total_pt || 0).toLocaleString()} pt</span>
        </div>
        <div class="commentary-card-body">
          ${escapeHtml(song.commentary).replace(/\n/g, "<br>")}
        </div>
      </div>
    `
    )
    .join("");
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}