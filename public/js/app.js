window.__VOCALOID_APP_LOADED__ = true;

/**
 * 運営者用設定：
 * シェア時に使用する公式公開URL（.pages.dev が外部に出ないよう固定）
 */
const OFFICIAL_SITE_URL = "https://weekly-vocaloid-combined-chart.com";

/**
 * 任意の感謝メッセージ（「1,000,000 view ありがとうございます！」など）を常時表示したい場合は
 * 下記の SITE_ANNOUNCEMENT_MESSAGE にテキストを入力してください。
 */
const SITE_ANNOUNCEMENT_MESSAGE = "";
const COUNTER_NAMESPACE = "vocaloid-combined-chart";
const COUNTER_KEY = "total-site-views";
const MILESTONE_THRESHOLDS = [1000000, 500000, 100000, 50000, 10000, 5000, 1000];

let insightChartInstance = null;
let currentChartData = null;
let archiveHistoryCache = [];
let archiveHistoryLoaded = false;
let chartJsLoadingPromise = null;
const inflightJsonRequests = new Map();

// ランキング用 フィルタ・ソート・お気に入り状態
let currentSearchQuery = "";
let currentSortMode = "rank";
let showFavoritesOnly = false;
let favoriteSongKeys = new Set();

// 記事・コラム用 状態管理
let allArticlesData = [];
let currentArticleCategory = "all";
let currentArticleSearchQuery = "";
let currentOpenArticleId = null;

const FAVORITES_STORAGE_KEY = "vcc_favorite_songs_v1";
const LAST_KNOWN_CHART_STORAGE_KEY = "vcc_latest_chart_cache_v1";
const ARCHIVE_HISTORY_SESSION_KEY = "vcc_archive_history_session_v1";
const MOBILE_MEDIA_QUERY = "(max-width: 640px)";

const WEIGHTS = {
  yt_views: 1,
  yt_likes: 50,
  yt_comments: 100,
  nc_views: 5,
  nc_mylist: 100,
  nc_mylists: 100,
  nc_comments: 10
};

const METRIC_COLORS = {
  yt_views: "#ef4444",    // 赤: YouTube再生
  yt_likes: "#f97316",    // 橙: YouTube高評価
  yt_comments: "#eab308", // 黄: YouTubeコメント
  nc_views: "#3b82f6",    // 青: ニコ動再生
  nc_mylists: "#06b6d4",  // 水色: ニコ動マイリスト
  nc_comments: "#8b5cf6"  // 紫: ニコ動コメント
};

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function isSmartphoneViewport() {
  return Boolean(window.matchMedia && window.matchMedia(MOBILE_MEDIA_QUERY).matches);
}

function isDataSaverEnabled() {
  return Boolean(navigator.connection && navigator.connection.saveData);
}

function isLocalOwnerPreview() {
  const host = window.location.hostname;
  return host === "localhost" || host === "127.0.0.1";
}

function isChartReleasedForPublic(chartData) {
  if (isLocalOwnerPreview()) return true;
  if (!chartData || typeof chartData !== "object") return true;

  let releaseMs = null;
  if (chartData.publishAt && typeof chartData.publishAt === "string") {
    const parsed = Date.parse(chartData.publishAt);
    if (!isNaN(parsed)) {
      releaseMs = parsed;
    }
  }

  if (releaseMs === null) {
    const dateStr = chartData.publishDate || chartData.archiveId || "";
    const m = String(dateStr).trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (m) {
      releaseMs = Date.parse(m[1] + "-" + m[2] + "-" + m[3] + "T13:00:00+09:00");
    }
  }

  if (releaseMs === null || isNaN(releaseMs)) return true;
  return Date.now() >= releaseMs;
}

function isArticleReleasedForPublic(article) {
  if (!article || typeof article !== "object") return false;
  if (isLocalOwnerPreview()) {
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get("preview") === "1") return true;
  }
  const status = String(article.status || "published").toLowerCase();
  if (status === "draft") return false;

  if (article.publishAt && typeof article.publishAt === "string") {
    const parsed = Date.parse(article.publishAt);
    if (!isNaN(parsed) && Date.now() < parsed) {
      return false;
    }
  }
  return true;
}

function ensureChartJsLoaded() {
  if (typeof Chart !== "undefined") {
    return Promise.resolve(true);
  }
  if (chartJsLoadingPromise) {
    return chartJsLoadingPromise;
  }
  chartJsLoadingPromise = new Promise(function (resolve) {
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js";
    script.crossOrigin = "anonymous";
    script.referrerPolicy = "no-referrer";
    script.async = true;
    script.onload = function () {
      resolve(true);
    };
    script.onerror = function () {
      chartJsLoadingPromise = null;
      resolve(false);
    };
    document.head.appendChild(script);
  });
  return chartJsLoadingPromise;
}

function sanitizeYoutubeId(rawId) {
  if (!rawId || typeof rawId !== "string") return "";
  const trimmed = rawId.trim();
  return /^[A-Za-z0-9_-]{6,20}$/.test(trimmed) ? trimmed : "";
}

function sanitizeNiconicoId(rawId) {
  if (!rawId || typeof rawId !== "string") return "";
  const trimmed = rawId.trim();
  return /^(sm|nm|so)?[0-9]{1,16}$/i.test(trimmed) ? trimmed : "";
}

function sanitizeThumbnailUrl(rawUrl, fallbackYtId) {
  if (rawUrl && typeof rawUrl === "string") {
    try {
      const parsed = new URL(rawUrl, window.location.origin);
      const allowedHosts = [
        "i.ytimg.com",
        "img.youtube.com",
        "img.cdn.nimg.jp",
        "nicovideo.cdn.nimg.jp",
        window.location.hostname
      ];
      if (parsed.protocol === "https:" && allowedHosts.indexOf(parsed.hostname) !== -1) {
        return parsed.href;
      }
      if (parsed.origin === window.location.origin) {
        return parsed.href;
      }
    } catch (_) {
      // ignore invalid URL
    }
  }
  const safeYt = sanitizeYoutubeId(fallbackYtId);
  return safeYt ? "https://i.ytimg.com/vi/" + safeYt + "/mqdefault.jpg" : "";
}

function sanitizeSafeImageUrl(rawUrl) {
  if (!rawUrl || typeof rawUrl !== "string") return "";
  const trimmed = rawUrl.trim();
  if (trimmed.indexOf("data:image/") === 0) return trimmed;
  if (trimmed.indexOf("./") === 0 || trimmed.indexOf("/") === 0) return trimmed;
  try {
    const parsed = new URL(trimmed, window.location.origin);
    if (parsed.protocol === "https:" || parsed.origin === window.location.origin) {
      return parsed.href;
    }
  } catch (_) {
    // ignore invalid URL
  }
  return "";
}

function sanitizeArchiveFilename(rawVal) {
  if (!rawVal || typeof rawVal !== "string") return "";
  const base = rawVal.trim().replace(/^.*[/\\]/, "");
  const withExt = base.endsWith(".json") ? base : base + ".json";
  return /^[A-Za-z0-9_.-]+\.json$/.test(withExt) && withExt.indexOf("..") === -1 ? withExt : "";
}

function sleepWithJitter(attempt) {
  const baseDelay = 220 * Math.pow(1.8, attempt);
  const jitter = Math.floor(Math.random() * 280);
  return new Promise(function (resolve) {
    setTimeout(resolve, baseDelay + jitter);
  });
}

async function fetchJsonSingleUrl(url, cacheMode, timeoutMs, maxRetries) {
  const mode = cacheMode || "no-cache";
  const timeout = timeoutMs || 6500;
  const retries = maxRetries !== undefined ? maxRetries : 2;
  const requestKey = mode + "::" + url;

  if (inflightJsonRequests.has(requestKey)) {
    return inflightJsonRequests.get(requestKey);
  }

  const task = (async function () {
    for (let attempt = 0; attempt <= retries; attempt++) {
      const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
      const timerId = controller
        ? setTimeout(function () {
            controller.abort();
          }, timeout)
        : null;

      try {
        const res = await fetch(url, {
          cache: mode,
          credentials: "same-origin",
          signal: controller ? controller.signal : undefined
        });
        if (timerId) clearTimeout(timerId);

        if (res.ok) {
          return await res.json();
        }
        if (res.status >= 400 && res.status < 500 && res.status !== 429) {
          return null;
        }
      } catch (_) {
        if (timerId) clearTimeout(timerId);
      }

      if (attempt < retries) {
        await sleepWithJitter(attempt);
      }
    }
    return null;
  })();

  inflightJsonRequests.set(requestKey, task);
  try {
    return await task;
  } finally {
    inflightJsonRequests.delete(requestKey);
  }
}

async function fetchJsonWithFallback(urls, cacheMode) {
  for (let i = 0; i < urls.length; i++) {
    const data = await fetchJsonSingleUrl(urls[i], cacheMode || "no-cache");
    if (data) {
      return data;
    }
  }
  return null;
}

function startApp() {
  loadFavoritesFromStorage();
  initTabs();
  initUtilityToolbar();
  initRankingEventDelegation();
  initScrollHints();
  initBackToTopButton();
  initSiteViewCounter();
  initChartApp();
  initArticlesSystem();

  if (!isSmartphoneViewport() && !isDataSaverEnabled()) {
    const idleFn =
      window.requestIdleCallback ||
      function (cb) {
        setTimeout(cb, 1500);
      };
    idleFn(function () {
      ensureChartJsLoaded();
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", startApp);
} else {
  startApp();
}

/**
 * 1. サイト累計アクセスカウンター ＆ 記念マイルストーン感謝バナーシステム
 */
async function initSiteViewCounter() {
  const countEl = document.getElementById("view-count-value");
  const bannerEl = document.getElementById("milestone-banner");
  const bannerTextEl = document.getElementById("milestone-text");
  const closeBtn = document.getElementById("milestone-close-btn");

  if (closeBtn && bannerEl) {
    closeBtn.addEventListener("click", function () {
      bannerEl.style.display = "none";
    });
  }

  if (SITE_ANNOUNCEMENT_MESSAGE && bannerEl && bannerTextEl) {
    bannerTextEl.textContent = SITE_ANNOUNCEMENT_MESSAGE;
    bannerEl.style.display = "block";
  }

  try {
    const sessionKey = "vcc_session_counted";
    const alreadyCounted = sessionStorage.getItem(sessionKey) === "1" || isLocalOwnerPreview();
    const baseApi = "https://api.counterapi.dev/v1/" + COUNTER_NAMESPACE + "/" + COUNTER_KEY;
    const endpoint = alreadyCounted ? baseApi + "/" : baseApi + "/up";

    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timerId = controller
      ? setTimeout(function () {
          controller.abort();
        }, 3500)
      : null;

    const res = await fetch(endpoint, {
      cache: "no-store",
      signal: controller ? controller.signal : undefined
    });
    if (timerId) clearTimeout(timerId);

    if (res.ok) {
      const data = await res.json();
      const views = typeof data.count === "number" ? data.count : parseInt(data.count, 10);
      if (!isNaN(views) && views > 0) {
        sessionStorage.setItem(sessionKey, "1");
        localStorage.setItem("vcc_last_known_views", String(views));
        if (countEl) {
          countEl.textContent = Number(views).toLocaleString();
        }
        checkAndShowMilestoneBanner(views);
        return;
      }
    }
  } catch (_) {
    // 外部カウンターAPIがオフライン等の場合はローカルキャッシュへフォールバック
  }

  const fallbackViews = parseInt(localStorage.getItem("vcc_last_known_views") || "1", 10);
  if (countEl) {
    countEl.textContent = Number(fallbackViews).toLocaleString();
  }
}

function checkAndShowMilestoneBanner(views) {
  if (SITE_ANNOUNCEMENT_MESSAGE) return;
  const bannerEl = document.getElementById("milestone-banner");
  const bannerTextEl = document.getElementById("milestone-text");
  if (!bannerEl || !bannerTextEl) return;

  if (currentChartData && currentChartData.milestone_message) {
    bannerTextEl.textContent = currentChartData.milestone_message;
    bannerEl.style.display = "block";
    return;
  }

  for (let i = 0; i < MILESTONE_THRESHOLDS.length; i++) {
    const threshold = MILESTONE_THRESHOLDS[i];
    if (views >= threshold && views < threshold * 1.15) {
      bannerTextEl.textContent =
        "🎉 累計 " +
        Number(threshold).toLocaleString() +
        " Views 突破ありがとうございます！これからも週刊VOCALOID™複合ランキングをよろしくお願いいたします。";
      bannerEl.style.display = "block";
      break;
    }
  }
}

/**
 * 2. お気に入り（ローカルブックマーク）管理システム
 */
function loadFavoritesFromStorage() {
  try {
    const raw = localStorage.getItem(FAVORITES_STORAGE_KEY);
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) {
        favoriteSongKeys = new Set(arr);
      }
    }
  } catch (_) {
    favoriteSongKeys = new Set();
  }
  updateFavCountBadge();
}

function saveFavoritesToStorage() {
  try {
    localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(Array.from(favoriteSongKeys)));
  } catch (_) {
    // ignore storage quota errors
  }
  updateFavCountBadge();
}

function getPrimarySongKey(song) {
  if (!song || typeof song !== "object") return "";
  return String(
    song.song_id ||
      song.id ||
      song.youtube_id ||
      song.niconico_id ||
      (song.title || "") + "__" + (song.producer || "")
  );
}

function isSongFavorited(song) {
  const key = getPrimarySongKey(song);
  return key ? favoriteSongKeys.has(key) : false;
}

function toggleFavoriteSong(songKey) {
  if (!songKey) return;
  if (favoriteSongKeys.has(songKey)) {
    favoriteSongKeys.delete(songKey);
    showToast("お気に入りから解除しました");
  } else {
    favoriteSongKeys.add(songKey);
    showToast("★ お気に入りに保存しました");
  }
  saveFavoritesToStorage();
  if (currentChartData) {
    renderRankingView(getSongsArray(currentChartData));
  }
}

function updateFavCountBadge() {
  const countSpan = document.getElementById("fav-count-num");
  const favBtn = document.getElementById("fav-filter-btn");
  if (countSpan) {
    countSpan.textContent = String(favoriteSongKeys.size);
  }
  if (favBtn) {
    favBtn.classList.toggle("active", showFavoritesOnly);
    favBtn.setAttribute("aria-pressed", showFavoritesOnly ? "true" : "false");
  }
}

/**
 * 3. 検索・ソート・YouTube連続再生・SNSシェアの便利ツールバー初期化
 */
function initUtilityToolbar() {
  const searchInput = document.getElementById("ranking-search-input");
  const sortSelect = document.getElementById("ranking-sort-select");
  const favFilterBtn = document.getElementById("fav-filter-btn");
  const ytPlaylistBtn = document.getElementById("yt-playlist-btn");
  const shareXBtn = document.getElementById("share-x-btn");
  const copySummaryBtn = document.getElementById("copy-summary-btn");

  if (searchInput) {
    searchInput.addEventListener("input", function (e) {
      currentSearchQuery = (e.target.value || "").trim().toLowerCase();
      if (currentChartData) {
        renderRankingView(getSongsArray(currentChartData));
      }
    });
  }

  if (sortSelect) {
    sortSelect.addEventListener("change", function (e) {
      currentSortMode = e.target.value || "rank";
      if (currentChartData) {
        renderRankingView(getSongsArray(currentChartData));
      }
    });
  }

  if (favFilterBtn) {
    favFilterBtn.addEventListener("click", function () {
      showFavoritesOnly = !showFavoritesOnly;
      updateFavCountBadge();
      if (currentChartData) {
        renderRankingView(getSongsArray(currentChartData));
      }
    });
  }

  if (ytPlaylistBtn) {
    ytPlaylistBtn.addEventListener("click", function () {
      const songs = getSongsArray(currentChartData);
      const ytIds = songs
        .slice(0, 20)
        .map(function (s) {
          return sanitizeYoutubeId(s.youtube_id);
        })
        .filter(Boolean);

      if (!ytIds.length) {
        showToast("再生可能なYouTube動画が見つかりません");
        return;
      }
      const playlistUrl = "https://www.youtube.com/watch_videos?video_ids=" + ytIds.join(",");
      window.open(playlistUrl, "_blank", "noopener,noreferrer");
    });
  }

  if (shareXBtn) {
    shareXBtn.addEventListener("click", function () {
      const text = buildChartSummaryText();
      const shareUrl =
        "https://twitter.com/intent/tweet?text=" +
        encodeURIComponent(text) +
        "&url=" +
        encodeURIComponent(OFFICIAL_SITE_URL);
      window.open(shareUrl, "_blank", "noopener,noreferrer");
    });
  }

  if (copySummaryBtn) {
    copySummaryBtn.addEventListener("click", async function () {
      const text = buildChartSummaryText() + "\n" + OFFICIAL_SITE_URL;
      try {
        await navigator.clipboard.writeText(text);
        showToast("📋 今週のランキング結果をコピーしました！");
      } catch (_) {
        showToast("コピーに失敗しました");
      }
    });
  }
}

function buildChartSummaryText() {
  if (!currentChartData) {
    return "週刊VOCALOID™複合ランキング TOP 20 #週刊VOCALOID複合ランキング #vocanew #ボカロ";
  }
  const period = normalizePeriodString(currentChartData.period || "");
  const top3 = getSongsArray(currentChartData).slice(0, 3);
  const lines = top3.map(function (s, i) {
    return (
      i +
      1 +
      "位: " +
      s.title +
      " / " +
      s.producer +
      " (" +
      Number(s.total_pt || 0).toLocaleString() +
      " pt)"
    );
  });
  return (
    "【週刊VOCALOID™複合ランキング】\n集計期間: " +
    period +
    "\n\n" +
    lines.join("\n") +
    "\n\n#週刊VOCALOID複合ランキング #ボカロ"
  );
}

function showToast(message) {
  const toastEl = document.getElementById("toast-notification");
  if (!toastEl) return;
  toastEl.textContent = message;
  toastEl.classList.add("visible");
  clearTimeout(toastEl._hideTimer);
  toastEl._hideTimer = setTimeout(function () {
    toastEl.classList.remove("visible");
  }, 2600);
}

/**
 * 4. ページ最上部へ戻るフローティングボタン制御
 */
function initBackToTopButton() {
  const btn = document.getElementById("back-to-top-btn");
  if (!btn) return;

  window.addEventListener(
    "scroll",
    function () {
      btn.classList.toggle("visible", window.scrollY > 360);
    },
    { passive: true }
  );

  btn.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

function getSongsArray(chartData) {
  if (!chartData) return [];
  if (Array.isArray(chartData)) return chartData;
  if (Array.isArray(chartData.ranking)) return chartData.ranking;
  if (Array.isArray(chartData.songs)) return chartData.songs;
  return [];
}

function initRankingEventDelegation() {
  const container = document.getElementById("ranking-container");
  if (!container) return;

  container.addEventListener("click", function (e) {
    const detailBtn = e.target.closest(".detail-toggle-btn");
    if (detailBtn) {
      e.stopPropagation();
      const rank = parseInt(detailBtn.getAttribute("data-rank"), 10);
      if (!isNaN(rank)) {
        window.toggleRankDetail(rank);
      }
      return;
    }

    const favBtn = e.target.closest(".fav-star-btn");
    if (favBtn) {
      e.stopPropagation();
      const songKey = favBtn.getAttribute("data-song-key");
      toggleFavoriteSong(songKey);
      return;
    }

    const shareSongBtn = e.target.closest(".share-song-x-btn");
    if (shareSongBtn) {
      e.stopPropagation();
      const rank = shareSongBtn.getAttribute("data-rank");
      const title = shareSongBtn.getAttribute("data-title");
      const producer = shareSongBtn.getAttribute("data-producer");
      const pt = shareSongBtn.getAttribute("data-pt");
      const text =
        "『" +
        title +
        "』(" +
        producer +
        ") が「週刊VOCALOID™複合ランキング」で今週 " +
        rank +
        "位 (" +
        pt +
        " pt) にランクイン！\n#週刊VOCALOID複合ランキング #ボカロ";
      const shareUrl =
        "https://twitter.com/intent/tweet?text=" +
        encodeURIComponent(text) +
        "&url=" +
        encodeURIComponent(OFFICIAL_SITE_URL);
      window.open(shareUrl, "_blank", "noopener,noreferrer");
    }
  });
}

function activateTabById(targetId) {
  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabContents = document.querySelectorAll(".tab-content");

  tabButtons.forEach(function (b) {
    const isMatch = b.getAttribute("data-tab") === targetId;
    b.classList.toggle("active", isMatch);
    if (isMatch && typeof b.scrollIntoView === "function") {
      b.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    }
  });

  tabContents.forEach(function (c) {
    c.classList.toggle("active", c.id === targetId);
  });

  if (targetId === "tab-insight" && currentChartData) {
    ensureChartJsLoaded().then(function () {
      requestAnimationFrame(function () {
        setTimeout(function () {
          renderTop10InsightChart(getSongsArray(currentChartData));
          refreshAllScrollHints();
        }, 20);
      });
    });
  } else {
    requestAnimationFrame(function () {
      refreshAllScrollHints();
    });
  }
}

function initTabs() {
  const tabButtons = document.querySelectorAll(".tab-btn");
  tabButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const targetId = btn.getAttribute("data-tab");
      if (!targetId) return;
      activateTabById(targetId);

      const articlesTabId = getArticlesTabId();
      if (targetId !== articlesTabId && window.location.hash.indexOf("#article=") === 0) {
        history.replaceState(null, "", window.location.pathname + window.location.search);
      }
    });
  });
}

function initScrollHints() {
  const tabNav = document.getElementById("tab-nav");
  const tabHint = document.getElementById("tab-scroll-hint");
  const tabWrapper = document.getElementById("tab-nav-wrapper");

  const updateTabHint = function () {
    if (!tabNav || !tabHint || !tabWrapper) return;
    const maxScroll = tabNav.scrollWidth - tabNav.clientWidth;
    const canScrollRight = maxScroll > 8 && tabNav.scrollLeft < maxScroll - 12;
    tabHint.classList.toggle("visible", canScrollRight);
    tabWrapper.classList.toggle("has-overflow-right", canScrollRight);
  };

  if (tabNav) {
    tabNav.addEventListener("scroll", updateTabHint, { passive: true });
    if (tabHint) {
      tabHint.addEventListener("click", function () {
        tabNav.scrollBy({ left: 160, behavior: "smooth" });
      });
    }
  }

  const setupTableScrollHints = function () {
    const containers = document.querySelectorAll(".table-responsive");
    containers.forEach(function (container) {
      if (!container.dataset.hintInitialized) {
        container.dataset.hintInitialized = "true";
        const badge = document.createElement("div");
        badge.className = "table-scroll-indicator";
        badge.innerHTML = "<span>⇄ スクロールして表示</span>";
        badge.addEventListener("click", function () {
          container.scrollBy({ left: 180, behavior: "smooth" });
        });
        container.parentElement.insertBefore(badge, container);

        const updateTableHint = function () {
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

  const vHint = document.getElementById("vertical-scroll-hint");
  let userHasScrolledVertically = false;

  const updateVerticalHint = function () {
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
    vHint.addEventListener("click", function () {
      window.scrollBy({ top: Math.round(window.innerHeight * 0.65), behavior: "smooth" });
    });
  }

  window.addEventListener("scroll", updateVerticalHint, { passive: true });
  window.addEventListener(
    "resize",
    function () {
      updateTabHint();
      setupTableScrollHints();
      updateVerticalHint();
    },
    { passive: true }
  );

  window._refreshScrollHintsInternal = function () {
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

function getSongIdentityKeys(song) {
  if (!song || typeof song !== "object") return [];
  const keys = [];
  if (song.song_id) keys.push("id:" + song.song_id);
  if (song.id) keys.push("id:" + song.id);
  if (song.youtube_id) keys.push("yt:" + song.youtube_id);
  if (song.niconico_id) keys.push("nc:" + song.niconico_id);
  if (song.title && song.producer) keys.push("tp:" + song.title + "__" + song.producer);
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

  const fmt = function (dt) {
    const yy = dt.getUTCFullYear();
    const mm = String(dt.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(dt.getUTCDate()).padStart(2, "0");
    return yy + "/" + mm + "/" + dd;
  };
  return fmt(startDt) + " - " + fmt(endDt);
}

function extractUpdateDateString(data) {
  const rawUpdate = data.publishDate || data.updated_at || data.published_at || "";
  if (rawUpdate && typeof rawUpdate === "string") {
    const m = rawUpdate.match(/(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})/);
    if (m) {
      return m[1] + "/" + String(m[2]).padStart(2, "0") + "/" + String(m[3]).padStart(2, "0");
    }
  }
  return "";
}

async function initChartApp() {
  await loadArchiveIndexOnly();
  await loadAndRenderChart();

  try {
    const songs = getSongsArray(currentChartData);
    const needsHistoryEnrich = songs.some(function (s) {
      return typeof s.chart_in_count !== "number" || s.chart_in_count < 1;
    });

    if (needsHistoryEnrich) {
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
  const indexData = await fetchJsonWithFallback(
    [
      "./data/archives/archive_index.json",
      "./data/archive_index.json",
      "public/data/archives/archive_index.json",
      "public/data/archive_index.json"
    ],
    "no-cache"
  );

  const selectEl = document.getElementById("archive-select");
  const rawArchiveList = Array.isArray(indexData)
    ? indexData
    : indexData && Array.isArray(indexData.archives)
    ? indexData.archives
    : [];

  const archiveList = rawArchiveList.filter(function (item) {
    if (isLocalOwnerPreview()) return true;
    if (typeof item === "string") {
      const stem = item.replace(/\.json$/i, "");
      return isChartReleasedForPublic({ publishDate: stem });
    }
    return isChartReleasedForPublic(item);
  });

  cachedArchiveListMeta = archiveList;
  if (!archiveList.length) {
    return;
  }

  if (selectEl && selectEl.options.length <= 1) {
    archiveList.forEach(function (item) {
      const fileVal =
        typeof item === "string"
          ? item
          : item.file || item.path || (item.archiveId ? item.archiveId + ".json" : item.id);
      let labelText =
        typeof item === "string"
          ? item
          : item.label || item.period || item.publishDate || item.archiveId || item.id;
      if (labelText && typeof labelText === "string") {
        labelText = labelText.replace(
          /(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}\s*[\-~〜]\s*\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2})/,
          function (m) {
            return normalizePeriodString(m);
          }
        );
      }
      const safeFile = sanitizeArchiveFilename(fileVal);
      if (!safeFile) return;
      const opt = document.createElement("option");
      opt.value = safeFile;
      opt.textContent = labelText;
      selectEl.appendChild(opt);
    });

    selectEl.addEventListener("change", async function (e) {
      const val = e.target.value;
      if (val === "latest") {
        await loadAndRenderChart();
      } else {
        const cleanFile = sanitizeArchiveFilename(val);
        if (!cleanFile) return;
        const archiveData = await fetchJsonWithFallback(
          ["./data/archives/" + cleanFile, "public/data/archives/" + cleanFile],
          "default"
        );
        if (archiveData && isChartReleasedForPublic(archiveData)) {
          const archiveSongs = getSongsArray(archiveData);
          const archiveNeedsEnrich = archiveSongs.some(function (s) {
            return typeof s.chart_in_count !== "number" || s.chart_in_count < 1;
          });
          if (archiveNeedsEnrich) {
            await ensureFullArchiveHistoryLoaded();
            enrichWithHistory(archiveData);
          }
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

  try {
    const cachedRaw = sessionStorage.getItem(ARCHIVE_HISTORY_SESSION_KEY);
    if (cachedRaw) {
      const parsed = JSON.parse(cachedRaw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        archiveHistoryCache = parsed;
        return;
      }
    }
  } catch (_) {
    // ignore sessionStorage error
  }

  const loadedArchives = [];
  for (let i = 0; i < cachedArchiveListMeta.length; i++) {
    const item = cachedArchiveListMeta[i];
    const rawFile =
      typeof item === "string"
        ? item
        : item.file || item.path || (item.archiveId ? item.archiveId + ".json" : item.id);
    const cleanFile = sanitizeArchiveFilename(rawFile);
    if (!cleanFile) continue;
    const data = await fetchJsonWithFallback(
      ["./data/archives/" + cleanFile, "public/data/archives/" + cleanFile],
      "default"
    );
    if (data && getSongsArray(data).length > 0 && isChartReleasedForPublic(data)) {
      loadedArchives.push(data);
    }
  }
  archiveHistoryCache = loadedArchives;

  try {
    sessionStorage.setItem(ARCHIVE_HISTORY_SESSION_KEY, JSON.stringify(loadedArchives));
  } catch (_) {
    // ignore quota error
  }
}

function enrichWithHistory(chartData) {
  const songs = getSongsArray(chartData);
  if (!songs.length || !archiveHistoryCache.length) return;

  const targetKey =
    chartData.archiveId || chartData.publishDate || chartData.period || chartData.updated_at || "";

  const olderCharts = archiveHistoryCache.filter(function (c) {
    const p = c.archiveId || c.publishDate || c.period || c.updated_at || "";
    return p && targetKey ? p < targetKey : false;
  });

  const prevChart = olderCharts.length > 0 ? olderCharts[olderCharts.length - 1] : null;

  songs.forEach(function (song) {
    const keys = getSongIdentityKeys(song);

    if (typeof song.chart_in_count !== "number" || song.chart_in_count < 1) {
      let count = 1;
      olderCharts.forEach(function (past) {
        const matched = getSongsArray(past)
          .slice(0, 20)
          .some(function (ps) {
            const pKeys = getSongIdentityKeys(ps);
            return keys.some(function (k) {
              return pKeys.indexOf(k) !== -1;
            });
          });
        if (matched) count += 1;
      });
      song.chart_in_count = count;
    }

    if (song.prev_total_pt === undefined && prevChart) {
      const prevSong = getSongsArray(prevChart).find(function (ps) {
        const pKeys = getSongIdentityKeys(ps);
        return keys.some(function (k) {
          return pKeys.indexOf(k) !== -1;
        });
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

async function loadLatestReleasedArchiveFallback() {
  for (let i = 0; i < cachedArchiveListMeta.length; i++) {
    const item = cachedArchiveListMeta[i];
    const rawFile =
      typeof item === "string"
        ? item
        : item.file || item.path || (item.archiveId ? item.archiveId + ".json" : item.id);
    const cleanFile = sanitizeArchiveFilename(rawFile);
    if (!cleanFile) continue;
    const archiveData = await fetchJsonWithFallback(
      ["./data/archives/" + cleanFile, "public/data/archives/" + cleanFile],
      "no-cache"
    );
    if (archiveData && isChartReleasedForPublic(archiveData)) {
      return archiveData;
    }
  }
  return null;
}

async function loadAndRenderChart() {
  const candidateUrls = isLocalOwnerPreview()
    ? [
        "./data/latest_ranking.json",
        "./data/drafts/weekly_draft.json",
        "./data/weekly_draft.json",
        "public/data/latest_ranking.json"
      ]
    : [
        "./data/latest_ranking.json",
        "data/latest_ranking.json",
        "public/data/latest_ranking.json",
        "latest_ranking.json"
      ];

  let data = await fetchJsonWithFallback(candidateUrls, "no-cache");

  if (data && !isChartReleasedForPublic(data)) {
    const fallbackReleased = await loadLatestReleasedArchiveFallback();
    if (fallbackReleased) {
      data = fallbackReleased;
    }
  }

  if (data) {
    try {
      localStorage.setItem(LAST_KNOWN_CHART_STORAGE_KEY, JSON.stringify(data));
    } catch (_) {
      // ignore storage quota errors
    }
  } else {
    try {
      const cachedStr = localStorage.getItem(LAST_KNOWN_CHART_STORAGE_KEY);
      if (cachedStr) {
        const parsedCache = JSON.parse(cachedStr);
        if (isChartReleasedForPublic(parsedCache)) {
          data = parsedCache;
          showToast("回線混雑のためキャッシュデータを表示しています");
        }
      }
    } catch (_) {
      data = null;
    }
  }

  if (!data) {
    const container = document.getElementById("ranking-container");
    if (container) {
      container.innerHTML =
        '<div class="error-state">ランキングデータの読み込みに失敗しました。再読み込みをお試しください。</div>';
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
      periodEl.textContent = cleanPeriod + " / 更新: " + updateDate;
    } else if (cleanPeriod) {
      periodEl.textContent = cleanPeriod;
    } else if (updateDate) {
      periodEl.textContent = "更新: " + updateDate;
    } else {
      periodEl.textContent = "最新チャート";
    }
  }

  if (data.milestone_message) {
    const bannerEl = document.getElementById("milestone-banner");
    const bannerTextEl = document.getElementById("milestone-text");
    if (bannerEl && bannerTextEl) {
      bannerTextEl.textContent = data.milestone_message;
      bannerEl.style.display = "block";
    }
  }

  const ranking = getSongsArray(data);
  renderRankingView(ranking);
  renderInsightTable(ranking);
  renderCommentaryView(data, ranking);

  const insightSection = document.getElementById("tab-insight");
  if (insightSection && insightSection.classList.contains("active")) {
    ensureChartJsLoaded().then(function () {
      renderTop10InsightChart(ranking);
    });
  }

  requestAnimationFrame(function () {
    refreshAllScrollHints();
  });
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
    yt_views: yt_views,
    yt_likes: yt_likes,
    yt_comments: yt_comments,
    nc_views: nc_views,
    nc_mylists: nc_mylists,
    nc_comments: nc_comments,
    yt_total: yt_total,
    nc_total: nc_total,
    total_pt: total_pt,
    calcSum: calcSum > 0 ? calcSum : 1,
    rawNcMylist: rawNcMylist
  };
}

function formatRankDiffBadge(song) {
  const prev = parseInt(song.prev_rank !== undefined ? song.prev_rank : song.prevRank, 10);
  const curr = parseInt(song.rank, 10);
  if (!prev || isNaN(prev)) {
    return '<span class="rank-diff diff-new">NEW</span>';
  }
  if (prev > curr) {
    return '<span class="rank-diff diff-up">▲' + (prev - curr) + " (前週" + prev + "位)</span>";
  }
  if (prev < curr) {
    return '<span class="rank-diff diff-down">▼' + (curr - prev) + " (前週" + prev + "位)</span>";
  }
  return '<span class="rank-diff diff-stay">→ KEEP (前週' + prev + "位)</span>";
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
    return '<span class="pt-ratio-new">NEW</span>';
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
    return '<span class="pt-ratio-up">∧' + roundedRatio + "%</span>";
  } else if (isDown) {
    return '<span class="pt-ratio-down">∨' + roundedRatio + "%</span>";
  } else {
    return '<span class="pt-ratio-stay">→' + roundedRatio + "%</span>";
  }
}

function getOptimizedThumbnailAttrs(song, index) {
  const safeThumbUrl = sanitizeThumbnailUrl(song.thumbnail, song.youtube_id);
  if (!safeThumbUrl) return null;

  const isAboveFold = index < 3;
  const loadingAttr = isAboveFold ? "eager" : "lazy";
  const priorityAttr = isAboveFold ? 'fetchpriority="high"' : 'fetchpriority="low"';

  return {
    url: safeThumbUrl,
    loadingAttr: loadingAttr,
    priorityAttr: priorityAttr
  };
}

function getFilteredAndSortedSongs(ranking) {
  let list = ranking.slice(0, 20).map(function (s, i) {
    return Object.assign({}, s, {
      _origRank: parseInt(s.rank, 10) || i + 1
    });
  });

  if (showFavoritesOnly) {
    list = list.filter(function (s) {
      return isSongFavorited(s);
    });
  }

  if (currentSearchQuery) {
    list = list.filter(function (s) {
      const hay = ((s.title || "") + " " + (s.producer || "") + " " + (s.vocal || "")).toLowerCase();
      return hay.indexOf(currentSearchQuery) !== -1;
    });
  }

  if (currentSortMode === "pt_ratio") {
    list.sort(function (a, b) {
      return (b.pt_ratio || 0) - (a.pt_ratio || 0);
    });
  } else if (currentSortMode === "chart_in") {
    list.sort(function (a, b) {
      return (b.chart_in_count || 1) - (a.chart_in_count || 1);
    });
  } else if (currentSortMode === "yt_share") {
    list.sort(function (a, b) {
      const ba = getPointsBreakdown(a);
      const bb = getPointsBreakdown(b);
      return bb.yt_total / bb.calcSum - ba.yt_total / ba.calcSum;
    });
  } else if (currentSortMode === "nc_share") {
    list.sort(function (a, b) {
      const ba = getPointsBreakdown(a);
      const bb = getPointsBreakdown(b);
      return bb.nc_total / bb.calcSum - ba.nc_total / ba.calcSum;
    });
  } else {
    list.sort(function (a, b) {
      return a._origRank - b._origRank;
    });
  }

  return list;
}

function buildRankCardHtml(song, idx) {
  const rankNum = song._origRank || parseInt(song.rank, 10) || idx + 1;
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
  const chartInCount = parseInt(song.chart_in_count, 10) || 1;
  const thumbInfo = getOptimizedThumbnailAttrs(song, idx);
  const safeYtId = sanitizeYoutubeId(song.youtube_id);
  const safeNcId = sanitizeNiconicoId(song.niconico_id);
  const songKey = getPrimarySongKey(song);
  const isFav = isSongFavorited(song);

  let thumbHtml = "";
  if (thumbInfo) {
    thumbHtml =
      '<div class="rank-thumb-col">' +
      '<img src="' +
      escapeHtml(thumbInfo.url) +
      '" alt="' +
      escapeHtml(song.title) +
      '" class="rank-thumb" width="112" height="63" loading="' +
      thumbInfo.loadingAttr +
      '" decoding="async" referrerpolicy="no-referrer" ' +
      thumbInfo.priorityAttr +
      " />" +
      "</div>";
  }

  const vocalHtml = song.vocal
    ? '<span class="song-vocal">feat. ' + escapeHtml(song.vocal) + "</span>"
    : "";

  const ytLinkHtml = safeYtId
    ? '<a href="https://www.youtube.com/watch?v=' +
      encodeURIComponent(safeYtId) +
      '" target="_blank" rel="noopener noreferrer" class="video-link yt-link">▶ YouTubeで視聴する</a>'
    : "";

  const ncLinkHtml = safeNcId
    ? '<a href="https://www.nicovideo.jp/watch/' +
      encodeURIComponent(safeNcId) +
      '" target="_blank" rel="noopener noreferrer" class="video-link nc-link">▶ ニコニコ動画で視聴する</a>'
    : "";

  const commentaryHtml = song.commentary
    ? '<div class="commentary-box"><h5>楽曲解説・チャート分析</h5><p>' +
      escapeHtml(song.commentary).replace(/\n/g, "<br>") +
      "</p></div>"
    : "";

  const favClass = isFav ? "favorited" : "";
  const favTitle = isFav ? "お気に入り解除" : "お気に入りに保存";
  const favSymbol = isFav ? "★" : "☆";

  return (
    '<article class="rank-card rank-' +
    rankNum +
    '" data-rank="' +
    rankNum +
    '">' +
    '<div class="rank-card-summary">' +
    '<div class="rank-number-col">' +
    '<span class="rank-number">' +
    rankNum +
    "<small>位</small></span>" +
    formatRankDiffBadge(song) +
    '<span class="chart-in-mini">' +
    chartInCount +
    "週目</span>" +
    "</div>" +
    thumbHtml +
    '<div class="rank-info-col">' +
    '<div class="song-title-row">' +
    '<h3 class="song-title">' +
    escapeHtml(song.title) +
    "</h3>" +
    '<div class="card-inline-actions">' +
    '<button type="button" class="fav-star-btn ' +
    favClass +
    '" data-song-key="' +
    escapeHtml(songKey) +
    '" title="' +
    favTitle +
    '" aria-label="お気に入り">' +
    favSymbol +
    "</button>" +
    '<button type="button" id="detail-btn-' +
    rankNum +
    '" class="detail-toggle-btn" data-rank="' +
    rankNum +
    '">詳細を見る ▾</button>' +
    "</div>" +
    "</div>" +
    '<div class="song-meta">' +
    '<span class="song-producer">' +
    escapeHtml(song.producer) +
    "</span>" +
    vocalHtml +
    "</div>" +
    '<div class="metric-stacked-bar">' +
    '<div class="bar-seg seg-yt-views" style="width: ' +
    pYtViews +
    '%" title="YouTube再生: ' +
    Number(bd.yt_views).toLocaleString() +
    " pt (" +
    pYtViews +
    '%)"></div>' +
    '<div class="bar-seg seg-yt-likes" style="width: ' +
    pYtLikes +
    '%" title="YouTube高評価: ' +
    Number(bd.yt_likes).toLocaleString() +
    " pt (" +
    pYtLikes +
    '%)"></div>' +
    '<div class="bar-seg seg-yt-comments" style="width: ' +
    pYtComments +
    '%" title="YouTubeコメント: ' +
    Number(bd.yt_comments).toLocaleString() +
    " pt (" +
    pYtComments +
    '%)"></div>' +
    '<div class="bar-seg seg-nc-views" style="width: ' +
    pNcViews +
    '%" title="ニコ動再生: ' +
    Number(bd.nc_views).toLocaleString() +
    " pt (" +
    pNcViews +
    '%)"></div>' +
    '<div class="bar-seg seg-nc-mylists" style="width: ' +
    pNcMylists +
    '%" title="ニコ動マイリス: ' +
    Number(bd.nc_mylists).toLocaleString() +
    " pt (" +
    pNcMylists +
    '%)"></div>' +
    '<div class="bar-seg seg-nc-comments" style="width: ' +
    pNcComments +
    '%" title="ニコ動コメント: ' +
    Number(bd.nc_comments).toLocaleString() +
    " pt (" +
    pNcComments +
    '%)"></div>' +
    "</div>" +
    "</div>" +
    '<div class="rank-points-col">' +
    '<div class="total-points">' +
    Number(bd.total_pt).toLocaleString() +
    " <small>pt</small></div>" +
    '<div class="points-sub-row">' +
    "<span>前週比: " +
    formatPointRatioHTML(song) +
    "</span>" +
    '<span class="platform-split-text">YT ' +
    ytPercent +
    "% / NC " +
    ncPercent +
    "%</span>" +
    "</div>" +
    "</div>" +
    "</div>" +
    '<div id="detail-panel-' +
    rankNum +
    '" class="rank-detail-panel">' +
    '<div class="detail-grid">' +
    '<div class="detail-box yt-detail-box">' +
    "<h4>YouTube 指標内訳 (" +
    Number(bd.yt_total).toLocaleString() +
    " pt / " +
    ytPercent +
    "%)</h4>" +
    "<ul>" +
    '<li><span><i class="legend-dot seg-yt-views"></i>週間再生数:</span> <strong>+' +
    Number(raw.yt_views || 0).toLocaleString() +
    "</strong> (" +
    Number(bd.yt_views).toLocaleString() +
    " pt)</li>" +
    '<li><span><i class="legend-dot seg-yt-likes"></i>週間高評価数:</span> <strong>+' +
    Number(raw.yt_likes || 0).toLocaleString() +
    "</strong> (" +
    Number(bd.yt_likes).toLocaleString() +
    " pt)</li>" +
    '<li><span><i class="legend-dot seg-yt-comments"></i>週間コメント数:</span> <strong>+' +
    Number(raw.yt_comments || 0).toLocaleString() +
    "</strong> (" +
    Number(bd.yt_comments).toLocaleString() +
    " pt)</li>" +
    "</ul>" +
    ytLinkHtml +
    "</div>" +
    '<div class="detail-box nc-detail-box">' +
    "<h4>ニコニコ動画 指標内訳 (" +
    Number(bd.nc_total).toLocaleString() +
    " pt / " +
    ncPercent +
    "%)</h4>" +
    "<ul>" +
    '<li><span><i class="legend-dot seg-nc-views"></i>週間再生数:</span> <strong>+' +
    Number(raw.nc_views || 0).toLocaleString() +
    "</strong> (" +
    Number(bd.nc_views).toLocaleString() +
    " pt)</li>" +
    '<li><span><i class="legend-dot seg-nc-mylists"></i>週間マイリスト数:</span> <strong>+' +
    Number(bd.rawNcMylist).toLocaleString() +
    "</strong> (" +
    Number(bd.nc_mylists).toLocaleString() +
    " pt)</li>" +
    '<li><span><i class="legend-dot seg-nc-comments"></i>週間コメント数:</span> <strong>+' +
    Number(raw.nc_comments || 0).toLocaleString() +
    "</strong> (" +
    Number(bd.nc_comments).toLocaleString() +
    " pt)</li>" +
    "</ul>" +
    ncLinkHtml +
    "</div>" +
    "</div>" +
    '<div class="detail-share-row">' +
    '<button type="button" class="share-song-x-btn" data-rank="' +
    rankNum +
    '" data-title="' +
    escapeHtml(song.title) +
    '" data-producer="' +
    escapeHtml(song.producer) +
    '" data-pt="' +
    Number(bd.total_pt).toLocaleString() +
    '">𝕏 この楽曲のランクインをシェアする</button>' +
    "</div>" +
    commentaryHtml +
    "</div>" +
    "</article>"
  );
}

function renderRankingView(ranking) {
  const container = document.getElementById("ranking-container");
  if (!container) return;

  if (!ranking.length) {
    container.innerHTML = '<div class="empty-state">表示できるランキングデータがありません。</div>';
    return;
  }

  const displayList = getFilteredAndSortedSongs(ranking);
  if (!displayList.length) {
    container.innerHTML = '<div class="empty-state">条件に一致する楽曲が見つかりませんでした。</div>';
    return;
  }

  const htmlParts = [];
  for (let i = 0; i < displayList.length; i++) {
    htmlParts.push(buildRankCardHtml(displayList[i], i));
  }
  container.innerHTML = htmlParts.join("");
}

window.toggleRankDetail = function (rank, event) {
  if (event) {
    event.stopPropagation();
  }
  const safeRank = parseInt(rank, 10);
  if (isNaN(safeRank)) return;

  const panel = document.getElementById("detail-panel-" + safeRank);
  const btn = document.getElementById("detail-btn-" + safeRank);
  if (panel) {
    const isOpen = panel.classList.toggle("open");
    if (btn) {
      btn.textContent = isOpen ? "閉じる ▴" : "詳細を見る ▾";
      btn.classList.toggle("open", isOpen);
    }
    if (isOpen && isSmartphoneViewport()) {
      setTimeout(function () {
        const rect = panel.getBoundingClientRect();
        if (rect.bottom > window.innerHeight) {
          panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }, 60);
    }
  }
};

function renderTop10InsightChart(ranking) {
  const wrapper =
    document.getElementById("insight-chart-wrapper") || document.querySelector(".chart-wrapper");
  if (!wrapper) return;

  const top10 = ranking.slice(0, 10);
  if (!top10.length) return;

  const isMobile = isSmartphoneViewport();
  const labels = top10.map(function (s, i) {
    const r = parseInt(s.rank, 10) || i + 1;
    const titleStr = String(s.title || "");
    const shortTitle = isMobile && titleStr.length > 10 ? titleStr.slice(0, 10) + "…" : titleStr;
    return r + "位: " + shortTitle;
  });
  const breakdowns = top10.map(function (s) {
    return getPointsBreakdown(s);
  });

  let canvas = document.getElementById("top5Chart") || document.getElementById("top20Chart");

  if (typeof Chart !== "undefined") {
    if (!canvas) {
      wrapper.innerHTML = '<canvas id="top5Chart"></canvas>';
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
          labels: labels,
          datasets: [
            {
              label: "YouTube 再生",
              data: breakdowns.map(function (b) {
                return b.yt_views;
              }),
              backgroundColor: METRIC_COLORS.yt_views
            },
            {
              label: "YouTube 高評価",
              data: breakdowns.map(function (b) {
                return b.yt_likes;
              }),
              backgroundColor: METRIC_COLORS.yt_likes
            },
            {
              label: "YouTube コメント",
              data: breakdowns.map(function (b) {
                return b.yt_comments;
              }),
              backgroundColor: METRIC_COLORS.yt_comments
            },
            {
              label: "ニコ動 再生",
              data: breakdowns.map(function (b) {
                return b.nc_views;
              }),
              backgroundColor: METRIC_COLORS.nc_views
            },
            {
              label: "ニコ動 マイリス",
              data: breakdowns.map(function (b) {
                return b.nc_mylists;
              }),
              backgroundColor: METRIC_COLORS.nc_mylists
            },
            {
              label: "ニコ動 コメント",
              data: breakdowns.map(function (b) {
                return b.nc_comments;
              }),
              backgroundColor: METRIC_COLORS.nc_comments
            }
          ]
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
                }
              },
              grid: { color: "rgba(148, 163, 184, 0.12)" }
            },
            y: {
              stacked: true,
              ticks: { color: "#f8fafc", font: { size: isMobile ? 11 : 12, weight: "600" } },
              grid: { display: false }
            }
          },
          plugins: {
            legend: {
              position: "top",
              labels: {
                color: "#e2e8f0",
                boxWidth: isMobile ? 10 : 14,
                padding: isMobile ? 8 : 14,
                font: { size: isMobile ? 11 : 12 }
              }
            },
            tooltip: {
              callbacks: {
                label: function (context) {
                  const val = Number(context.raw || 0).toLocaleString();
                  return context.dataset.label + ": " + val + " pt";
                }
              }
            }
          }
        }
      });
      insightChartInstance.resize();
      return;
    } catch (err) {
      console.warn("Chart.js 描画エラーのため HTML フォールバックを使用します:", err);
    }
  }

  let maxPt = 1;
  for (let i = 0; i < breakdowns.length; i++) {
    if (breakdowns[i].total_pt > maxPt) {
      maxPt = breakdowns[i].total_pt;
    }
  }

  const rowHtmls = top10.map(function (song, i) {
    const r = parseInt(song.rank, 10) || i + 1;
    const b = breakdowns[i];
    const wTotal = ((b.total_pt / maxPt) * 100).toFixed(2);
    const denom = b.calcSum;
    return (
      '<div class="fallback-chart-row">' +
      '<div class="fallback-chart-label" title="' +
      escapeHtml(song.title) +
      '">' +
      r +
      "位: " +
      escapeHtml(song.title) +
      "</div>" +
      '<div class="fallback-chart-bar-track">' +
      '<div class="fallback-chart-bar-fill" style="width: ' +
      wTotal +
      '%">' +
      '<div class="bar-seg seg-yt-views" style="width: ' +
      ((b.yt_views / denom) * 100).toFixed(2) +
      '%"></div>' +
      '<div class="bar-seg seg-yt-likes" style="width: ' +
      ((b.yt_likes / denom) * 100).toFixed(2) +
      '%"></div>' +
      '<div class="bar-seg seg-yt-comments" style="width: ' +
      ((b.yt_comments / denom) * 100).toFixed(2) +
      '%"></div>' +
      '<div class="bar-seg seg-nc-views" style="width: ' +
      ((b.nc_views / denom) * 100).toFixed(2) +
      '%"></div>' +
      '<div class="bar-seg seg-nc-mylists" style="width: ' +
      ((b.nc_mylists / denom) * 100).toFixed(2) +
      '%"></div>' +
      '<div class="bar-seg seg-nc-comments" style="width: ' +
      ((b.nc_comments / denom) * 100).toFixed(2) +
      '%"></div>' +
      "</div>" +
      "</div>" +
      '<div class="fallback-chart-pt">' +
      Number(b.total_pt).toLocaleString() +
      " pt</div>" +
      "</div>"
    );
  });

  wrapper.innerHTML =
    '<div class="fallback-chart-legend">' +
    '<span><i class="legend-dot seg-yt-views"></i>YouTube 再生</span>' +
    '<span><i class="legend-dot seg-yt-likes"></i>YouTube 高評価</span>' +
    '<span><i class="legend-dot seg-yt-comments"></i>YouTube コメント</span>' +
    '<span><i class="legend-dot seg-nc-views"></i>ニコ動 再生</span>' +
    '<span><i class="legend-dot seg-nc-mylists"></i>ニコ動 マイリス</span>' +
    '<span><i class="legend-dot seg-nc-comments"></i>ニコ動 コメント</span>' +
    "</div>" +
    '<div class="fallback-chart-rows">' +
    rowHtmls.join("") +
    "</div>";
}

function renderInsightTable(ranking) {
  const tbody =
    document.getElementById("insight-table-body") ||
    document.querySelector("#insight-table-container tbody");
  if (!tbody) return;

  const top10 = ranking.slice(0, 10);
  if (!top10.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="loading-cell">データがありません。</td></tr>';
    return;
  }

  tbody.innerHTML = top10
    .map(function (song, i) {
      const r = parseInt(song.rank, 10) || i + 1;
      const bd = getPointsBreakdown(song);
      const ytRatio = bd.total_pt > 0 ? ((bd.yt_total / bd.total_pt) * 100).toFixed(1) : "0.0";
      const ncRatio = bd.total_pt > 0 ? ((bd.nc_total / bd.total_pt) * 100).toFixed(1) : "0.0";
      const chartInCount = parseInt(song.chart_in_count, 10) || 1;

      return (
        "<tr>" +
        '<td class="col-rank">' +
        r +
        "位</td>" +
        '<td class="col-song">' +
        '<span class="insight-song-title">' +
        escapeHtml(song.title) +
        "</span>" +
        '<span class="insight-song-producer">(' +
        escapeHtml(song.producer) +
        ")</span>" +
        "</td>" +
        '<td class="col-total-pt">' +
        Number(bd.total_pt).toLocaleString() +
        " pt</td>" +
        '<td class="col-pt-ratio">' +
        formatPointRatioHTML(song) +
        "</td>" +
        '<td class="col-chart-in">' +
        chartInCount +
        "回</td>" +
        '<td class="col-yt-ratio">' +
        ytRatio +
        "% (" +
        Number(bd.yt_total).toLocaleString() +
        " pt)</td>" +
        '<td class="col-nc-ratio">' +
        ncRatio +
        "% (" +
        Number(bd.nc_total).toLocaleString() +
        " pt)</td>" +
        "</tr>"
      );
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
      ? "<p>" + escapeHtml(overallText).replace(/\n/g, "<br>") + "</p>"
      : '<p class="muted-text">今週の全体総評はまだ登録されていません。</p>';
  }

  const listEl = document.getElementById("commentary-container");
  if (!listEl) return;

  const commentedSongs = ranking.filter(function (s) {
    return s.commentary && String(s.commentary).trim() !== "";
  });
  if (!commentedSongs.length) {
    listEl.innerHTML = '<div class="empty-state">楽曲別の解説はまだ登録されていません。</div>';
    return;
  }

  listEl.innerHTML = commentedSongs
    .map(function (song, i) {
      const r = parseInt(song.rank, 10) || i + 1;
      return (
        '<div class="commentary-card">' +
        '<div class="commentary-card-header">' +
        '<span class="commentary-rank-badge">' +
        r +
        "位</span>" +
        '<h3 class="commentary-song-title">' +
        escapeHtml(song.title) +
        " <small>/ " +
        escapeHtml(song.producer) +
        "</small></h3>" +
        '<span class="commentary-song-pt">' +
        Number(song.total_pt || 0).toLocaleString() +
        " pt</span>" +
        "</div>" +
        '<div class="commentary-card-body">' +
        escapeHtml(song.commentary).replace(/\n/g, "<br>") +
        "</div>" +
        "</div>"
      );
    })
    .join("");
}

/* ==========================================================================
   5. 「記事・コラム」システム（Billboard Japan × ソシャゲなう風＋左右対話システム）
   ========================================================================== */

function getArticlesTabId() {
  const candidates = ["tab-articles", "tab-columns", "tab-column"];
  for (let i = 0; i < candidates.length; i++) {
    if (document.getElementById(candidates[i])) {
      return candidates[i];
    }
  }
  const buttons = document.querySelectorAll(".tab-btn");
  for (let j = 0; j < buttons.length; j++) {
    const txt = buttons[j].textContent || "";
    if (txt.indexOf("記事") !== -1 || txt.indexOf("コラム") !== -1) {
      return buttons[j].getAttribute("data-tab") || "tab-articles";
    }
  }
  return "tab-articles";
}

function ensureArticlesTabStructure() {
  let tabId = getArticlesTabId();
  let sectionEl = document.getElementById(tabId);

  if (!sectionEl) {
    tabId = "tab-articles";
    const tabNav = document.getElementById("tab-nav");
    const methodBtn = tabNav ? tabNav.querySelector('[data-tab="tab-method"]') : null;
    if (tabNav && !tabNav.querySelector('[data-tab="' + tabId + '"]')) {
      const newBtn = document.createElement("button");
      newBtn.className = "tab-btn";
      newBtn.setAttribute("data-tab", tabId);
      newBtn.textContent = "記事・コラム";
      if (methodBtn) {
        tabNav.insertBefore(newBtn, methodBtn);
      } else {
        tabNav.appendChild(newBtn);
      }
      newBtn.addEventListener("click", function () {
        activateTabById(tabId);
      });
    }

    const mainContainer = document.querySelector(".main-container") || document.body;
    const methodSec = document.getElementById("tab-method");
    sectionEl = document.createElement("section");
    sectionEl.id = tabId;
    sectionEl.className = "tab-content";
    if (methodSec && methodSec.parentElement === mainContainer) {
      mainContainer.insertBefore(sectionEl, methodSec);
    } else {
      mainContainer.appendChild(sectionEl);
    }
  }

  const hasExistingGrid = Boolean(
    sectionEl.querySelector("#articles-grid") ||
      sectionEl.querySelector("#column-grid") ||
      sectionEl.querySelector("#articles-container") ||
      sectionEl.querySelector("#column-list")
  );

  if (!hasExistingGrid) {
    sectionEl.innerHTML =
      '<div id="articles-list-view" class="articles-list-view">' +
      '<div class="section-header section-header-flex">' +
      "<div>" +
      '<h2 class="section-title">記事・コラム / 特集</h2>' +
      '<p class="articles-lead-sub">ボカロシーンのトレンド深掘り分析・ボカロP特集・楽曲レビュー・対談コラム</p>' +
      "</div>" +
      "</div>" +
      '<div class="articles-toolbar">' +
      '<div id="article-category-bar" class="article-category-bar" role="tablist" aria-label="記事カテゴリ絞り込み">' +
      '<button type="button" class="article-cat-btn active" data-category="all">すべて</button>' +
      '<button type="button" class="article-cat-btn" data-category="チャート分析">チャート分析</button>' +
      '<button type="button" class="article-cat-btn" data-category="ボカロP特集">ボカロP特集</button>' +
      '<button type="button" class="article-cat-btn" data-category="楽曲レビュー">楽曲レビュー</button>' +
      '<button type="button" class="article-cat-btn" data-category="対談・コラム">対談・コラム</button>' +
      "</div>" +
      '<div class="article-search-wrap">' +
      '<input type="search" id="article-search-input" class="ranking-search-input article-search-input" placeholder="記事タイトル・タグ・キーワードで検索..." autocomplete="off" />' +
      "</div>" +
      "</div>" +
      '<div id="articles-featured-container" class="articles-featured-container"></div>' +
      '<div id="articles-grid" class="articles-grid">' +
      '<div class="loading-state">記事・コラムを読み込んでいます...</div>' +
      "</div>" +
      "</div>" +
      '<div id="article-detail-view" class="article-detail-view" style="display: none;"></div>';
  } else if (!sectionEl.querySelector("#article-detail-view") && !sectionEl.querySelector("#column-detail-view")) {
    const detailDiv = document.createElement("div");
    detailDiv.id = "article-detail-view";
    detailDiv.className = "article-detail-view";
    detailDiv.style.display = "none";
    sectionEl.appendChild(detailDiv);
  }

  return sectionEl;
}

let articlesDataLoaded = false;
let articlesLoadingPromise = null;
const DEFAULT_PAGE_TITLE = document.title || "週刊VOCALOID™複合ランキング";
const DEFAULT_META_DESC = (function () {
  const el = document.querySelector('meta[name="description"]');
  return el ? el.getAttribute("content") || "" : "";
})();

function updatePageSeoMeta(article) {
  const descEl = document.querySelector('meta[name="description"]');
  const ogTitleEl = document.querySelector('meta[property="og:title"]');
  const ogDescEl = document.querySelector('meta[property="og:description"]');
  const ogUrlEl = document.querySelector('meta[property="og:url"]');
  const canonicalEl = document.querySelector('link[rel="canonical"]');

  if (article && article.title) {
    const fullTitle = article.title + " | 週刊VOCALOID™複合ランキング";
    const desc =
      article.summary ||
      article.title + " - 週刊VOCALOID™複合ランキング（" + (article.category || "コラム") + "）";
    const articleUrl =
      OFFICIAL_SITE_URL + "/articles/" + encodeURIComponent(article.id) + ".html";

    document.title = fullTitle;
    if (descEl) descEl.setAttribute("content", desc);
    if (ogTitleEl) ogTitleEl.setAttribute("content", fullTitle);
    if (ogDescEl) ogDescEl.setAttribute("content", desc);
    if (ogUrlEl) ogUrlEl.setAttribute("content", articleUrl);
    if (canonicalEl) canonicalEl.setAttribute("href", articleUrl);
  } else {
    document.title = DEFAULT_PAGE_TITLE;
    if (descEl && DEFAULT_META_DESC) descEl.setAttribute("content", DEFAULT_META_DESC);
    if (ogTitleEl) ogTitleEl.setAttribute("content", DEFAULT_PAGE_TITLE);
    if (ogDescEl && DEFAULT_META_DESC) ogDescEl.setAttribute("content", DEFAULT_META_DESC);
    if (ogUrlEl) ogUrlEl.setAttribute("content", OFFICIAL_SITE_URL);
    if (canonicalEl) canonicalEl.setAttribute("href", OFFICIAL_SITE_URL);
  }
}

async function ensureArticlesLoaded() {
  if (articlesDataLoaded) return;
  if (articlesLoadingPromise) return articlesLoadingPromise;
  articlesLoadingPromise = loadArticlesData().finally(function () {
    articlesDataLoaded = true;
    articlesLoadingPromise = null;
  });
  return articlesLoadingPromise;
}

async function initArticlesSystem() {
  const sectionEl = ensureArticlesTabStructure();
  if (!sectionEl) return;

  const articlesTabId = getArticlesTabId();
  const tabBtn = document.querySelector('.tab-btn[data-tab="' + articlesTabId + '"]');
  if (tabBtn) {
    // 初期表示を重くしないため、「記事・コラム」タブにマウスを乗せた時またはクリックした時に初めて通信を行う
    tabBtn.addEventListener(
      "mouseenter",
      function () {
        if (!isDataSaverEnabled()) ensureArticlesLoaded();
      },
      { passive: true }
    );
    tabBtn.addEventListener("click", function () {
      ensureArticlesLoaded();
    });
  }

  sectionEl.addEventListener("click", function (e) {
    const catBtn = e.target.closest(
      ".article-cat-btn, .category-pill, .column-cat-btn, [data-category]"
    );
    if (catBtn && catBtn.hasAttribute("data-category")) {
      const cat = catBtn.getAttribute("data-category") || "all";
      currentArticleCategory = cat;
      sectionEl
        .querySelectorAll(".article-cat-btn, .category-pill, .column-cat-btn, [data-category]")
        .forEach(function (b) {
          b.classList.toggle("active", b.getAttribute("data-category") === cat);
        });
      if (currentOpenArticleId) {
        closeArticleDetail(false);
      }
      renderArticlesView();
      return;
    }

    // 個別URLリンク (<a class="article-seo-link" href="./articles/xxx.html">) が通常クリックされた場合はそのまま個別URLへ遷移させても良いし、
    // Ctrl/Cmdクリック時はブラウザ標準の別タブ遷移に任せる
    const seoLink = e.target.closest(".article-seo-link");
    if (seoLink) {
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) {
        return;
      }
      // プレビュー環境(localhost)では未ビルドの下書きも読めるようSPAリーダーで開く
      if (isLocalOwnerPreview()) {
        e.preventDefault();
        const card = seoLink.closest("[data-article-id]");
        if (card) openArticleById(card.getAttribute("data-article-id"), true);
      }
      return;
    }

    const openCard = e.target.closest("[data-article-id]");
    if (openCard && !e.target.closest("a") && !e.target.closest("button")) {
      const aid = openCard.getAttribute("data-article-id");
      if (aid) {
        if (!isLocalOwnerPreview()) {
          window.location.href = "./articles/" + encodeURIComponent(aid) + ".html";
        } else {
          openArticleById(aid, true);
        }
      }
      return;
    }

    const backBtn = e.target.closest("#article-back-btn, #column-back-btn, .article-back-btn");
    if (backBtn) {
      closeArticleDetail(true);
      return;
    }

    const shareArticleBtn = e.target.closest(".share-article-x-btn");
    if (shareArticleBtn) {
      const aid = shareArticleBtn.getAttribute("data-share-id");
      const title = shareArticleBtn.getAttribute("data-share-title");
      const cat = shareArticleBtn.getAttribute("data-share-cat") || "記事・コラム";
      const shareUrl = OFFICIAL_SITE_URL + "/articles/" + encodeURIComponent(aid) + ".html";
      const text =
        "【" +
        cat +
        "】" +
        title +
        "\n｜週刊VOCALOID™複合ランキング\n#週刊VOCALOID複合ランキング #ボカロ";
      const intentUrl =
        "https://twitter.com/intent/tweet?text=" +
        encodeURIComponent(text) +
        "&url=" +
        encodeURIComponent(shareUrl);
      window.open(intentUrl, "_blank", "noopener,noreferrer");
      return;
    }

    const copyArticleUrlBtn = e.target.closest(".copy-article-url-btn");
    if (copyArticleUrlBtn) {
      const aid = copyArticleUrlBtn.getAttribute("data-share-id");
      const shareUrl = OFFICIAL_SITE_URL + "/articles/" + encodeURIComponent(aid) + ".html";
      navigator.clipboard
        .writeText(shareUrl)
        .then(function () {
          showToast("🔗 記事の個別URLをコピーしました！");
        })
        .catch(function () {
          showToast("コピーに失敗しました");
        });
    }
  });

  const searchInput =
    sectionEl.querySelector("#article-search-input") ||
    sectionEl.querySelector("#column-search-input") ||
    sectionEl.querySelector('input[type="search"]');
  if (searchInput) {
    searchInput.addEventListener("input", function (e) {
      currentArticleSearchQuery = (e.target.value || "").trim().toLowerCase();
      if (currentOpenArticleId) {
        closeArticleDetail(false);
      }
      renderArticlesView();
    });
  }

  // 初回アクセス時にURLハッシュが #article= または #tab-articles の場合のみ即時読み込みし、
  // 通常のトップページ表示時はバックグラウンドアイドル時まで待機して初期表示を高速化する
  const initialHash = window.location.hash || "";
  if (
    initialHash.indexOf("#article=") === 0 ||
    initialHash === "#" + articlesTabId ||
    sectionEl.classList.contains("active")
  ) {
    await ensureArticlesLoaded();
    checkAndHandleArticleHash();
  } else if (!isSmartphoneViewport() && !isDataSaverEnabled()) {
    const idleFn =
      window.requestIdleCallback ||
      function (cb) {
        setTimeout(cb, 2800);
      };
    idleFn(function () {
      ensureArticlesLoaded();
    });
  }

  window.addEventListener("hashchange", function () {
    ensureArticlesLoaded().then(checkAndHandleArticleHash);
  });
}

async function loadArticlesData() {
  // 本番環境では本文(body)を含まない超軽量な articles_index.json を最優先で読み込む
  const candidateUrls = isLocalOwnerPreview()
    ? [
        "./data/articles/articles_master.json",
        "./data/articles_index.json",
        "./data/articles.json",
        "public/data/articles_index.json",
        "public/data/articles.json"
      ]
    : [
        "./data/articles_index.json",
        "data/articles_index.json",
        "public/data/articles_index.json",
        "./data/articles.json",
        "data/articles.json",
        "public/data/articles.json"
      ];

  const rawData = await fetchJsonWithFallback(candidateUrls, "no-cache");
  let list = [];
  if (Array.isArray(rawData)) {
    list = rawData;
  } else if (rawData && Array.isArray(rawData.articles)) {
    list = rawData.articles;
  }

  allArticlesData = list.filter(function (a) {
    return isArticleReleasedForPublic(a);
  });

  allArticlesData.sort(function (a, b) {
    const da = String(a.publishedAt || a.publishAt || a.updatedAt || "");
    const db = String(b.publishedAt || b.publishAt || b.updatedAt || "");
    return db.localeCompare(da);
  });

  renderArticlesView();
}

function checkAndHandleArticleHash() {
  const hash = window.location.hash || "";
  if (hash.indexOf("#article=") === 0) {
    const targetId = decodeURIComponent(hash.replace("#article=", "").trim());
    if (targetId) {
      const tabId = getArticlesTabId();
      activateTabById(tabId);
      openArticleById(targetId, false);
    }
  } else if (hash === "#" + getArticlesTabId()) {
    activateTabById(getArticlesTabId());
    if (currentOpenArticleId) closeArticleDetail(false);
  } else if (currentOpenArticleId) {
    closeArticleDetail(false);
  }
}

function resolveArticleThumbnail(article) {
  if (!article) return "";
  if (article.thumbnail) {
    const safeUrl = sanitizeSafeImageUrl(article.thumbnail);
    if (safeUrl) return safeUrl;
  }
  if (article.youtubeId || article.youtube_id) {
    const yid = sanitizeYoutubeId(article.youtubeId || article.youtube_id);
    if (yid) return "https://i.ytimg.com/vi/" + yid + "/hqdefault.jpg";
  }
  return "";
}

function formatArticleDate(article) {
  const raw = article.publishedAt || article.publishAt || article.updatedAt || "";
  const m = String(raw).match(/(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})/);
  if (m) {
    return m[1] + "." + String(m[2]).padStart(2, "0") + "." + String(m[3]).padStart(2, "0");
  }
  return raw || "";
}

function getFilteredArticles() {
  return allArticlesData.filter(function (a) {
    if (currentArticleCategory !== "all") {
      if ((a.category || "") !== currentArticleCategory) return false;
    }
    if (currentArticleSearchQuery) {
      const tagsStr = Array.isArray(a.tags) ? a.tags.join(" ") : String(a.tags || "");
      const hay = (
        (a.title || "") +
        " " +
        (a.summary || "") +
        " " +
        (a.category || "") +
        " " +
        tagsStr +
        " " +
        (a.author || "")
      ).toLowerCase();
      if (hay.indexOf(currentArticleSearchQuery) === -1) return false;
    }
    return true;
  });
}

function buildArticleTagRowHtml(tags) {
  if (!Array.isArray(tags) || !tags.length) return "";
  const spans = tags.map(function (t) {
    return '<span class="article-tag">#' + escapeHtml(t) + "</span>";
  });
  return '<div class="article-tag-row">' + spans.join("") + "</div>";
}

function getArticlePermalink(article) {
  const cleanId = encodeURIComponent(String(article.id || "").trim());
  return "./articles/" + cleanId + ".html";
}

function buildHeroArticleHtml(heroArticle) {
  const thumbUrl = resolveArticleThumbnail(heroArticle);
  const dateStr = formatArticleDate(heroArticle);
  const tags = Array.isArray(heroArticle.tags) ? heroArticle.tags : [];
  const permalink = getArticlePermalink(heroArticle);

  const thumbInner = thumbUrl
    ? '<img src="' +
      escapeHtml(thumbUrl) +
      '" alt="' +
      escapeHtml(heroArticle.title) +
      '" class="article-hero-thumb" loading="lazy" decoding="async" referrerpolicy="no-referrer" />'
    : '<div class="article-thumb-placeholder"><span>VOCALOID COLUMN</span></div>';

  const authorHtml = heroArticle.author
    ? '<span class="article-author">by ' + escapeHtml(heroArticle.author) + "</span>"
    : "";

  return (
    '<article class="article-hero-card" data-article-id="' +
    escapeHtml(heroArticle.id) +
    '">' +
    '<div class="article-hero-thumb-wrap">' +
    thumbInner +
    '<span class="article-pickup-ribbon">PICK UP 特集</span>' +
    "</div>" +
    '<div class="article-hero-body">' +
    '<div class="article-card-meta">' +
    '<span class="article-cat-badge">' +
    escapeHtml(heroArticle.category || "コラム") +
    "</span>" +
    '<time class="article-date">' +
    escapeHtml(dateStr) +
    "</time>" +
    authorHtml +
    "</div>" +
    '<h3 class="article-hero-title"><a href="' +
    escapeHtml(permalink) +
    '" class="article-seo-link" style="color:inherit;text-decoration:none;">' +
    escapeHtml(heroArticle.title) +
    "</a></h3>" +
    '<p class="article-hero-summary">' +
    escapeHtml(heroArticle.summary || "") +
    "</p>" +
    buildArticleTagRowHtml(tags) +
    '<a href="' +
    escapeHtml(permalink) +
    '" class="article-read-more article-seo-link" style="text-decoration:none;">記事を読む ➔</a>' +
    "</div>" +
    "</article>"
  );
}

function buildGridArticleCardHtml(art) {
  const thumbUrl = resolveArticleThumbnail(art);
  const dateStr = formatArticleDate(art);
  const tags = Array.isArray(art.tags) ? art.tags.slice(0, 4) : [];
  const permalink = getArticlePermalink(art);

  const thumbInner = thumbUrl
    ? '<img src="' +
      escapeHtml(thumbUrl) +
      '" alt="' +
      escapeHtml(art.title) +
      '" class="article-card-thumb" loading="lazy" decoding="async" referrerpolicy="no-referrer" />'
    : '<div class="article-thumb-placeholder"><span>COLUMN</span></div>';

  const authorHtml = art.author
    ? '<span class="article-author">' + escapeHtml(art.author) + "</span>"
    : "";

  return (
    '<article class="article-card" data-article-id="' +
    escapeHtml(art.id) +
    '">' +
    '<div class="article-card-thumb-wrap">' +
    thumbInner +
    '<span class="article-cat-badge overlay-badge">' +
    escapeHtml(art.category || "コラム") +
    "</span>" +
    "</div>" +
    '<div class="article-card-body">' +
    '<div class="article-card-meta">' +
    '<time class="article-date">' +
    escapeHtml(dateStr) +
    "</time>" +
    authorHtml +
    "</div>" +
    '<h3 class="article-card-title"><a href="' +
    escapeHtml(permalink) +
    '" class="article-seo-link" style="color:inherit;text-decoration:none;">' +
    escapeHtml(art.title) +
    "</a></h3>" +
    '<p class="article-card-summary">' +
    escapeHtml(art.summary || "") +
    "</p>" +
    buildArticleTagRowHtml(tags) +
    "</div>" +
    "</article>"
  );
}

function renderArticlesView() {
  const sectionEl = document.getElementById(getArticlesTabId());
  if (!sectionEl) return;

  const featuredContainer =
    sectionEl.querySelector("#articles-featured-container") ||
    sectionEl.querySelector("#column-featured-container") ||
    sectionEl.querySelector("#articles-featured");
  const gridContainer =
    sectionEl.querySelector("#articles-grid") ||
    sectionEl.querySelector("#column-grid") ||
    sectionEl.querySelector("#articles-container") ||
    sectionEl.querySelector("#column-list");

  const emptyStateEl =
    sectionEl.querySelector("#column-empty-state") ||
    sectionEl.querySelector("#articles-empty-state");

  if (!gridContainer) return;

  if (!allArticlesData.length) {
    if (featuredContainer) featuredContainer.innerHTML = "";
    if (emptyStateEl) {
      emptyStateEl.style.display = "block";
      gridContainer.innerHTML = "";
    } else {
      gridContainer.innerHTML =
        '<div class="articles-empty-card">' +
        '<div class="articles-empty-badge">COMING SOON</div>' +
        '<h3 class="articles-empty-title">記事・コラムは現在準備中です</h3>' +
        '<p class="articles-empty-desc">' +
        "このタブでは、週間チャートの深掘りトレンド考察、注目ボカロP・新曲の特集レビュー、対話形式のコラム記事を不定期で公開していきます。<br>" +
        "第1弾の記事公開まで今しばらくお待ちください！" +
        "</p>" +
        "</div>";
    }
    return;
  }

  if (emptyStateEl) {
    emptyStateEl.style.display = "none";
  }

  const filtered = getFilteredArticles();
  if (!filtered.length) {
    if (featuredContainer) featuredContainer.innerHTML = "";
    gridContainer.innerHTML =
      '<div class="empty-state">条件に一致する記事・コラムが見つかりませんでした。</div>';
    return;
  }

  const showHero = currentArticleCategory === "all" && !currentArticleSearchQuery;
  const heroArticle = showHero
    ? filtered.find(function (a) {
        return Boolean(a.featured);
      }) || filtered[0]
    : null;

  const gridList =
    heroArticle && featuredContainer
      ? filtered.filter(function (a) {
          return a.id !== heroArticle.id;
        })
      : filtered;

  if (featuredContainer) {
    featuredContainer.innerHTML = heroArticle ? buildHeroArticleHtml(heroArticle) : "";
  }

  if (!gridList.length && heroArticle && featuredContainer) {
    gridContainer.innerHTML = "";
    return;
  }

  gridContainer.innerHTML = gridList.map(buildGridArticleCardHtml).join("");
}

async function openArticleById(articleId, updateHash) {
  await ensureArticlesLoaded();
  let article = allArticlesData.find(function (a) {
    return String(a.id) === String(articleId);
  });
  if (!article) {
    showToast("指定された記事が見つかりません");
    return;
  }

  // 軽量インデックス(articles_index.json)から読み込まれていて本文(body)が未取得の場合、オンデマンドで個別記事JSONを取得
  if (!article.body && !article.content) {
    const cleanId = encodeURIComponent(String(article.id).trim());
    const fullArticle = await fetchJsonWithFallback(
      [
        "./data/articles/" + cleanId + ".json",
        "public/data/articles/" + cleanId + ".json",
        "./data/articles.json"
      ],
      "default"
    );
    if (fullArticle) {
      if (Array.isArray(fullArticle.articles)) {
        const found = fullArticle.articles.find(function (x) {
          return String(x.id) === String(articleId);
        });
        if (found) Object.assign(article, found);
      } else if (fullArticle.body || fullArticle.content) {
        Object.assign(article, fullArticle);
      }
    }
  }

  currentOpenArticleId = article.id;
  if (updateHash) {
    history.pushState(null, "", "#article=" + encodeURIComponent(article.id));
  }
  updatePageSeoMeta(article);

  const sectionEl = document.getElementById(getArticlesTabId());
  if (!sectionEl) return;

  const listView =
    sectionEl.querySelector("#articles-list-view") ||
    sectionEl.querySelector("#column-list-view");
  const detailView =
    sectionEl.querySelector("#article-detail-view") ||
    sectionEl.querySelector("#column-detail-view");
  if (!detailView) return;

  if (listView) {
    listView.style.display = "none";
  } else {
    Array.from(sectionEl.children).forEach(function (ch) {
      if (ch !== detailView) ch.style.display = "none";
    });
  }

  const thumbUrl = resolveArticleThumbnail(article);
  const dateStr = formatArticleDate(article);
  const tags = Array.isArray(article.tags) ? article.tags : [];
  const bodyHtml = parseArticleBodyHtml(article.body || article.content || "");
  const related = allArticlesData
    .filter(function (a) {
      return a.id !== article.id;
    })
    .slice(0, 3);

  const authorHtml = article.author
    ? '<span class="article-author">執筆: ' + escapeHtml(article.author) + "</span>"
    : "";

  const heroImgHtml = thumbUrl
    ? '<div class="article-reader-hero-img-wrap"><img src="' +
      escapeHtml(thumbUrl) +
      '" alt="' +
      escapeHtml(article.title) +
      '" class="article-reader-hero-img" referrerpolicy="no-referrer" /></div>'
    : "";

  const leadHtml = article.summary
    ? '<div class="article-reader-lead">' +
      escapeHtml(article.summary).replace(/\n/g, "<br>") +
      "</div>"
    : "";

  let relatedHtml = "";
  if (related.length) {
    const relatedCards = related.map(buildGridArticleCardHtml).join("");
    relatedHtml =
      '<div class="article-related-section">' +
      '<h3 class="section-title">その他の記事・コラム</h3>' +
      '<div class="articles-grid related-grid">' +
      relatedCards +
      "</div>" +
      "</div>";
  }

  detailView.style.display = "block";
  detailView.innerHTML =
    '<div class="article-reader-card">' +
    '<div class="article-reader-topbar">' +
    '<button type="button" id="article-back-btn" class="article-back-btn">← 記事一覧へ戻る</button>' +
    '<div class="article-share-actions">' +
    '<button type="button" class="action-btn share-article-x-btn" data-share-id="' +
    escapeHtml(article.id) +
    '" data-share-title="' +
    escapeHtml(article.title) +
    '" data-share-cat="' +
    escapeHtml(article.category || "記事・コラム") +
    '">𝕏 記事をシェア</button>' +
    '<button type="button" class="action-btn copy-article-url-btn" data-share-id="' +
    escapeHtml(article.id) +
    '">🔗 個別URLをコピー</button>' +
    "</div>" +
    "</div>" +
    '<header class="article-reader-header">' +
    '<div class="article-card-meta">' +
    '<span class="article-cat-badge">' +
    escapeHtml(article.category || "コラム") +
    "</span>" +
    '<time class="article-date">公開: ' +
    escapeHtml(dateStr) +
    "</time>" +
    authorHtml +
    "</div>" +
    '<h1 class="article-reader-title">' +
    escapeHtml(article.title) +
    "</h1>" +
    buildArticleTagRowHtml(tags) +
    "</header>" +
    heroImgHtml +
    leadHtml +
    '<div class="article-reader-content">' +
    bodyHtml +
    "</div>" +
    '<footer class="article-reader-footer">' +
    '<div class="article-share-box">' +
    "<span>この記事をシェアする：</span>" +
    '<div class="article-share-actions">' +
    '<button type="button" class="action-btn share-article-x-btn" data-share-id="' +
    escapeHtml(article.id) +
    '" data-share-title="' +
    escapeHtml(article.title) +
    '" data-share-cat="' +
    escapeHtml(article.category || "記事・コラム") +
    '">𝕏 ポストする</button>' +
    '<button type="button" class="action-btn copy-article-url-btn" data-share-id="' +
    escapeHtml(article.id) +
    '">🔗 個別URLをコピー</button>' +
    "</div>" +
    "</div>" +
    '<button type="button" class="article-back-btn bottom-back-btn">← 記事・コラム一覧へ戻る</button>' +
    "</footer>" +
    "</div>" +
    relatedHtml;

  window.scrollTo({ top: 0, behavior: "smooth" });
}

function closeArticleDetail(clearHash) {
  currentOpenArticleId = null;
  updatePageSeoMeta(null);
  if (clearHash && window.location.hash.indexOf("#article=") === 0) {
    history.pushState(null, "", window.location.pathname + window.location.search);
  }
  const sectionEl = document.getElementById(getArticlesTabId());
  if (!sectionEl) return;

  const listView =
    sectionEl.querySelector("#articles-list-view") ||
    sectionEl.querySelector("#column-list-view");
  const detailView =
    sectionEl.querySelector("#article-detail-view") ||
    sectionEl.querySelector("#column-detail-view");
  if (detailView) detailView.style.display = "none";

  if (listView) {
    listView.style.display = "block";
  } else {
    Array.from(sectionEl.children).forEach(function (ch) {
      if (ch !== detailView) ch.style.display = "";
    });
  }
}

function renderTalkBubbleHtml(side, name, icon, color, messageText) {
  const cleanSide = String(side || "left").toLowerCase() === "right" ? "right" : "left";
  const safeName = escapeHtml(name || "話し手");
  const safeColor = /^#[0-9A-Fa-f]{3,8}$/.test((color || "").trim()) ? color.trim() : "#00d2ff";
  const safeImgUrl = sanitizeSafeImageUrl(icon);

  const avatarInner = safeImgUrl
    ? '<img src="' +
      escapeHtml(safeImgUrl) +
      '" alt="' +
      safeName +
      '" class="talk-avatar-img" referrerpolicy="no-referrer" />'
    : '<span class="talk-avatar-emoji">' +
      escapeHtml(icon || safeName.slice(0, 2) || "💬") +
      "</span>";

  const formattedMsg = formatInlineMarkdown(messageText || "").replace(/\n/g, "<br>");

  return (
    '<div class="talk-row talk-' +
    cleanSide +
    '">' +
    '<div class="talk-speaker-col">' +
    '<div class="talk-avatar" style="border-color: ' +
    safeColor +
    ';">' +
    avatarInner +
    "</div>" +
    '<span class="talk-speaker-name">' +
    safeName +
    "</span>" +
    "</div>" +
    '<div class="talk-bubble" style="--speaker-color: ' +
    safeColor +
    ';">' +
    '<div class="talk-bubble-text">' +
    formattedMsg +
    "</div>" +
    "</div>" +
    "</div>"
  );
}

function renderVideoEmbedCardHtml(ytId, ncId, titleStr) {
  const safeYt = sanitizeYoutubeId(ytId);
  const safeNc = sanitizeNiconicoId(ncId);
  const thumb = safeYt ? "https://i.ytimg.com/vi/" + safeYt + "/mqdefault.jpg" : "";
  const safeTitle = escapeHtml(titleStr || "関連楽曲・動画リンク");

  const thumbHtml = thumb
    ? '<img src="' +
      escapeHtml(thumb) +
      '" alt="' +
      safeTitle +
      '" class="article-video-thumb" loading="lazy" referrerpolicy="no-referrer" />'
    : "";

  const ytBtn = safeYt
    ? '<a href="https://www.youtube.com/watch?v=' +
      encodeURIComponent(safeYt) +
      '" target="_blank" rel="noopener noreferrer" class="video-link yt-link">▶ YouTubeで視聴</a>'
    : "";

  const ncBtn = safeNc
    ? '<a href="https://www.nicovideo.jp/watch/' +
      encodeURIComponent(safeNc) +
      '" target="_blank" rel="noopener noreferrer" class="video-link nc-link">▶ ニコニコ動画で視聴</a>'
    : "";

  return (
    '<div class="article-video-card">' +
    thumbHtml +
    '<div class="article-video-info">' +
    '<div class="article-video-title">🎵 ' +
    safeTitle +
    "</div>" +
    '<div class="article-video-links">' +
    ytBtn +
    ncBtn +
    "</div>" +
    "</div>" +
    "</div>"
  );
}

function formatInlineMarkdown(rawText) {
  let s = escapeHtml(rawText);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  return s;
}

function parseShortcodeAttrs(attrStr) {
  const attrs = {};
  const regex = /([a-zA-Z0-9_-]+)\s*=\s*"([^"]*)"/g;
  let m;
  while ((m = regex.exec(attrStr)) !== null) {
    attrs[m[1]] = m[2];
  }
  return attrs;
}

function parseArticleBodyHtml(rawBody) {
  if (!rawBody || typeof rawBody !== "string") return "";

  const placeholders = [];
  const pushPlaceholder = function (html) {
    const token = "@@__ARTICLE_BLOCK_" + placeholders.length + "__@@";
    placeholders.push(html);
    return "\n" + token + "\n";
  };

  let text = rawBody.replace(/\r\n/g, "\n");

  text = text.replace(/\[talk([^\]]*)\]([\s\S]*?)\[\/talk\]/gi, function (_, attrStr, inner) {
    const attrs = parseShortcodeAttrs(attrStr);
    return pushPlaceholder(
      renderTalkBubbleHtml(
        attrs.side || "left",
        attrs.name || "",
        attrs.icon || "🎧",
        attrs.color || "#00d2ff",
        inner.trim()
      )
    );
  });

  text = text.replace(/^:::talk\s+([^\n]+)\n([\s\S]*?)^:::\s*$/gm, function (_, headerLine, inner) {
    const parts = headerLine.split("|").map(function (p) {
      return p.trim();
    });
    return pushPlaceholder(
      renderTalkBubbleHtml(
        parts[0] || "left",
        parts[1] || "話し手",
        parts[2] || "💬",
        parts[3] || "#00d2ff",
        inner.trim()
      )
    );
  });

  text = text.replace(/\[point([^\]]*)\]([\s\S]*?)\[\/point\]/gi, function (_, attrStr, inner) {
    const attrs = parseShortcodeAttrs(attrStr);
    const title = escapeHtml(attrs.title || "POINT");
    const content = formatInlineMarkdown(inner.trim()).replace(/\n/g, "<br>");
    return pushPlaceholder(
      '<div class="article-point-box">' +
        '<div class="article-point-title">💡 ' +
        title +
        "</div>" +
        '<div class="article-point-body">' +
        content +
        "</div>" +
        "</div>"
    );
  });

  text = text.replace(/^:::point\s*([^\n]*)\n([\s\S]*?)^:::\s*$/gm, function (_, titleLine, inner) {
    const title = escapeHtml(titleLine.trim() || "POINT");
    const content = formatInlineMarkdown(inner.trim()).replace(/\n/g, "<br>");
    return pushPlaceholder(
      '<div class="article-point-box">' +
        '<div class="article-point-title">💡 ' +
        title +
        "</div>" +
        '<div class="article-point-body">' +
        content +
        "</div>" +
        "</div>"
    );
  });

  text = text.replace(/\[video([^\]]*)\]/gi, function (_, attrStr) {
    const attrs = parseShortcodeAttrs(attrStr);
    return pushPlaceholder(
      renderVideoEmbedCardHtml(attrs.yt || "", attrs.nc || "", attrs.title || "")
    );
  });

  const lines = text.split("\n");
  const outHtml = [];
  let inList = false;

  const closeListIfNeeded = function () {
    if (inList) {
      outHtml.push("</ul>");
      inList = false;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      closeListIfNeeded();
      continue;
    }

    const tokenMatch = trimmed.match(/^@@__ARTICLE_BLOCK_(\d+)__@@$/);
    if (tokenMatch) {
      closeListIfNeeded();
      outHtml.push(placeholders[parseInt(tokenMatch[1], 10)]);
      continue;
    }

    const quickTalkMatch = trimmed.match(
      /^\[(left\vert{}right):([^:\]]+)(?::([^:\]]+))?(?::(#[0-9A-Fa-f]{3,8}))?\]\s*(.+)$/i
    );
    if (quickTalkMatch) {
      closeListIfNeeded();
      outHtml.push(
        renderTalkBubbleHtml(
          quickTalkMatch[1],
          quickTalkMatch[2],
          quickTalkMatch[3] || "💬",
          quickTalkMatch[4] || "#00d2ff",
          quickTalkMatch[5]
        )
      );
      continue;
    }

    if (trimmed === "---" || trimmed === "***") {
      closeListIfNeeded();
      outHtml.push('<hr class="article-divider" />');
      continue;
    }

    if (trimmed.indexOf("### ") === 0) {
      closeListIfNeeded();
      outHtml.push('<h3 class="article-h3">' + formatInlineMarkdown(trimmed.slice(4)) + "</h3>");
      continue;
    }

    if (trimmed.indexOf("## ") === 0) {
      closeListIfNeeded();
      outHtml.push('<h2 class="article-h2">' + formatInlineMarkdown(trimmed.slice(3)) + "</h2>");
      continue;
    }

    if (trimmed.indexOf("> ") === 0) {
      closeListIfNeeded();
      outHtml.push(
        '<blockquote class="article-quote">' + formatInlineMarkdown(trimmed.slice(2)) + "</blockquote>"
      );
      continue;
    }

    if (trimmed.indexOf("- ") === 0 || trimmed.indexOf("・") === 0) {
      if (!inList) {
        outHtml.push('<ul class="article-ul">');
        inList = true;
      }
      const itemText = trimmed.indexOf("- ") === 0 ? trimmed.slice(2) : trimmed.slice(1);
      outHtml.push("<li>" + formatInlineMarkdown(itemText.trim()) + "</li>");
      continue;
    }

    closeListIfNeeded();
    outHtml.push('<p class="article-p">' + formatInlineMarkdown(trimmed) + "</p>");
  }

  closeListIfNeeded();
  return outHtml.join("\n");
}
