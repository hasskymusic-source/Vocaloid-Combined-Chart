window.__VOCALOID_APP_LOADED__ = true;

let insightChartInstance = null;
let currentChartData = null;
let archiveHistoryCache = [];

const WEIGHTS = {
  yt_views: 1,
  yt_likes: 50,
  yt_comments: 100,
  nc_views: 5,
  nc_mylist: 100,
  nc_mylists: 100,
  nc_comments: 10,
};

// 6指標の統一カラーパレット（カードのpt内訳バーおよびTOP 10グラフで共通使用）
const METRIC_COLORS = {
  yt_views: "#ef4444",    // 赤: YouTube再生
  yt_likes: "#f97316",    // 橙: YouTube高評価
  yt_comments: "#eab308", // 黄: YouTubeコメント
  nc_views: "#3b82f6",    // 青: ニコ動再生
  nc_mylists: "#06b6d4",  // 水色: ニコ動マイリスト
  nc_comments: "#8b5cf6", // 紫: ニコ動コメント
};

function startApp() {
  initTabs();
  initChartApp();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", startApp);
} else {
  startApp();
}

function getSongsArray(chartData) {
  if (!chartData) return [];
  if (Array.isArray(chartData)) return chartData;
  if (Array.isArray(chartData.ranking)) return chartData.ranking;
  if (Array.isArray(chartData.songs)) return chartData.songs;
  return [];
}

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

      // タブが display: block になった直後のフレームでグラフを再描画・リサイズする
      if (targetId === "tab-insight" && currentChartData) {
        requestAnimationFrame(() => {
          setTimeout(() => {
            renderTop10InsightChart(getSongsArray(currentChartData));
          }, 20);
        });
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
  if (!song || typeof song !== "object") return [];
  const keys = [];
  if (song.song_id) keys.push(`id:${song.song_id}`);
  if (song.id) keys.push(`id:${song.id}`);
  if (song.youtube_id) keys.push(`yt:${song.youtube_id}`);
  if (song.niconico_id) keys.push(`nc:${song.niconico_id}`);
  if (song.title && song.producer) keys.push(`tp:${song.title}__${song.producer}`);
  return keys;
}

async function initChartApp() {
  await loadAndRenderChart();

  try {
    await loadArchiveHistory();
    if (currentChartData) {
      enrichWithHistory(currentChartData);
      renderAllViews(currentChartData);
    }
  } catch (err) {
    console.warn("アーカイブ履歴の補完をスキップしました:", err);
  }
}

async function loadArchiveHistory() {
  const indexData = await fetchJsonWithFallback([
    "./data/archives/archive_index.json",
    "./data/archive_index.json",
    "public/data/archives/archive_index.json",
    "public/data/archive_index.json",
  ]);

  const selectEl = document.getElementById("archive-select");
  const archiveList = Array.isArray(indexData)
    ? indexData
    : indexData && Array.isArray(indexData.archives)
    ? indexData.archives
    : [];

  if (!archiveList.length) {
    return;
  }

  if (selectEl && selectEl.options.length <= 1) {
    archiveList.forEach((item) => {
      const fileVal =
        typeof item === "string"
          ? item
          : item.file || item.path || (item.archiveId ? `${item.archiveId}.json` : item.id);
      const labelText =
        typeof item === "string"
          ? item
          : item.label || item.period || item.publishDate || item.archiveId || item.id;
      if (!fileVal) return;
      const opt = document.createElement("option");
      opt.value = fileVal;
      opt.textContent = labelText;
      selectEl.appendChild(opt);
    });

    selectEl.addEventListener("change", async (e) => {
      const val = e.target.value;
      if (val === "latest") {
        await loadAndRenderChart();
      } else {
        const cleanFile = val.endsWith(".json") ? val : `${val}.json`;
        const archiveData = await fetchJsonWithFallback([
          `./data/archives/${cleanFile}`,
          `public/data/archives/${cleanFile}`,
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

  const loadedArchives = [];
  for (const item of archiveList) {
    const rawFile =
      typeof item === "string"
        ? item
        : item.file || item.path || (item.archiveId ? `${item.archiveId}.json` : item.id);
    if (!rawFile) continue;
    const cleanFile = rawFile.endsWith(".json") ? rawFile : `${rawFile}.json`;
    const data = await fetchJsonWithFallback([
      `./data/archives/${cleanFile}`,
      `public/data/archives/${cleanFile}`,
      rawFile,
    ]);
    if (data && getSongsArray(data).length > 0) {
      loadedArchives.push(data);
    }
  }
  archiveHistoryCache = loadedArchives;
}

function enrichWithHistory(chartData) {
  const songs = getSongsArray(chartData);
  if (!songs.length) return;

  const targetKey =
    chartData.archiveId || chartData.publishDate || chartData.period || chartData.updated_at || "";

  const olderCharts = archiveHistoryCache.filter((c) => {
    const p = c.archiveId || c.publishDate || c.period || c.updated_at || "";
    return p && targetKey ? p < targetKey : false;
  });

  const prevChart = olderCharts.length > 0 ? olderCharts[olderCharts.length - 1] : null;

  songs.forEach((song) => {
    const keys = getSongIdentityKeys(song);

    if (typeof song.chart_in_count !== "number" || song.chart_in_count < 1) {
      let count = 1;
      olderCharts.forEach((past) => {
        const matched = getSongsArray(past)
          .slice(0, 20)
          .some((ps) => {
            const pKeys = getSongIdentityKeys(ps);
            return keys.some((k) => pKeys.includes(k));
          });
        if (matched) count += 1;
      });
      song.chart_in_count = count;
    }

    if (song.prev_total_pt === undefined && prevChart) {
      const prevSong = getSongsArray(prevChart).find((ps) => {
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

async function loadAndRenderChart() {
  const data = await fetchJsonWithFallback([
    "./data/latest_ranking.json",
    "data/latest_ranking.json",
    "public/data/latest_ranking.json",
    "./data/weekly_draft.json",
    "data/weekly_draft.json",
    "../data/weekly_draft.json",
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
  const periodEl = document.getElementById("chart-period") || document.getElementById("chart-title");
  if (periodEl) {
    periodEl.textContent = data.period || data.publishDate || data.updated_at || "最新チャート";
  }

  const ranking = getSongsArray(data);
  renderRankingView(ranking);
  renderTop10InsightChart(ranking);
  renderInsightTable(ranking);
  renderCommentaryView(data, ranking);
}

function getPointsBreakdown(song) {
  const raw = song.raw || {};
  const pts = song.pts || {};

  const rawNcMylist = raw.nc_mylist !== undefined ? raw.nc_mylist : raw.nc_mylists || 0;
  const ptsNcMylist =
    pts.nc_mylist !== undefined
      ? pts.nc_mylist
      : pts.nc_mylists !== undefined
      ? pts.nc_mylists
      : rawNcMylist * WEIGHTS.nc_mylist;

  const yt_views = pts.yt_views !== undefined ? pts.yt_views : (raw.yt_views || 0) * WEIGHTS.yt_views;
  const yt_likes = pts.yt_likes !== undefined ? pts.yt_likes : (raw.yt_likes || 0) * WEIGHTS.yt_likes;
  const yt_comments =
    pts.yt_comments !== undefined ? pts.yt_comments : (raw.yt_comments || 0) * WEIGHTS.yt_comments;

  const nc_views = pts.nc_views !== undefined ? pts.nc_views : (raw.nc_views || 0) * WEIGHTS.nc_views;
  const nc_mylists = ptsNcMylist;
  const nc_comments =
    pts.nc_comments !== undefined ? pts.nc_comments : (raw.nc_comments || 0) * WEIGHTS.nc_comments;

  const yt_total = pts.yt_total !== undefined ? pts.yt_total : yt_views + yt_likes + yt_comments;
  const nc_total = pts.nc_total !== undefined ? pts.nc_total : nc_views + nc_mylists + nc_comments;
  const calcSum = yt_total + nc_total;
  const total_pt = song.total_pt !== undefined && song.total_pt > 0 ? song.total_pt : calcSum;

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
    calcSum: calcSum > 0 ? calcSum : 1,
    rawNcMylist,
  };
}

function formatRankDiffBadge(song) {
  const prev = song.prev_rank !== undefined ? song.prev_rank : song.prevRank;
  const curr = song.rank;
  if (!prev || prev === null) {
    return `<span class="rank-diff diff-new">NEW</span>`;
  }
  if (prev > curr) {
    return `<span class="rank-diff diff-up">▲${prev - curr}</span>`;
  }
  if (prev < curr) {
    return `<span class="rank-diff diff-down">▼${curr - prev}</span>`;
  }
  return `<span class="rank-diff diff-stay">→</span>`;
}

/**
 * ポイント前週比率のフォーマット
 * 上昇時: 緑色で「∧150%」、下降時: 赤色で「∨85%」、初登場時: 「NEW」
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

/**
 * 週間ランキング TOP 20 カード描画
 * - 楽曲名の隣に「詳細を見る ▾」ボタンを配置（カード全体クリックではなくボタンで開閉）
 * - 6指標それぞれのpt割合に応じた6色プログレスバー＆左右の YouTube計 / ニコ動計 ラベルを完全復元
 */
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
      const denom = bd.calcSum;

      // 6指標それぞれの割合（%）
      const pYtViews = ((bd.yt_views / denom) * 100).toFixed(2);
      const pYtLikes = ((bd.yt_likes / denom) * 100).toFixed(2);
      const pYtComments = ((bd.yt_comments / denom) * 100).toFixed(2);
      const pNcViews = ((bd.nc_views / denom) * 100).toFixed(2);
      const pNcMylists = ((bd.nc_mylists / denom) * 100).toFixed(2);
      const pNcComments = ((bd.nc_comments / denom) * 100).toFixed(2);

      // プラットフォーム合計割合（%）
      const ytPercent = bd.total_pt > 0 ? ((bd.yt_total / bd.total_pt) * 100).toFixed(1) : "0.0";
      const ncPercent = bd.total_pt > 0 ? ((bd.nc_total / bd.total_pt) * 100).toFixed(1) : "0.0";

      return `
      <article class="rank-card rank-${song.rank}" data-rank="${song.rank}">
        <div class="rank-card-main">
          <div class="rank-top-row">
            <div class="rank-number-col">
              <span class="rank-number">${song.rank}</span>
              ${formatRankDiffBadge(song)}
            </div>

            <div class="rank-info-col">
              <div class="song-title-row">
                <h3 class="song-title">${escapeHtml(song.title)}</h3>
                <button
                  type="button"
                  id="detail-btn-${song.rank}"
                  class="detail-toggle-btn"
                  onclick="toggleRankDetail(${song.rank}, event)"
                >詳細を見る ▾</button>
              </div>
              <div class="song-meta">
                <span class="song-producer">P: ${escapeHtml(song.producer)}</span>
                ${song.vocal ? `<span class="song-vocal">Vocal: ${escapeHtml(song.vocal)}</span>` : ""}
              </div>
            </div>

            <div class="rank-points-col">
              <div class="total-points">${Number(bd.total_pt).toLocaleString()} <small>pt</small></div>
            </div>
          </div>

          <!-- 6指標それぞれのpt割合を表示する6色バー -->
          <div class="metric-stacked-bar">
            <div class="bar-seg seg-yt-views" style="width: ${pYtViews}%" title="YouTube再生: ${Number(bd.yt_views).toLocaleString()} pt (${pYtViews}%)"></div>
            <div class="bar-seg seg-yt-likes" style="width: ${pYtLikes}%" title="YouTube高評価: ${Number(bd.yt_likes).toLocaleString()} pt (${pYtLikes}%)"></div>
            <div class="bar-seg seg-yt-comments" style="width: ${pYtComments}%" title="YouTubeコメント: ${Number(bd.yt_comments).toLocaleString()} pt (${pYtComments}%)"></div>
            <div class="bar-seg seg-nc-views" style="width: ${pNcViews}%" title="ニコ動再生: ${Number(bd.nc_views).toLocaleString()} pt (${pNcViews}%)"></div>
            <div class="bar-seg seg-nc-mylists" style="width: ${pNcMylists}%" title="ニコ動マイリス: ${Number(bd.nc_mylists).toLocaleString()} pt (${pNcMylists}%)"></div>
            <div class="bar-seg seg-nc-comments" style="width: ${pNcComments}%" title="ニコ動コメント: ${Number(bd.nc_comments).toLocaleString()} pt (${pNcComments}%)"></div>
          </div>

          <div class="share-labels">
            <span>YouTube計: ${ytPercent}% (${Number(bd.yt_total).toLocaleString()} pt)</span>
            <span>ニコ動計: ${ncPercent}% (${Number(bd.nc_total).toLocaleString()} pt)</span>
          </div>
        </div>

        <div id="detail-panel-${song.rank}" class="rank-detail-panel">
          <div class="detail-grid">
            <div class="detail-box yt-detail-box">
              <h4>YouTube 指標内訳 (${Number(bd.yt_total).toLocaleString()} pt / ${ytPercent}%)</h4>
              <ul>
                <li>
                  <span><i class="legend-dot seg-yt-views"></i>週間再生数:</span>
                  <strong>+${Number(raw.yt_views || 0).toLocaleString()}</strong> (${Number(bd.yt_views).toLocaleString()} pt)
                </li>
                <li>
                  <span><i class="legend-dot seg-yt-likes"></i>週間高評価数:</span>
                  <strong>+${Number(raw.yt_likes || 0).toLocaleString()}</strong> (${Number(bd.yt_likes).toLocaleString()} pt)
                </li>
                <li>
                  <span><i class="legend-dot seg-yt-comments"></i>週間コメント数:</span>
                  <strong>+${Number(raw.yt_comments || 0).toLocaleString()}</strong> (${Number(bd.yt_comments).toLocaleString()} pt)
                </li>
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
                <li>
                  <span><i class="legend-dot seg-nc-views"></i>週間再生数:</span>
                  <strong>+${Number(raw.nc_views || 0).toLocaleString()}</strong> (${Number(bd.nc_views).toLocaleString()} pt)
                </li>
                <li>
                  <span><i class="legend-dot seg-nc-mylists"></i>週間マイリスト数:</span>
                  <strong>+${Number(bd.rawNcMylist).toLocaleString()}</strong> (${Number(bd.nc_mylists).toLocaleString()} pt)
                </li>
                <li>
                  <span><i class="legend-dot seg-nc-comments"></i>週間コメント数:</span>
                  <strong>+${Number(raw.nc_comments || 0).toLocaleString()}</strong> (${Number(bd.nc_comments).toLocaleString()} pt)
                </li>
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

window.toggleRankDetail = function (rank, event) {
  if (event) {
    event.stopPropagation();
  }
  const panel = document.getElementById(`detail-panel-${rank}`);
  const btn = document.getElementById(`detail-btn-${rank}`);
  if (panel) {
    const isOpen = panel.classList.toggle("open");
    if (btn) {
      btn.textContent = isOpen ? "閉じる ▴" : "詳細を見る ▾";
      btn.classList.toggle("open", isOpen);
    }
  }
};

/**
 * ランキングインサイト：TOP 10 ポイント構成比（6指標内訳）グラフ描画
 * Chart.js での描画を行い、万一 Chart.js が未ロードまたは非表示サイズ0の場合は
 * 確実に表示される HTML/CSS 6色積み上げグラフへ自動フォールバックする
 */
function renderTop10InsightChart(ranking) {
  const wrapper = document.getElementById("insight-chart-wrapper") || document.querySelector(".chart-wrapper");
  if (!wrapper) return;

  const top10 = ranking.slice(0, 10);
  if (!top10.length) return;

  const labels = top10.map((s) => `${s.rank}位: ${s.title}`);
  const breakdowns = top10.map((s) => getPointsBreakdown(s));

  let canvas = document.getElementById("top5Chart") || document.getElementById("top20Chart");

  // Chart.js が利用可能な場合
  if (typeof Chart !== "undefined") {
    if (!canvas) {
      wrapper.innerHTML = `<canvas id="top5Chart"></canvas>`;
      canvas = document.getElementById("top5Chart");
    }

    if (insightChartInstance) {
      insightChartInstance.destroy();
      insightChartInstance = null;
    }

    try {
      const ctx = canvas.getContext("2d");
      insightChartInstance = new Chart(ctx, {
        type: "bar",
        data: {
          labels,
          datasets: [
            {
              label: "YouTube 再生",
              data: breakdowns.map((b) => b.yt_views),
              backgroundColor: METRIC_COLORS.yt_views,
            },
            {
              label: "YouTube 高評価",
              data: breakdowns.map((b) => b.yt_likes),
              backgroundColor: METRIC_COLORS.yt_likes,
            },
            {
              label: "YouTube コメント",
              data: breakdowns.map((b) => b.yt_comments),
              backgroundColor: METRIC_COLORS.yt_comments,
            },
            {
              label: "ニコ動 再生",
              data: breakdowns.map((b) => b.nc_views),
              backgroundColor: METRIC_COLORS.nc_views,
            },
            {
              label: "ニコ動 マイリス",
              data: breakdowns.map((b) => b.nc_mylists),
              backgroundColor: METRIC_COLORS.nc_mylists,
            },
            {
              label: "ニコ動 コメント",
              data: breakdowns.map((b) => b.nc_comments),
              backgroundColor: METRIC_COLORS.nc_comments,
            },
          ],
        },
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          animation: { duration: 350 },
          scales: {
            x: {
              stacked: true,
              ticks: {
                color: "#94a3b8",
                callback: function (value) {
                  return Number(value).toLocaleString() + " pt";
                },
              },
              grid: { color: "rgba(148, 163, 184, 0.12)" },
            },
            y: {
              stacked: true,
              ticks: { color: "#f8fafc", font: { size: 12, weight: "600" } },
              grid: { display: false },
            },
          },
          plugins: {
            legend: {
              position: "top",
              labels: { color: "#e2e8f0", boxWidth: 14, padding: 14 },
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
      insightChartInstance.resize();
      return;
    } catch (err) {
      console.warn("Chart.js 描画エラーのため HTML フォールバックを使用します:", err);
    }
  }

  // 万一 Chart.js が読み込めない環境向けの HTML/CSS 6指標積み上げグラフ
  const maxPt = Math.max(...breakdowns.map((b) => b.total_pt), 1);
  wrapper.innerHTML = `
    <div class="fallback-chart-legend">
      <span><i class="legend-dot seg-yt-views"></i>YouTube 再生</span>
      <span><i class="legend-dot seg-yt-likes"></i>YouTube 高評価</span>
      <span><i class="legend-dot seg-yt-comments"></i>YouTube コメント</span>
      <span><i class="legend-dot seg-nc-views"></i>ニコ動 再生</span>
      <span><i class="legend-dot seg-nc-mylists"></i>ニコ動 マイリス</span>
      <span><i class="legend-dot seg-nc-comments"></i>ニコ動 コメント</span>
    </div>
    <div class="fallback-chart-rows">
      ${top10
        .map((song, i) => {
          const b = breakdowns[i];
          const wTotal = ((b.total_pt / maxPt) * 100).toFixed(2);
          const denom = b.calcSum;
          return `
            <div class="fallback-chart-row">
              <div class="fallback-chart-label" title="${escapeHtml(song.title)}">${song.rank}位: ${escapeHtml(song.title)}</div>
              <div class="fallback-chart-bar-track">
                <div class="fallback-chart-bar-fill" style="width: ${wTotal}%">
                  <div class="bar-seg seg-yt-views" style="width: ${((b.yt_views / denom) * 100).toFixed(2)}%"></div>
                  <div class="bar-seg seg-yt-likes" style="width: ${((b.yt_likes / denom) * 100).toFixed(2)}%"></div>
                  <div class="bar-seg seg-yt-comments" style="width: ${((b.yt_comments / denom) * 100).toFixed(2)}%"></div>
                  <div class="bar-seg seg-nc-views" style="width: ${((b.nc_views / denom) * 100).toFixed(2)}%"></div>
                  <div class="bar-seg seg-nc-mylists" style="width: ${((b.nc_mylists / denom) * 100).toFixed(2)}%"></div>
                  <div class="bar-seg seg-nc-comments" style="width: ${((b.nc_comments / denom) * 100).toFixed(2)}%"></div>
                </div>
              </div>
              <div class="fallback-chart-pt">${Number(b.total_pt).toLocaleString()} pt</div>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

/**
 * ランキングインサイト：TOP 10 プラットフォーム別・指標構成比データ テーブルを描画
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
  const overallEl =
    document.getElementById("overall-commentary") ||
    document.getElementById("weekly-summary-text");
  if (overallEl) {
    const overallText =
      data.overall_commentary || data.weeklySummary || data.trend_analysis || "";
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