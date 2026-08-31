/* Диаграмма линии в реальном времени.
   Загружается весь период с момента смены ключа продукта (или последние 120
   минут, если задания нет). По умолчанию — окно 10 минут, обновление каждую
   секунду и по SSE-событию. Кнопка «Весь период» показывает весь загруженный
   период.

   Особенности:
   - если за минуту было несколько смен кода продукта, столбец делится на
     цветные сегменты (по одному датасету на продукт в стеке);
   - индикатор «Продукция, шт/мин» показывает ВСЕ цвета/коды продуктов,
     которые видны на выбранном отрезке;
   - простои — минимальные красно-полосатые столбики (1–2 ед.) на каждой
     минуте простоя, над каждым — жёлтый «!»; при наведении — период простоя;
   - при максимальном уменьшении («Весь период») чёрная окантовка столбиков
     убирается, чтобы не чернить график. */
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
  const swatchesEl = $('prodSwatches');

  const FALLBACK_MINUTES = 120; // если задания нет — окно 2 часа
  const DEFAULT_STEP = 0;       // индекс шага в MolvestZoom: 10 минут
  const POLL_MS = 1000;         // обновление раз в секунду (реальное время)
  const DOWN_PERCENT = 0.05;    // высота столбика простоя: 5% от самого
                                // высокого столбца продукции на графике

  let chart = null;
  let zoomApi = null;
  let productsMap = {};
  let fullSeries = [];
  let currentSeries = [];
  let downColumns = [];   // [{idx, text}] — маркеры простоя
  let downTexts = {};     // idx в видимом окне -> текст подсказки
  let downLabels = {};    // idx в видимом окне -> подпись («!»)
  let initialStepDone = false;
  let loading = false;
  let lastAssignment = null;  // последнее задание из API (для строки статуса)
  let lastDownTotal = 0;      // суммарные минуты простоя за период

  const EMPTY_COLOR = '#e9ecef';
  const codeToDs = {};    // код продукта -> индекс датасета в chart.data.datasets

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

  // С секундами — чтобы ряд включал текущую (неполную) минуту
  function toLocalInputSec(dt) {
    const pad = (n) => String(n).padStart(2, '0');
    return dt.getFullYear() + '-' + pad(dt.getMonth() + 1) + '-' + pad(dt.getDate()) +
      'T' + pad(dt.getHours()) + ':' + pad(dt.getMinutes()) + ':' + pad(dt.getSeconds());
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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

  // Строка статуса под графиком:
  //   Код продукта: 005 («Молоко топлёное 4%»). Начало задания 25.08.2026 20:15.
  //   Изготовлено: 6 шт. Время простоя линии : 8 мин.
  function renderStatus() {
    if (!chartStatus) return;
    let text = '';
    const a = lastAssignment;
    if (a) {
      text = 'Код продукта: ' + (a.product_code || '—') +
        ' («' + (a.product_name || '') + '»). ' +
        'Начало задания ' + fmtDT(a.started_at) + '. ' +
        'Изготовлено: ' + Number(a.total_count || 0).toLocaleString('ru-RU') + ' шт. ';
    }
    text += 'Время простоя линии : ' + lastDownTotal + ' мин.';
    chartStatus.textContent = text;
  }

  // ------------------------------------------------------------------
  // Маркеры простоя: на каждую минуту простоя — точка с текстом периода
  // (столбик рисуется минимальной высоты, над ним — жёлтый «!»)
  // ------------------------------------------------------------------
  function buildDownColumns(series, events) {
    const markers = [];
    (events || []).forEach((ev) => {
      const start = new Date(ev.start).getTime();
      const end = new Date(ev.end).getTime();
      const dur = fmtDuration(ev.minutes);
      const text = 'Простой: ' + fmtDT(ev.start) + ' – ' + fmtDT(ev.end) +
        ' · ' + dur;
      for (let i = 0; i < series.length; i++) {
        const ts = new Date(series[i].ts).getTime();
        if (ts >= start && ts < end) {
          markers.push({ idx: i, text: text });
        }
      }
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

  // Части минуты (продукты) для точки ряда; при отсутствии parts —
  // единственный продукт точки
  function partsOf(s) {
    if (s.parts && s.parts.length) return s.parts;
    if (s.product_code) return [{ code: s.product_code, name: s.product_name, count: s.count }];
    return [];
  }

  function tooltipHandler(context) {
    const { chart: ch, tooltip } = context;
    const el = ensureTooltipEl();
    if (!tooltip.dataPoints || !tooltip.dataPoints.length ||
        !Number.isFinite(tooltip.caretX) || !Number.isFinite(tooltip.caretY)) {
      hideTooltip();
      return;
    }
    const idx = tooltip.dataPoints[0].dataIndex;
    const pos = ch.canvas.getBoundingClientRect();
    const px = pos.left + tooltip.caretX;
    const py = pos.top + tooltip.caretY;
    // простои: hover по красно-полосатому столбцу
    if (downTexts[idx]) {
      el.innerHTML = '<div class="tt-body"><div class="tt-noimg"><span class="badge text-bg-danger">↓</span></div>' +
        '<div class="tt-text"><div class="tt-count text-danger">Простой</div>' +
        '<div class="tt-1c">' + downTexts[idx] + '</div></div></div>';
      placeTooltip(el, px, py);
      return;
    }
    const s = currentSeries[idx];
    if (!s) { hideTooltip(); return; }
    const parts = partsOf(s);
    if (!parts.length && s.count === undefined) { hideTooltip(); return; }
    const totalHtml = '<div class="tt-count">' + Number(s.count || 0).toLocaleString('ru-RU') + ' шт.</div>';
    const timeHtml = '<div class="tt-time">' + fmtTs(s.ts) + '</div>';
    if (parts.length > 1) {
      // Несколько продуктов в одной минуте: общее кол-во, ниже дата/время,
      // ниже — по каждому продукту цветной код (цвет продукта) и его кол-во
      const rows = parts.map((p) => {
        const prod = productsMap[p.code] || null;
        return '<div class="tt-part">' +
          '<span class="product-chip" style="background:' + ((prod && prod.color) || '#6c757d') + '">' + p.code + '</span>' +
          '<span class="tt-part-count">' + Number(p.count || 0).toLocaleString('ru-RU') + ' шт.</span>' +
          '</div>';
      }).join('');
      el.innerHTML = '<div class="tt-body tt-body-col">' +
        '<div class="tt-text">' + totalHtml + timeHtml +
        '<div class="tt-parts">' + rows + '</div></div></div>';
      placeTooltip(el, px, py);
      return;
    }
    const p = parts[0] ? (productsMap[parts[0].code] || null) : null;
    const code = parts[0] ? parts[0].code : s.product_code;
    let imgHtml;
    if (p && p.image) {
      imgHtml = '<img class="tt-img" src="' + p.image + '" alt="">';
    } else if (code) {
      imgHtml = '<div class="tt-noimg"><span class="badge text-bg-dark">' + code + '</span></div>';
    } else {
      imgHtml = '<div class="tt-noimg"><span class="badge text-bg-secondary">—</span></div>';
    }
    const nameHtml = p ? '<div class="tt-name">' + escapeHtml(p.name) + '</div>'
                       : '<div class="tt-name text-muted">нет данных о продукте</div>';
    const codeHtml = code ? '<div class="tt-1c">Код продукта: ' + code + '</div>' : '';
    const code1cHtml = p ? '<div class="tt-1c">Код 1С: ' + escapeHtml(p.code_1c || '—') + '</div>' : '';
    el.innerHTML = '<div class="tt-body">' + imgHtml +
      '<div class="tt-text">' + totalHtml + timeHtml + nameHtml + codeHtml + code1cHtml + '</div></div>';
    placeTooltip(el, px, py);
  }

  // ------------------------------------------------------------------
  // Индикатор «Продукция, шт/мин»: ВСЕ цвета и коды продуктов,
  // видимые на выбранном отрезке (2, 3, 4 цвета — все отображаются)
  // ------------------------------------------------------------------
  function updateProductIndicator() {
    try {
      if (!swatchesEl) return;
      const seen = new Map();
      currentSeries.forEach((s) => {
        partsOf(s).forEach((p) => {
          if (!p || !p.code || seen.has(p.code)) return;
          const prod = productsMap[p.code] || null;
          seen.set(p.code, {
            color: (prod && prod.color) ? prod.color : '#adb5bd',
            name: (prod && prod.name) || p.name || '',
          });
        });
      });
      const codes = Array.from(seen.keys())
        .sort((a, b) => (parseInt(a, 10) || 0) - (parseInt(b, 10) || 0) || a.localeCompare(b));
      swatchesEl.innerHTML = codes.length
        ? codes.map((code) =>
            '<span class="prod-legend-swatch" data-code="' + code + '" title="' +
            escapeHtml(seen.get(code).name || code) + '" style="background:' +
            seen.get(code).color + '">' + code + '</span>'
          ).join('')
        : '<span class="prod-legend-swatch" style="background:#adb5bd">—</span>';
      // подсказка при наведении на каждый чип
      Array.prototype.forEach.call(swatchesEl.querySelectorAll('.prod-legend-swatch'), (chip) => {
        chip.addEventListener('mouseenter', () => showProductTip(chip.dataset.code));
        chip.addEventListener('mouseleave', hideProductTip);
      });
    } catch (e) {
      // индикатор декоративный — сбой не должен ломать отрисовку графика
    }
  }

  function hideProductTip() {
    hideTooltip();
  }

  function showProductTip(code) {
    if (!code) return;
    const p = productsMap[code] || null;
    if (!p) return;
    const el = ensureTooltipEl();
    let imgHtml;
    if (p.image) {
      imgHtml = '<img class="tt-img" src="' + p.image + '" alt="">';
    } else {
      imgHtml = '<div class="tt-noimg"><span class="product-chip" style="background:' + (p.color || '#adb5bd') + '">' + code + '</span></div>';
    }
    el.innerHTML = '<div class="tt-body">' + imgHtml +
      '<div class="tt-text">' +
      '<div class="tt-count">Продукт ' + code + '</div>' +
      '<div class="tt-name">' + escapeHtml(p.name) + '</div>' +
      '<div class="tt-1c">Код 1С: ' + escapeHtml(p.code_1c || '—') + '</div>' +
      '<div class="tt-1c">Цвет: <span style="color:' + (p.color || '#fff') + '">' + (p.color || '—') + '</span></div>' +
      '</div></div>';
    const chip = swatchesEl ? swatchesEl.querySelector('.prod-legend-swatch[data-code="' + code + '"]') : null;
    const pos = chip ? chip.getBoundingClientRect() : { left: 0, top: 0 };
    placeTooltip(el, pos.left, pos.top);
  }

  // ------------------------------------------------------------------
  // Датасеты: по одному на продукт (стек) + датасет простоя (последний)
  // ------------------------------------------------------------------
  function downDsIndex() {
    if (!chart) return -1;
    for (let i = 0; i < chart.data.datasets.length; i++) {
      if (chart.data.datasets[i]._down) return i;
    }
    return -1;
  }

  // Толщина чёрной окантовки столбцов: в оконном режиме — 1px, при
  // максимальном уменьшении («Весь период») — 0 (чтобы не чернить график).
  function barBorderWidth(ctx) {
    const z = ctx && ctx.chart && ctx.chart._molvestZoom;
    return z && z.isFullPeriod() ? 0 : 1;
  }

  function syncProductDatasets() {
    if (!chart) return;
    const codes = new Set();
    fullSeries.forEach((s) => {
      partsOf(s).forEach((p) => { if (p && p.code) codes.add(p.code); });
    });
    // удаляем датасеты продуктов, которых больше нет
    chart.data.datasets = chart.data.datasets.filter((ds) => {
      if (ds._down) return true;
      if (ds._code && codes.has(ds._code)) return true;
      delete codeToDs[ds._code];
      return false;
    });
    // добавляем новые (перед датасетом простоя)
    let insertIdx = downDsIndex();
    if (insertIdx === -1) insertIdx = chart.data.datasets.length;
    const sorted = Array.from(codes)
      .sort((a, b) => (parseInt(a, 10) || 0) - (parseInt(b, 10) || 0) || a.localeCompare(b));
    sorted.forEach((code) => {
      if (code in codeToDs) return;
      const p = productsMap[code] || null;
      const ds = {
        label: 'Продукт ' + code,
        _code: code,
        data: [],
        backgroundColor: (p && p.color) ? p.color : EMPTY_COLOR,
        borderWidth: barBorderWidth,
        borderColor: 'rgba(0,0,0,0.75)',
        borderRadius: 0,
        barPercentage: 1.0,
        categoryPercentage: 1.0,
        stack: 'main',
      };
      chart.data.datasets.splice(insertIdx, 0, ds);
      insertIdx += 1;
    });
    // пересчёт индексов
    Object.keys(codeToDs).forEach((k) => delete codeToDs[k]);
    chart.data.datasets.forEach((ds, i) => {
      if (!ds._down && ds._code) codeToDs[ds._code] = i;
    });
  }

  // ------------------------------------------------------------------
  // Отрисовка видимого окна
  // ------------------------------------------------------------------
  function renderVisible() {
    if (!chart) return;
    const w = zoomApi ? zoomApi.getWindow() : { min: 0, max: Math.max(0, fullSeries.length - 1) };
    const slice = fullSeries.slice(w.min, w.max + 1);
    currentSeries = slice;
    const maxCount = fullSeries.reduce((mx, s) => Math.max(mx, s.count || 0), 0) || 1;

    // Запас по оси Y: максимум + 40% сверху (самый высокий столбец — ~71% высоты)
    chart.options.scales.y.max = window.Molvest3D
      ? Molvest3D.yAxisMax(maxCount)
      : Math.max(1, Math.ceil(maxCount * 1.4));

    // Данные простоя: столбики высотой 5% от максимального столбца продукции
    // на каждой минуте простоя; над каждым — жёлтый «!»; при наведении —
    // период простоя
    const downValue = Math.max(1, Math.round(maxCount * DOWN_PERCENT));
    const downData = new Array(slice.length).fill(0);
    downTexts = {};
    downLabels = {};
    const downOn = !document.getElementById('downToggle') ||
      document.getElementById('downToggle').checked;
    if (downOn) {
      downColumns.forEach((c) => {
        const local = c.idx - w.min;
        if (local >= 0 && local < slice.length) {
          downData[local] = downValue;
          downTexts[local] = c.text;
          downLabels[local] = '!';
        }
      });
    }

    // Данные по продуктам (сегменты одного столбца)
    Object.keys(codeToDs).forEach((code) => {
      const ds = chart.data.datasets[codeToDs[code]];
      if (!ds) return;
      ds.data = slice.map((s) => {
        const parts = s.parts || [];
        for (let i = 0; i < parts.length; i++) {
          if (parts[i].code === code) return parts[i].count || 0;
        }
        return 0;
      });
    });

    chart.data.labels = slice.map((s) => s.minute);
    const di = downDsIndex();
    if (di !== -1) {
      chart.data.datasets[di].data = downData;
      chart.data.datasets[di].backgroundColor = stripesPattern;
    }
    chart.update('none');
    updateProductIndicator();
    renderStatus();
  }

  function createChart() {
    const ctx = $('lineChart').getContext('2d');
    chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: [],
        datasets: [
          // датасеты продуктов добавляются динамически (syncProductDatasets);
          // датасет простоя всегда последний
          { label: 'Простой', data: [], _down: true, backgroundColor: stripesPattern,
            borderWidth: barBorderWidth, borderColor: 'rgba(0,0,0,0.75)', borderRadius: 0,
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
          // 2D-столбцы: 3D-эффект отключён (enabled: false) — плоские
          // непрозрачные столбцы цветом продукта, без «прозрачности»
          molvest3d: { enabled: false, depth: 9, outline: false },
          // Жёлтый «!» над каждым столбиком простоя
          datalabels: {
            display: (ctx) => ctx.datasetIndex === downDsIndex() && !!downLabels[ctx.dataIndex],
            color: '#ffc107',
            textStrokeColor: 'rgba(0,0,0,0.85)',
            textStrokeWidth: 1.5,
            anchor: 'end',
            align: 'end',
            offset: 1,
            font: { weight: 'bold', size: 12 },
            formatter: (value, ctx) => downLabels[ctx.dataIndex] || '',
          },
        },
        scales: {
          x: {
            stacked: true,
            grid: { display: false },
            ticks: { maxTicksLimit: 14, maxRotation: 0, autoSkip: true },
          },
          y: {
            stacked: true,
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

  async function loadChart() {
    if (loading) return; // не запускаем повторный запрос, пока идёт текущий
    loading = true;
    try {
      const to = new Date();
      let from;
      if (assignmentStartRaw) {
        from = new Date(assignmentStartRaw);
        if (isNaN(from.getTime())) from = new Date(to.getTime() - FALLBACK_MINUTES * 60000);
      } else {
        from = new Date(to.getTime() - FALLBACK_MINUTES * 60000);
      }
      const url = '/api/v1/lines/' + lineId + '/chart/?from=' + encodeURIComponent(toLocalInput(from)) +
        '&to=' + encodeURIComponent(toLocalInputSec(to));
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

      if (!chart) createChart();
      syncProductDatasets();

      if (zoomApi) zoomApi.setData(fullSeries.length);
      if (!initialStepDone && zoomApi && fullSeries.length > 0) {
        zoomApi.setStep(DEFAULT_STEP);
        initialStepDone = true;
      }
      renderVisible(); // при первой загрузке тоже обновляем индикатор

      renderSummary(data.summary);
      lastAssignment = data.assignment || null;
      lastDownTotal = (data.downtime || []).reduce((s, e) => s + (e.minutes || 0), 0);
      renderStatus();
    } catch (e) {
      chartStatus.textContent = 'Ошибка загрузки данных: ' + e.message;
    } finally {
      loading = false;
    }
  }

  // ------------------------------------------------------------------
  // Реальное время: SSE + опрос раз в секунду
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

  setInterval(loadChart, POLL_MS);

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
