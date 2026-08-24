/* Диаграмма линии в реальном времени.
   Загружается весь период с момента смены ключа продукта (или последние 120
   минут, если задания нет). По умолчанию — окно 10 минут, обновление каждую
   минуту и по SSE-событию. Кнопка «Весь период» показывает весь загруженный
   период. Простои отображаются одним красно-чёрным столбцом на минуте
   возобновления фасовки; при наведении — диалог с периодом простоя. */
(function () {
  'use strict';

  if (window.ChartDataLabels && window.Chart) {
    window.Chart.register(window.ChartDataLabels);
  }
  // Регистрируем 3D-плагин (иначе ни 3D-столбцы, ни чёрная окантовка не рисуются)
  if (window.Molvest3D && window.Molvest3D.plugin && window.Chart) {
    window.Chart.register(window.Molvest3D.plugin);
  }

  const $ = (id) => document.getElementById(id);

  const lineId = JSON.parse($('lineId').textContent);
  const assignmentStartRaw = JSON.parse($('assignmentStart').textContent);

  const rangeTotal = $('rangeTotal');
  const summaryBody = $('summaryBody');
  const chartStatus = $('chartStatus');

  const FALLBACK_MINUTES = 120; // если задания нет — окно 2 часа
  const DEFAULT_STEP = 0;       // индекс шага в MolvestZoom: 10 минут

  let chart = null;
  let zoomApi = null;
  let productsMap = {};
  let fullSeries = [];
  let currentSeries = [];
  let downColumns = [];   // [{idx, label, text}] — маркеры простоя
  let downTexts = {};     // idx в видимом окне -> текст подсказки
  let downLabels = {};    // idx в видимом окне -> подпись («!» или итог простоя)
  let initialStepDone = false;

  const EMPTY_COLOR = '#e9ecef';

  // Паттерн «красный с чёрными полосками» для столбцов простоя
  const _patternCanvas = document.createElement('canvas');
  _patternCanvas.width = 8;
  _patternCanvas.height = 8;
  const _pctx = _patternCanvas.getContext('2d');
  _pctx.fillStyle = '#dc3545';
  _pctx.fillRect(0, 0, 8, 8);
  _pctx.strokeStyle = 'rgba(0, 0, 0, 0.55)';
  _pctx.lineWidth = 2;
  _pctx.beginPath();
  _pctx.moveTo(0, 8);
  _pctx.lineTo(8, 0);
  _pctx.stroke();
  const stripesPattern = _pctx.createPattern(_patternCanvas, 'repeat');

  function fmtTs(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear() +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

  function fmtDT(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    const pad = (n) => String(n).padStart(2, '0');
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear() +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  // Длительность: 45 -> '45 минут', 75 -> '1 час 15 минут'
  function fmtDuration(minutes) {
    const m = Math.round(minutes || 0);
    const h = Math.floor(m / 60);
    const mm = m % 60;
    function plural(n, one, few, many) {
      const n10 = n % 10, n100 = n % 100;
      if (n10 === 1 && n100 !== 11) return one;
      if (n10 >= 2 && n10 <= 4 && !(n100 >= 12 && n100 <= 14)) return few;
      return many;
    }
    if (h === 0) return mm + ' ' + plural(mm, 'минута', 'минуты', 'минут');
    if (mm === 0) return h + ' ' + plural(h, 'час', 'часа', 'часов');
    return h + ' ' + plural(h, 'час', 'часа', 'часов') + ' ' +
      mm + ' ' + plural(mm, 'минута', 'минуты', 'минут');
  }

  function toLocalInput(dt) {
    const pad = (n) => String(n).padStart(2, '0');
    return dt.getFullYear() + '-' + pad(dt.getMonth() + 1) + '-' + pad(dt.getDate()) +
      'T' + pad(dt.getHours()) + ':' + pad(dt.getMinutes());
  }

  function renderSummary(summary) {
    rangeTotal.textContent = 'Всего за период: ' + (summary.total || 0).toLocaleString('ru-RU') + ' шт.';
    if (!summary.per_product || !summary.per_product.length) {
      summaryBody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-3">Нет данных</td></tr>';
      return;
    }
    summaryBody.innerHTML = summary.per_product.map((p) =>
      '<tr><td><span class="product-chip" style="background:' + ((productsMap[p.code] || {}).color || '#6c757d') + '">' + p.code + '</span></td>' +
      '<td>' + p.name + '</td>' +
      '<td class="text-end fw-semibold">' + Number(p.count).toLocaleString('ru-RU') + '</td></tr>'
    ).join('');
  }

  // ------------------------------------------------------------------
  // Маркеры простоя: на каждую минуту простоя — жёлтый «!», на последней
  // минуте события — общее время простоя.
  // ------------------------------------------------------------------
  function buildDownColumns(series, events) {
    const markers = [];
    (events || []).forEach((ev) => {
      const start = new Date(ev.start).getTime();
      const end = new Date(ev.end).getTime();
      const dur = fmtDuration(ev.minutes);
      const text = 'Простой: ' + fmtDT(ev.start) + ' – ' + fmtDT(ev.end) +
        ' · ' + dur;
      const idxs = [];
      for (let i = 0; i < series.length; i++) {
        const ts = new Date(series[i].ts).getTime();
        if (ts >= start && ts < end) idxs.push(i);
      }
      if (!idxs.length) return;
      idxs.forEach((idx, j) => {
        markers.push({
          idx: idx,
          label: (j === idxs.length - 1) ? dur : '!',
          text: text,
        });
      });
    });
    return markers;
  }

  // ------------------------------------------------------------------
  // Всплывающая подсказка (диалог)
  // ------------------------------------------------------------------
  function ensureTooltipEl() {
    let el = document.getElementById('chart-tooltip');
    if (!el) {
      el = document.createElement('div');
      el.id = 'chart-tooltip';
      document.body.appendChild(el);
    }
    return el;
  }

  function hideTooltip() {
    const el = document.getElementById('chart-tooltip');
    if (el) el.style.opacity = '0';
  }

  // Позиция подсказки с ограничением по границам окна: подсказка никогда
  // не выходит за пределы страницы (не обрезается справа/снизу).
  function placeTooltip(el, x, y) {
    const r = el.getBoundingClientRect();
    const pad = 10;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let tx = x + 16;
    let ty = y - 14;
    // не хватает места справа — показываем слева от курсора
    if (tx + r.width > vw - pad) tx = x - r.width - 16;
    if (tx < pad) tx = pad;
    if (ty + r.height > vh - pad) ty = vh - r.height - pad;
    if (ty < pad) ty = pad;
    el.style.transform = 'translate(' + Math.round(tx) + 'px,' + Math.round(ty) + 'px)';
    el.style.opacity = '1';
  }

  function tooltipHandler(context) {
    const { chart: ch, tooltip } = context;
    const el = ensureTooltipEl();
    // Не полагаемся на tooltip.opacity (при animation:false он может не меняться):
    // показываем, когда есть активные точки и позиция курсора
    if (!tooltip.dataPoints || !tooltip.dataPoints.length ||
        !Number.isFinite(tooltip.caretX) || !Number.isFinite(tooltip.caretY)) {
      hideTooltip();
      return;
    }
    const idx = tooltip.dataPoints[0].dataIndex;
    const pos = ch.canvas.getBoundingClientRect();
    const px = pos.left + tooltip.caretX;
    const py = pos.top + tooltip.caretY;
    // простои: hover по красно-чёрному столбцу
    if (downTexts[idx]) {
      el.innerHTML = '<div class="tt-body"><div class="tt-noimg"><span class="badge text-bg-danger">↓</span></div>' +
        '<div class="tt-text"><div class="tt-count text-danger">Простой</div>' +
        '<div class="tt-1c">' + downTexts[idx] + '</div></div></div>';
      placeTooltip(el, px, py);
      return;
    }
    const s = currentSeries[idx];
    if (!s) { hideTooltip(); return; }
    if (s.count === undefined && !s.product_code) { hideTooltip(); return; }
    const p = s.product_code ? (productsMap[s.product_code] || null) : null;
    const countHtml = '<div class="tt-count">' + Number(s.count).toLocaleString('ru-RU') + ' шт.</div>';
    const timeHtml = '<div class="tt-time">' + fmtTs(s.ts) + '</div>';
    let imgHtml;
    if (p && p.image) {
      imgHtml = '<img class="tt-img" src="' + p.image + '" alt="">';
    } else if (p) {
      imgHtml = '<div class="tt-noimg"><span class="badge text-bg-dark">' + (s.product_code || '—') + '</span></div>';
    } else {
      imgHtml = '<div class="tt-noimg"><span class="badge text-bg-secondary">—</span></div>';
    }
    const nameHtml = p ? '<div class="tt-name">' + p.name + '</div>' : '<div class="tt-name text-muted">нет данных о продукте</div>';
    const codeHtml = s.product_code ? '<div class="tt-1c">Код продукта: ' + s.product_code + '</div>' : '';
    const code1cHtml = p ? '<div class="tt-1c">Код 1С: ' + (p.code_1c || '—') + '</div>' : '';
    el.innerHTML = '<div class="tt-body">' + imgHtml +
      '<div class="tt-text">' + countHtml + timeHtml + nameHtml + codeHtml + code1cHtml + '</div></div>';
    placeTooltip(el, px, py);
  }

  // ------------------------------------------------------------------
  // Отрисовка видимого окна
  // ------------------------------------------------------------------
  // Доминирующий продукт в видимом окне (по сумме кол-ва за минуты)
  function dominantProduct(slice) {
    const sums = {};
    slice.forEach((s) => {
      if (s.product_code) sums[s.product_code] = (sums[s.product_code] || 0) + (s.count || 0);
    });
    let best = null;
    let bestSum = -1;
    Object.keys(sums).forEach((code) => {
      if (sums[code] > bestSum) { best = code; bestSum = sums[code]; }
    });
    return best;
  }

  // Индикатор «Продукция, шт/мин»: цвет и код продукта в поле зрения по оси X
  const prodSwatch = $('prodLegendSwatch');
  let dominantCode = null;

  function updateProductIndicator() {
    if (!prodSwatch) return;
    dominantCode = dominantProduct(currentSeries);
    if (dominantCode) {
      const p = productsMap[dominantCode] || null;
      prodSwatch.style.background = (p && p.color) ? p.color : '#adb5bd';
      prodSwatch.textContent = dominantCode;
    } else {
      prodSwatch.style.background = '#adb5bd';
      prodSwatch.textContent = '—';
    }
  }

  function showProductTip(ev) {
    if (!dominantCode) return;
    const p = productsMap[dominantCode] || null;
    if (!p) return;
    const el = ensureTooltipEl();
    let imgHtml;
    if (p.image) {
      imgHtml = '<img class="tt-img" src="' + p.image + '" alt="">';
    } else {
      imgHtml = '<div class="tt-noimg"><span class="product-chip" style="background:' + (p.color || '#adb5bd') + '">' + dominantCode + '</span></div>';
    }
    el.innerHTML = '<div class="tt-body">' + imgHtml +
      '<div class="tt-text">' +
      '<div class="tt-count">Продукт ' + dominantCode + '</div>' +
      '<div class="tt-name">' + p.name + '</div>' +
      '<div class="tt-1c">Код 1С: ' + (p.code_1c || '—') + '</div>' +
      '<div class="tt-1c">Цвет: <span style="color:' + (p.color || '#fff') + '">' + (p.color || '—') + '</span></div>' +
      '</div></div>';
    const pos = prodSwatch.getBoundingClientRect();
    placeTooltip(el, pos.left, pos.top);
  }

  function hideProductTip() {
    const el = document.getElementById('chart-tooltip');
    if (el) el.style.opacity = '0';
  }

  if (prodSwatch) {
    prodSwatch.addEventListener('mouseenter', showProductTip);
    prodSwatch.addEventListener('mouseleave', hideProductTip);
  }

  function renderVisible() {
    if (!chart) return;
    const w = zoomApi ? zoomApi.getWindow() : { min: 0, max: Math.max(0, fullSeries.length - 1) };
    const slice = fullSeries.slice(w.min, w.max + 1);
    currentSeries = slice;
    const maxCount = fullSeries.reduce((mx, s) => Math.max(mx, s.count || 0), 0) || 1;

    // Запас по оси Y: максимум + 20% сверху (самый высокий столбец — ~80% высоты)
    chart.options.scales.y.max = window.Molvest3D
      ? Molvest3D.yAxisMax(maxCount)
      : Math.max(1, Math.ceil(maxCount * 1.4));

    // данные простоя для видимого окна: жёлтый маркер на каждую минуту
    const downData = new Array(slice.length).fill(0);
    downTexts = {};
    downLabels = {};
    const downOn = !document.getElementById('downToggle') ||
      document.getElementById('downToggle').checked;
    if (downOn) {
      downColumns.forEach((c) => {
        const local = c.idx - w.min;
        if (local >= 0 && local < slice.length) {
          downData[local] = maxCount;
          downTexts[local] = c.text;
          downLabels[local] = c.label;
        }
      });
    }
    // Даже при выключенном простоях датасет остаётся (нули) — ширина столбцов
    // продукции не меняется (нет перерасчёта раскладки)

    chart.data.labels = slice.map((s) => s.minute);
    chart.data.datasets[0].data = slice.map((s) => s.count);
    chart.data.datasets[0].backgroundColor = slice.map((s) => {
      const p = s.product_code ? productsMap[s.product_code] : null;
      return p && p.color ? p.color : EMPTY_COLOR;
    });
    chart.data.datasets[1].data = downData;
    chart.update('none');
    updateProductIndicator();
    chartStatus.textContent = 'Обновлено: ' + new Date().toLocaleTimeString('ru-RU') +
      ' · Простоев: ' + downColumns.length;
  }

  async function loadChart() {
    const to = new Date();
    let from;
    if (assignmentStartRaw) {
      from = new Date(assignmentStartRaw);
      if (isNaN(from.getTime())) from = new Date(to.getTime() - FALLBACK_MINUTES * 60000);
    } else {
      from = new Date(to.getTime() - FALLBACK_MINUTES * 60000);
    }
    const url = '/api/v1/lines/' + lineId + '/chart/?from=' + encodeURIComponent(toLocalInput(from)) +
      '&to=' + encodeURIComponent(toLocalInput(to));
    try {
      const resp = await fetch(url, { headers: { 'Accept': 'application/json' } });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        chartStatus.textContent = 'Ошибка: ' + (err.error || resp.status);
        return;
      }
      const data = await resp.json();
      fullSeries = data.series || [];
      productsMap = data.products || {};
      downColumns = buildDownColumns(fullSeries, data.downtime || []);

      if (!chart) {
        const ctx = $('lineChart').getContext('2d');
        chart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels: [],
            datasets: [
              { label: 'Продукция, шт/мин', data: [], backgroundColor: [], borderWidth: 0, borderRadius: 0,
                barPercentage: 1.0, categoryPercentage: 1.0, stack: 'main' },
              { label: 'Простой', data: [], backgroundColor: '#ffc107', borderWidth: 1, borderColor: 'rgba(0,0,0,0.7)', borderRadius: 0,
                barPercentage: 1.0, categoryPercentage: 1.0, stack: 'main', molvest3d: false },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
              // Легенда скрыта: вместо неё — чекбокс «Отображать график простоя»
              legend: { display: false },
              tooltip: { enabled: false, external: tooltipHandler },
              // 3D-столбцы (только для продукции; простой — плоские жёлтые маркеры)
              molvest3d: { enabled: true, depth: 9 },
              // Жёлтый «!» на каждой минуте простоя; итог — на последней минуте
              datalabels: {
                display: (ctx) => ctx.datasetIndex === 1 && !!downLabels[ctx.dataIndex],
                color: '#6b4e00',
                anchor: 'end',
                align: 'end',
                offset: -1,
                font: { weight: 'bold', size: 9 },
                formatter: (value, ctx) => downLabels[ctx.dataIndex] || '',
              },
            },
            scales: {
              x: {
                grid: { display: false },
                ticks: { maxTicksLimit: 14, maxRotation: 0, autoSkip: true },
              },
              y: {
                beginAtZero: true,
                ticks: { precision: 0 },
                title: { display: true, text: 'шт./мин' },
              },
            },
          },
        });
        if (window.MolvestZoom) {
          zoomApi = MolvestZoom.attach(chart, {
            container: $('lineChartZoom'),
            onWindow: () => renderVisible(),
          });
        }
        // курсор ушёл с холста — подсказка скрывается
        chart.canvas.addEventListener('mouseleave', hideTooltip);
      }

      if (zoomApi) zoomApi.setData(fullSeries.length);
      if (!initialStepDone && zoomApi && fullSeries.length > 0) {
        zoomApi.setStep(DEFAULT_STEP);
        initialStepDone = true;
      }
      renderVisible(); // при первой загрузке тоже обновляем индикатор

      renderSummary(data.summary);
      const a = data.assignment;
      let status = '';
      if (a) {
        status = 'Задание: продукт ' + a.product_code + ' («' + a.product_name + '»), с ' + a.started_at +
          ', изготовлено ' + a.total_count + ' шт. · ';
      }
      chartStatus.textContent = status + 'Обновлено: ' + new Date().toLocaleTimeString('ru-RU') +
        ' · Простоев: ' + downColumns.length;
    } catch (e) {
      chartStatus.textContent = 'Ошибка загрузки данных: ' + e.message;
    }
  }

  // ------------------------------------------------------------------
  // Реальное время: SSE + опрос раз в минуту
  // ------------------------------------------------------------------
  function connectEvents() {
    let es;
    try {
      es = new EventSource('/api/v1/events/');
    } catch (e) {
      return;
    }
    es.addEventListener('line_update', (ev) => {
      try {
        const d = JSON.parse(ev.data);
        if (d && d.line_id === lineId) loadChart();
      } catch (e) { /* ignore */ }
    });
    es.onerror = () => {
      try { es.close(); } catch (e) { /* ignore */ }
      setTimeout(connectEvents, 5000);
    };
  }

  setInterval(loadChart, 60000);

  // Переключатель «Отображать график простоя» — перерисовка без изменения
  // ширины столбцов (датасет простоя остаётся в раскладке)
  const downToggle = document.getElementById('downToggle');
  if (downToggle) {
    downToggle.addEventListener('change', () => {
      if (chart) renderVisible();
    });
  }

  loadChart();
  connectEvents();
})();