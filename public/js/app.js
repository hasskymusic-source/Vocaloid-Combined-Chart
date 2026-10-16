// public/js/app.js
let currentChartData = null;

async function initApp() {
  try {
    // 1. 過去アーカイブ一覧を読み込んでプルダウンを生成
    const indexRes = await fetch('./data/archive_index.json');
    if (indexRes.ok) {
      const archiveList = await indexRes.json();
      renderArchiveSelector(archiveList);
    }

    // 2. 最新ランキングJSONを読み込んで描画
    await loadChartData('./data/latest_ranking.json');
  } catch (err) {
    console.error('データの読み込みに失敗しました:', err);
  }
}

async function loadChartData(jsonPath) {
  const res = await fetch(jsonPath);
  currentChartData = await res.json();
  renderChart(currentChartData);
}

function renderArchiveSelector(archiveList) {
  const select = document.getElementById('archive-select');
  if (!select) return;
  select.innerHTML = archiveList.map((item, idx) =>
    `<option value="${idx === 0 ? './data/latest_ranking.json' : `./data/archives/${item.archiveId}.json`}">
      ${item.label}
    </option>`
  ).join('');

  select.addEventListener('change', (e) => {
    loadChartData(e.target.value);
  });
}

// 以降は currentChartData.songs をループして DOM を生成（前回の renderChart 関数と同様）
document.addEventListener('DOMContentLoaded', initApp);