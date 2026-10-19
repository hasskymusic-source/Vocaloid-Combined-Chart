window.__VOCALOID_APP_LOADED__ = true;

let insightChartInstance = null;
let currentChartData = null;
let archiveHistoryCache = [];
let archiveHistoryLoaded = false;
let chartJsLoadingPromise = null;

const MOBILE_MEDIA_QUERY = "(max-width: 640px)";

const WEIGHTS = {
  yt_views: 1,
  yt_likes: 50,
  yt_comments: 100,
  nc_views: 5,
  nc_mylist: 100,
  nc_mylists: 100,
  nc_comments: 10,
};

const METRIC_COLORS = {
  yt_views: "#ef4444",    // 赤: YouTube再生
  yt_likes: "#f97316",    // 橙: YouTube高評価
  yt_comments: "#eab308", // 黄: YouTubeコメント
  nc_views: "#3b82f6",    // 青: ニコ動再生
  nc_mylists: "#06b6d4",  // 水色: ニコ動マイリスト
  nc_comments: "#8b5cf6", // 紫: ニコ動コメント
};

function isSmartphoneViewport() {
  return window.matchMedia && window.matchMedia(MOBILE_MEDIA_QUERY).matches;
}

function isDataSaverEnabled() {
  return Boolean(navigator.connection && navigator.connection.saveData);
}

/**
 * スマホ表示時の初期読み込み速度を落とさないための Chart.js 動的ローダー
 * ランキングインサイトタブを開いたとき、またはPCのアイドル時にのみ読み込む
 */
function ensureChartJsLoaded() {
  if (typeof Chart !== "undefined") {
    return Promise.resolve(true);
  }
  if (chartJsLoadingPromise) {
    return chartJsLoadingPromise;
  }
  chartJsLoadingPromise = new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js";
    script.async = true;
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
  return chartJsLoadingPromise;
}

function startApp() {
  initTabs();
  initScrollHints();
  initChartApp();

  // PC・タブレット表示時のみ、ブラウザのアイドル時間にChart.jsを事前準備
  if (!isSmartphoneViewport() && !isDataSaverEnabled()) {
    const idleFn = window.requestIdleCallback || ((cb) => setTimeout(cb, 1200));
    idleFn(() => ensureChartJsLoaded());
  }
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
    btn.addEventListener("click", async () => {
      const targetId = btn.getAttribute("data-tab");
      tabButtons.forEach((b) => b.classList.remove("active"));
      tabContents.forEach((c) => c.classList.remove("active"));

      btn.classList.add("active");
      const targetEl = document.getElementById(targetId);
      if (targetEl) {
        targetEl.classList.add("active");
      }

      // スマホでタップしたタブが画面端で見切れている場合、スムーズに中央へスクロール
      if (typeof btn.scrollIntoView === "function") {
        btn.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
      }

      if (targetId === "tab-insight" && currentChartData) {
        await ensureChartJsLoaded();
        requestAnimationFrame(() => {
          setTimeout(() => {
            renderTop10InsightChart(getSongsArray(currentChartData));
            refreshAllScrollHints();
          }, 20);
        });
      } else {
        requestAnimationFrame(() => refreshAllScrollHints());
      }
    });
  });
}

/**
 * 画面に収まっていない部分（横スクロール可能なタブ・表、および縦スクロール領域）に
 * 「スクロールして表示」ガイドを動的に表示・制御するシステム
 */
function initScrollHints() {
  // 1. タブナビゲーションの横スクロール監視
  const tabNav = document.getElementById("tab-nav");
  const tabHint = document.getElementById("tab-scroll-hint");
  const tabWrapper = document.getElementById("tab-nav-wrapper");

  const updateTabHint = () => {
    if (!tabNav || !tabHint || !tabWrapper) return;
    const maxScroll = tabNav.scrollWidth - tabNav.clientWidth;
    const canScrollRight = maxScroll > 8 && tabNav.scrollLeft < maxScroll - 12;
    tabHint.classList.toggle("visible", canScrollRight);
    tabWrapper.classList.toggle("has-overflow-right", canScrollRight);
  };

  if (tabNav) {
    tabNav.addEventListener("scroll", updateTabHint, { passive: true });
    if (tabHint) {
      tabHint.addEventListener("click", () => {
        tabNav.scrollBy({ left: 160, behavior: "smooth" });
      });
    }
  }

  // 2. テーブル（.table-responsive）の横スクロール監視と動的バッジ注入
  const setupTableScrollHints = () => {
    const containers = document.querySelectorAll(".table-responsive");
    containers.forEach((container) => {
      if (!container.dataset.hintInitialized) {
        container.dataset.hintInitialized = "true";
        const badge = document.createElement("div");
        badge.className = "table-scroll-indicator";
        badge.innerHTML = `<span>⇄ スクロールして表示</span>`;
        badge.addEventListener("click", () => {
          container.scrollBy({ left: 180, behavior: "smooth" });
        });
        container.parentElement.insertBefore(badge, container);

        const updateTableHint = () => {
          const maxScroll = container.scrollWidth - container.clientWidth;
          const isOverflowing = maxScroll > 8;
          const hasScrolled = container.scrollLeft > 24;
          badge.classList.toggle("visible", isOverflowing && !hasScrolled);
          container.classList.toggle("is-scrollable", isOverflowing && container.scrollLeft < maxScroll - 8);
        };

        container.addEventListener("scroll", updateTableHint, { passive: true });
        container._updateScrollHint = updateTableHint;
      }
      if (typeof container._updateScrollHint === "function") {
        container._updateScrollHint();
      }
    });
  };

  // 3. スマホ向け：画面下方向のスクロール誘導ピル制御
  const vHint = document.getElementById("vertical-scroll-hint");
  let userHasScrolledVertically = false;

  const updateVerticalHint = () => {
    if (!vHint) return;
    if (!isSmartphoneViewport()) {
      vHint.classList.remove("visible");
      return;
    }
    const scrollableHeight = document.documentElement.scrollHeight - window.innerHeight;
    if (window.scrollY > 80) {
      userHasScrolledVertically = true;
    }
    const shouldShow = !userHasScrolledVertically && scrollableHeight > 220 && window.scrollY <= 80;
    vHint.classList.toggle("visible", shouldShow);
  };

  if (vHint) {
    vHint.addEventListener("click", () => {
      window.scrollBy({ top: Math.round(window.innerHeight * 0.65), behavior: "smooth" });
    });
  }

  window.addEventListener("scroll", updateVerticalHint, { passive: true });
  window.addEventListener(
    "resize",
    () => {
      updateTabHint();
      setupTableScrollHints();
      updateVerticalHint();
    },
    { passive: true }
  );

  window._refreshScrollHintsInternal = () => {
    updateTabHint();
    setupTableScrollHints();
    updateVerticalHint();
  };

  setTimeout(window._refreshScrollHintsInternal, 80);
}

function refreshAllScrollHints() {
  if (typeof window._refreshScrollHintsInternal === "function") {
    window._refreshScrollHintsInternal();
  }
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

function normalizePeriodString(periodStr) {
  if (!periodStr || typeof periodStr !== "string") return "";
  const match = periodStr.match(
    /(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})\s*[\-~〜]\s*(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})/
  );
  if (!match) return periodStr;

  const y1 = parseInt(match[1], 10);
  const m1 = parseInt(match[2], 10);
  const d1 = parseInt(match[3], 10);
  const y2 = parseInt(match[4], 10);
  const m2 = parseInt(match[5], 10);
  const d2 = parseInt(match[6], 10);

  const startDt = new Date(Date.UTC(y1, m1 - 1, d1));
  const endDt = new Date(Date.UTC(y2, m2 - 1, d2));
  const diffDays = Math.round((endDt - startDt) / 86400000);

  if (diffDays === 7) {
    endDt.setUTCDate(endDt.getUTCDate() - 1);
  }

  const fmt = (dt) => {
    const yy = dt.getUTCFullYear();
    const mm = String(dt.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(dt.getUTCDate()).padStart(2, "0");
    return `${yy}/${mm}/${dd}`;
  };
  return `${fmt(startDt)} - ${fmt(endDt)}`;
}

function extractUpdateDateString(data) {
  const rawUpdate = data.updated_at || data.published_at || data.publishDate || "";
  if (rawUpdate && typeof rawUpdate === "string") {
    const m = rawUpdate.match(/(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})/);
    if (m) {
      return `${m[1]}/${String(m[2]).padStart(2, "0")}/${String(m[3]).padStart(2, "0")}`;
    }
  }
  return "";
}

async function initChartApp() {
  await loadAndRenderChart();

  try {
    await loadArchiveIndexOnly();
    // すでに全曲に chart_in_count が付与されている場合、スマホでは不要な過去アーカイブ全件通信を省略して高速化
    const songs = getSongsArray(currentChartData);
    const needsHistoryEnrich = songs.some(
      (s) => typeof s.chart_in_count !== "number" || s.chart_in_count < 1
    );

    if (needsHistoryEnrich || (!isSmartphoneViewport() && !isDataSaverEnabled())) {
      await ensureFullArchiveHistoryLoaded();
      if (currentChartData) {
        enrichWithHistory(currentChartData);
        renderAllViews(currentChartData);
      }
    }
  } catch (err) {
    console.warn("アーカイブ履歴の補完をスキップしました:", err);
  }
}

let cachedArchiveListMeta = [];

async function loadArchiveIndexOnly() {
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

  cachedArchiveListMeta = archiveList;
  if (!archiveList.length) {
    return;
  }

  if (selectEl && selectEl.options.length <= 1) {
    archiveList.forEach((item) => {
      const fileVal =
        typeof item === "string"
          ? item
          : item.file || item.path || (item.archiveId ? `${item.archiveId}.json` : item.id);
      let labelText =
        typeof item === "string"
          ? item
          : item.label || item.period || item.publishDate || item.archiveId || item.id;
      if (labelText && typeof labelText === "string") {
        labelText = labelText.replace(
          /(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}\s*[\-~〜]\s*\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2})/,
          (m) => normalizePeriodString(m)
        );
      }
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
          await ensureFullArchiveHistoryLoaded();
          enrichWithHistory(archiveData);
          currentChartData = archiveData;
          renderAllViews(archiveData);
        }
      }
    });
  }
}

async function ensureFullArchiveHistoryLoaded() {
  if (archiveHistoryLoaded || !cachedArchiveListMeta.length) return;
  archiveHistoryLoaded = true;

  const loadedArchives = [];
  for (const item of cachedArchiveListMeta) {
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
  if (!songs.length || !archiveHistoryCache.length) return;

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
    const cleanPeriod = normalizePeriodString(data.period || "");
    const updateDate = extractUpdateDateString(data);
    if (cleanPeriod && updateDate) {
      periodEl.textContent = `${cleanPeriod} / 更新: ${updateDate}`;
    } else if (cleanPeriod) {
      periodEl.textContent = cleanPeriod;
    } else if (updateDate) {
      periodEl.textContent = `更新: ${updateDate}`;
    } else {
      periodEl.textContent = "最新チャート";
    }
  }

  const ranking = getSongsArray(data);
  renderRankingView(ranking);
  renderInsightTable(ranking);
  renderCommentaryView(data, ranking);

  // インサイトタブが開いている場合のみ即座にグラフを描画
  const insightSection = document.getElementById("tab-insight");
  if (insightSection && insightSection.classList.contains("active")) {
    ensureChartJsLoaded().then(() => renderTop10InsightChart(ranking));
  }

  requestAnimationFrame(() => refreshAllScrollHints());
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
    return `<span class="rank-diff diff-up">▲${prev - curr} (前週${prev}位)</span>`;
  }
  if (prev < curr) {
    return `<span class="rank-diff diff-down">▼${curr - prev} (前週${prev}位)</span>`;
  }
  return `<span class="rank-diff diff-stay">→ KEEP (前週${prev}位)</span>`;
}

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
 * スマホの通信量を抑えるためのサムネイルURL選択＆遅延読み込み属性生成
 */
function getOptimizedThumbnailAttrs(song, index) {
  let thumbUrl =
    song.thumbnail ||
    (song.youtube_id ? `https://i.ytimg.com/vi/${song.youtube_id}/mqdefault.jpg` : "");

  if (!thumbUrl) return null;

  // ファーストビューに入る上位3曲は優先取得、4位以降は遅延読み込みで初期表示を高速化
  const isAboveFold = index < 3;
  const loadingAttr = isAboveFold ? "eager" : "lazy";
  const priorityAttr = isAboveFold ? `fetchpriority="high"` : `fetchpriority="low"`;

  return {
    url: thumbUrl,
    loadingAttr,
    priorityAttr,
  };
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
    .map((song, idx) => {
      const bd = getPointsBreakdown(song);
      const raw = song.raw || {};
      const denom = bd.calcSum;

      const pYtViews = ((bd.yt_views / denom) * 100).toFixed(2);
      const pYtLikes = ((bd.yt_likes / denom) * 100).toFixed(2);
      const pYtComments = ((bd.yt_comments / denom) * 100).toFixed(2);
      const pNcViews = ((bd.nc_views / denom) * 100).toFixed(2);
      const pNcMylists = ((bd.nc_mylists / denom) * 100).toFixed(2);
      const pNcComments = ((bd.nc_comments / denom) * 100).toFixed(2);

      const ytPercent = bd.total_pt > 0 ? ((bd.yt_total / bd.total_pt) * 100).toFixed(1) : "0.0";
      const ncPercent = bd.total_pt > 0 ? ((bd.nc_total / bd.total_pt) * 100).toFixed(1) : "0.0";
      const chartInCount = song.chart_in_count || 1;
      const thumbInfo = getOptimizedThumbnailAttrs(song, idx);

      return `
      <article class="rank-card rank-${song.rank}" data-rank="${song.rank}">
        <div class="rank-card-summary">
          <div class="rank-number-col">
            <span class="rank-number">${song.rank}<small>位</small></span>
            ${formatRankDiffBadge(song)}
            <span class="chart-in-mini">${chartInCount}週目</span>
          </div>

          ${
            thumbInfo
              ? `<div class="rank-thumb-col">
                   <img
                     src="${escapeHtml(thumbInfo.url)}"
                     alt="${escapeHtml(song.title)}"
                     class="rank-thumb"
                     width="112"
                     height="63"
                     loading="${thumbInfo.loadingAttr}"
                     decoding="async"
                     ${thumbInfo.priorityAttr}
                   />
                 </div>`
              : ""
          }

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
              <span class="song-producer">${escapeHtml(song.producer)}</span>
              ${song.vocal ? `<span class="song-vocal">feat. ${escapeHtml(song.vocal)}</span>` : ""}
            </div>
            <div class="metric-stacked-bar">
              <div class="bar-seg seg-yt-views" style="width: ${pYtViews}%" title="YouTube再生: ${Number(bd.yt_views).toLocaleString()} pt (${pYtViews}%)"></div>
              <div class="bar-seg seg-yt-likes" style="width: ${pYtLikes}%" title="YouTube高評価: ${Number(bd.yt_likes).toLocaleString()} pt (${pYtLikes}%)"></div>
              <div class="bar-seg seg-yt-comments" style="width: ${pYtComments}%" title="YouTubeコメント: ${Number(bd.yt_comments).toLocaleString()} pt (${pYtComments}%)"></div>
              <div class="bar-seg seg-nc-views" style="width: ${pNcViews}%" title="ニコ動再生: ${Number(bd.nc_views).toLocaleString()} pt (${pNcViews}%)"></div>
              <div class="bar-seg seg-nc-mylists" style="width: ${pNcMylists}%" title="ニコ動マイリス: ${Number(bd.nc_mylists).toLocaleString()} pt (${pNcMylists}%)"></div>
              <div class="bar-seg seg-nc-comments" style="width: ${pNcComments}%" title="ニコ動コメント: ${Number(bd.nc_comments).toLocaleString()} pt (${pNcComments}%)"></div>
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
    // スマホで詳細パネルを開いた際、パネル下部が画面外にはみ出していればスムーズに少しスクロールして見せる
    if (isOpen && isSmartphoneViewport()) {
      setTimeout(() => {
        const rect = panel.getBoundingClientRect();
        if (rect.bottom > window.innerHeight) {
          panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }, 60);
    }
  }
};

function renderTop10InsightChart(ranking) {
  const wrapper = document.getElementById("insight-chart-wrapper") || document.querySelector(".chart-wrapper");
  if (!wrapper) return;

  const top10 = ranking.slice(0, 10);
  if (!top10.length) return;

  const isMobile = isSmartphoneViewport();
  const labels = top10.map((s) => {
    const titleStr = String(s.title || "");
    const shortTitle = isMobile && titleStr.length > 10 ? titleStr.slice(0, 10) + "…" : titleStr;
    return `${s.rank}位: ${shortTitle}`;
  });
  const breakdowns = top10.map((s) => getPointsBreakdown(s));

  let canvas = document.getElementById("top5Chart") || document.getElementById("top20Chart");

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
          animation: { duration: isMobile ? 200 : 350 },
          scales: {
            x: {
              stacked: true,
              ticks: {
                color: "#94a3b8",
                font: { size: isMobile ? 10 : 12 },
                callback: function (value) {
                  if (isMobile && value >= 10000) {
                    return Math.round(value / 10000) + "万";
                  }
                  return Number(value).toLocaleString() + " pt";
                },
              },
              grid: { color: "rgba(148, 163, 184, 0.12)" },
            },
            y: {
              stacked: true,
              ticks: { color: "#f8fafc", font: { size: isMobile ? 11 : 12, weight: "600" } },
              grid: { display: false },
            },
          },
          plugins: {
            legend: {
              position: "top",
              labels: {
                color: "#e2e8f0",
                boxWidth: isMobile ? 10 : 14,
                padding: isMobile ? 8 : 14,
                font: { size: isMobile ? 11 : 12 },
              },
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