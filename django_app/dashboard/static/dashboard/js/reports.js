/* Вкладка «Отчёты»: несколько независимых блоков отчётов для сравнения.
   Каждый блок — свой счётчик, вкладка, тип и период. Кнопка «Формировать»
   строит таблицы + график через Ajax (fetch); «Добавить отчет для сравнения»
   добавляет ещё один блок (максимум 8); «Выгрузить отчёты» — все
   сформированные отчёты в один файл (в Excel — отдельный лист на отчёт). */
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
  const MAX_REPORTS = 8;
  const EXPORT_FILE = { xlsx: 'reports_comparison.xlsx', csv: 'reports_comparison.csv' };

  const counters = JSON.parse($('countersJson').textContent);
  const counterById = {};
  counters.forEach((c) => { counterById[c.id] = c; });

  const blocksContainer = $('reportBlocks');
  const blockTemplate = $('reportBlockTemplate');
  const btnAddReport = $('btnAddReport');
  const addReportError = $('addReportError');

  let blocks = [];

  // Паттерн «красный с чёрными полосками» для столбцов простоя (общий для всех блоков)
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

  function getCookie(name) {
    const m = document.cookie.match('(^|;)\\s*' + name + '=([^;]*)');
    return m ? decodeURIComponent(m[2]) : '';
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fmtLocalInput(dt) {
    const pad = (n) => String(n).padStart(2, '0');
    return dt.getFullYear() + '-' + pad(dt.getMonth() + 1) + '-' + pad(dt.getDate()) +
      'T' + pad(dt.getHours()) + ':' + pad(dt.getMinutes());
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

  // Счётчик по значению select: в режиме БД это число (pk), в режиме DBF —
  // строка-код (например '2044'). Пробуем оба варианта ключа.
  function counterInfo(value) {
    return counterById[value] || counterById[parseInt(value, 10)];
  }

  // Маркеры простоя на минутном графике: каждая минута простоя — столбик;
  // подпись (общее время простоя) — только на последней минуте события,
  // при наведении на любой столбик — период простоя.
  function buildDownColumns(minuteTs, events, seriesData) {
    const markers = [];
    (events || []).forEach((ev) => {
      const start = new Date(ev.start).getTime();
      const end = new Date(ev.end).getTime();
      const dur = fmtDuration(ev.minutes);
      const text = 'Простой: ' + fmtDT(ev.start) + ' – ' + fmtDT(ev.end) +
        ' · ' + dur;
      const idxs = [];
      for (let i = 0; i < minuteTs.length; i++) {
        const ts = new Date(minuteTs[i]).getTime();
        if (ts >= start && ts < end) idxs.push(i);
      }
      idxs.forEach((idx, j) => {
        // подпись — только на последнем столбце события (общее время простоя)
        markers.push({ idx: idx, text: text, label: (j === idxs.length - 1) ? dur : '' });
      });
    });
    return markers;
  }

  // --- Общий тултип графика (один на страницу) ---
  function ensureReportTooltip() {
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

  function placeTooltip(el, x, y) {
    const r = el.getBoundingClientRect();
    const pad = 10;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let tx = x + 16;
    let ty = y - 14;
    if (tx + r.width > vw - pad) tx = x - r.width - 16;
    if (tx < pad) tx = pad;
    if (ty + r.height > vh - pad) ty = vh - r.height - pad;
    if (ty < pad) ty = pad;
    el.style.transform = 'translate(' + Math.round(tx) + 'px,' + Math.round(ty) + 'px)';
    el.style.opacity = '1';
  }

  // Обработчик тултипа для конкретного блока (использует его видимые данные)
  function makeTooltipHandler(st) {
    return function reportTooltipHandler(context) {
      const { chart: ch, tooltip } = context;
      const el = ensureReportTooltip();
      if (!tooltip.dataPoints || !tooltip.dataPoints.length ||
          !Number.isFinite(tooltip.caretX) || !Number.isFinite(tooltip.caretY)) {
        hideTooltip();
        return;
      }
      const dp = tooltip.dataPoints[0];
      const idx = dp.dataIndex;
      const pos = ch.canvas.getBoundingClientRect();
      const px = pos.left + tooltip.caretX;
      const py = pos.top + tooltip.caretY;
      // столбец простоя (красно-полосатый, датасет последний): показываем
      // «Простой» и точный период; ищем его среди всех точек наведения
      let isDown = false;
      for (let k = 0; k < tooltip.dataPoints.length; k++) {
        if (tooltip.dataPoints[k].datasetIndex === st.downIdx()) { isDown = true; break; }
      }
      if (isDown) {
        const val = dp.parsed.y || 0;
        const text = st.downTexts[idx] || ('Простой: ' + fmtDuration(val));
        el.innerHTML = '<div class="tt-body"><div class="tt-noimg"><span class="badge text-bg-danger">↓</span></div>' +
          '<div class="tt-text"><div class="tt-count text-danger">Простой</div>' +
          '<div class="tt-1c">' + text + '</div></div></div>';
        placeTooltip(el, px, py);
        return;
      }
      const d = st.visibleDetails[idx] || null;
      const parts = (st.visibleParts && st.visibleParts[idx]) || [];
      const value = dp.parsed.y;
      const label = st.visibleLabels[idx] || '';
      if (parts.length > 1) {
        // Несколько продуктов в одной минуте: общее кол-во, ниже дата/время,
        // ниже — по каждому продукту цветной код (цвет продукта) и его кол-во
        const rows = parts.map((p) => {
          const pp = st.productsMap && st.productsMap[p.code] ? st.productsMap[p.code] : null;
          return '<div class="tt-part">' +
            '<span class="product-chip" style="background:' + ((pp && pp.color) || '#6c757d') + '">' + p.code + '</span>' +
            '<span class="tt-part-count">' + Number(p.count || 0).toLocaleString('ru-RU') + ' шт.</span>' +
            '</div>';
        }).join('');
        // дата и время минуты (для минутных графиков — полная дата)
        const dts = (d && d.ts) || '';
        const timeText = (dts && dts.indexOf(':') !== -1) ? dts : label;
        el.innerHTML = '<div class="tt-body tt-body-col">' +
          '<div class="tt-text">' +
          '<div class="tt-count">' + Number(value || 0).toLocaleString('ru-RU') + ' шт.</div>' +
          (timeText ? '<div class="tt-time">' + escapeHtml(timeText) + '</div>' : '') +
          '<div class="tt-parts">' + rows + '</div>' +
          '</div></div>';
        placeTooltip(el, px, py);
        return;
      }
      let imgHtml;
      if (d && d.image) {
        imgHtml = '<img class="tt-img" src="' + d.image + '" alt="">';
      } else if (d && d.code) {
        imgHtml = '<div class="tt-noimg"><span class="product-chip" style="background:' + (d.color || '#adb5bd') + '">' + d.code + '</span></div>';
      } else {
        imgHtml = '<div class="tt-noimg"><span class="badge text-bg-secondary">—</span></div>';
      }
      let prodHtml;
      if (d && d.name) {
        prodHtml = '<div class="tt-name">' + d.name + '</div>' +
          (d.code ? '<div class="tt-1c">Код продукта: ' + d.code + '</div>' : '') +
          (d.code_1c ? '<div class="tt-1c">Код 1С: ' + d.code_1c + '</div>' : '') +
          (d.color ? '<div class="tt-1c">Цвет: <span style="color:' + d.color + '">' + d.color + '</span></div>' : '');
      } else {
        prodHtml = '<div class="tt-name text-muted">нет данных о продукте</div>';
      }
      el.innerHTML = '<div class="tt-body">' + imgHtml +
        '<div class="tt-text">' +
        '<div class="tt-count">' + Number(value || 0).toLocaleString('ru-RU') + ' шт.</div>' +
        // Время: для минутных графиков показываем только «22:31» (без даты);
        // полная дата остаётся только в графиках по дням/месяцам (в подписи нет времени)
        (label ? '<div class="tt-time">' + label + '</div>' : '') +
        ((d && d.ts && label && label.indexOf(':') === -1) ? '<div class="tt-1c">' + d.ts + '</div>' : '') +
        prodHtml +
        '</div></div>';
      placeTooltip(el, px, py);
    };
  }

  // --- Управление кнопкой выгрузки и ошибкой лимита ---
  function updateExportHint() {
    $('btnExportToggle').disabled = blocks.filter((b) => b.built).length === 0;
  }

  function showAddError(msg) {
    addReportError.textContent = msg;
    addReportError.classList.remove('d-none');
  }

  function hideAddError() {
    addReportError.classList.add('d-none');
    addReportError.textContent = '';
  }

  // --- Создание блока отчёта ---
  function createBlock() {
    const node = blockTemplate.content.firstElementChild.cloneNode(true);
    const st = {
      node: node,
      chart: null,
      chartApi: null,
      fullLabels: [], fullData: [], chartDetails: [], chartColors: [],
      visibleLabels: [], visibleDetails: [], visibleParts: [],
      minuteTs: [], fullDown: [], downColumns: [], downTexts: {}, downLabels: {},
      parts: [],          // разбивка минуты по продуктам (если есть)
      usesParts: false,   // минутный график с несколькими продуктами в минуте
      codeToDs: {},       // код продукта -> индекс датасета
      lastParams: null,
      lastReportId: null,
      built: false,
    };

    // Индекс датасета простоя (всегда последний) в chart.data.datasets
    st.downIdx = function () {
      if (!st.chart) return -1;
      for (let i = 0; i < st.chart.data.datasets.length; i++) {
        if (st.chart.data.datasets[i]._down) return i;
      }
      return -1;
    };

    const downInput = node.querySelector('.rb-down-input');
    const statusEl = node.querySelector('.rb-status');
    const resultEl = node.querySelector('.rb-result');
    const emptyEl = node.querySelector('.rb-empty');
    const tablesEl = node.querySelector('.rb-tables');
    const chartCard = node.querySelector('.rb-chart-card');
    const canvas = node.querySelector('.rb-canvas');
    const zoomWrap = node.querySelector('.rb-zoom');

    // --- вкладки ---
    const tabs = Array.prototype.slice.call(node.querySelectorAll('.rb-tab'));
    const panels = Array.prototype.slice.call(node.querySelectorAll('.report-panel'));
    function switchTab(tab) {
      tabs.forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
      panels.forEach((p) => { p.style.display = p.dataset.tab === tab ? '' : 'none'; });
    }
    tabs.forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));
    switchTab('shift');

    // --- «Весь период» на вкладке «Период» ---
    node.querySelectorAll('.btn-full-period').forEach((btn) => {
      btn.addEventListener('click', () => {
        const c = counterInfo(node.querySelector('.rb-counter').value);
        if (!c) return;
        const panel = node.querySelector('.report-panel[data-tab="period"]');
        const start = panel.querySelector('input[name="start"]');
        const end = panel.querySelector('input[name="end"]');
        if (c.first_record && start) start.value = fmtLocalInput(new Date(c.first_record));
        if (c.now && end) end.value = fmtLocalInput(new Date(c.now));
      });
    });

    // --- сбор параметров блока ---
    function collectParams() {
      const tab = (node.querySelector('.rb-tab.active') || {}).dataset.tab || 'shift';
      const panel = node.querySelector('.report-panel[data-tab="' + tab + '"]');
      const typeEl = panel.querySelector('input.report-type:checked');
      const params = {
        counter: node.querySelector('.rb-counter').value,
        tab: tab,
        type: typeEl ? typeEl.value : 'total',
      };
      if (tab === 'shift' || tab === 'day') {
        const dateInput = panel.querySelector('input[name="date"]');
        if (dateInput && dateInput.value) params.date = dateInput.value;
        if (tab === 'shift') {
          const shiftSel = panel.querySelector('select[name="shift"]');
          if (shiftSel) params.shift = shiftSel.value;
        }
      } else if (tab === 'month') {
        const month = panel.querySelector('select[name="month"]');
        const year = panel.querySelector('select[name="year"]');
        if (month && month.value) params.month = month.value;
        if (year && year.value) params.year = year.value;
      } else if (tab === 'quarter') {
        const year = panel.querySelector('select[name="year"]');
        const q = panel.querySelector('select[name="quarter"]');
        if (year && year.value) params.year = year.value;
        if (q && q.value) params.quarter = q.value;
      } else if (tab === 'year') {
        const year = panel.querySelector('select[name="year"]');
        if (year && year.value) params.year = year.value;
      } else if (tab === 'period') {
        const start = panel.querySelector('input[name="start"]');
        const end = panel.querySelector('input[name="end"]');
        if (start && start.value) params.start = start.value;
        if (end && end.value) params.end = end.value;
      }
      return params;
    }

    // --- перерисовка видимого окна графика ---
    function renderVisible() {
      if (!st.chart) return;
      const w = st.chartApi ? st.chartApi.getWindow() : { min: 0, max: Math.max(0, st.fullLabels.length - 1) };
      st.visibleLabels = st.fullLabels.slice(w.min, w.max + 1);
      const labels = st.visibleLabels;
      const data = st.fullData.slice(w.min, w.max + 1);
      st.visibleDetails = st.chartDetails.slice(w.min, w.max + 1);
      st.visibleParts = st.parts.slice(w.min, w.max + 1);
      st.chart.data.labels = labels;
      // Запас по оси Y: максимум (продукция + простои) + 20% сверху
      let maxVal = st.fullData.reduce((m, v) => Math.max(m, v || 0), 0);
      if (st.fullDown.length) maxVal = st.fullDown.reduce((m, v) => Math.max(m, v || 0), maxVal);
      st.chart.options.scales.y.max = window.Molvest3D
        ? Molvest3D.yAxisMax(maxVal)
        : Math.max(1, Math.ceil(maxVal * 1.4));
      // Чёрная окантовка столбиков — только в оконном режиме; при
      // максимальном уменьшении («Весь период») убираем, чтобы не чернить график
      st.chart.options.plugins.molvest3d.outline = st.chartApi ? !st.chartApi.isFullPeriod() : true;
      // Данные простоя: набор столбцов не скрываем (ширина столбцов не меняется),
      // при выключенном чекбоксе просто обнуляем значения
      const showDown = downInput.checked;
      st.downTexts = {};
      st.downLabels = {};
      // Минутный график определяется по наличию поминутных меток (а не по
      // простоям): даже без простоев столбики должны стоять вплотную.
      // Оба датасета — в одном стеке: Chart.js не делит ширину категории
      // (иначе столбики разрежены). Месячный график — без стека (простой рядом).
      const isMinuteChart = st.minuteTs.length > 0;
      st.chart.options.scales.x.stacked = isMinuteChart;
      st.chart.options.scales.y.stacked = isMinuteChart;
      // Данные по продуктам: при многопродуктовых минутах — по датасету на
      // продукт (столбец делится на цветные сегменты), иначе один датасет
      if (st.usesParts) {
        Object.keys(st.codeToDs).forEach((code) => {
          const ds = st.chart.data.datasets[st.codeToDs[code]];
          if (!ds) return;
          ds.data = data.map((_, i) => {
            const parts = st.visibleParts[i] || [];
            for (let j = 0; j < parts.length; j++) {
              if (parts[j].code === code) return parts[j].count || 0;
            }
            return 0;
          });
        });
      } else {
        st.chart.data.datasets[0].data = data;
        // Цвет столбцов — цвет продукта; обязательно срез по видимому окну
        st.chart.data.datasets[0].backgroundColor = st.chartColors.slice(w.min, w.max + 1);
      }
      let downData;
      const di = st.downIdx();
      if (isMinuteChart && di !== -1) {
        // минутный график: минимальные красно-полосатые столбики (1–2 ед.)
        // на каждой минуте простоя; подпись (время простоя) — только на
        // последней минуте события
        const DOWN_MIN_VALUE = 1;
        downData = new Array(data.length).fill(0);
        if (showDown) {
          st.downColumns.forEach((c) => {
            const local = c.idx - w.min;
            if (local >= 0 && local < data.length) {
              downData[local] = DOWN_MIN_VALUE;
              st.downTexts[local] = c.text;
              st.downLabels[local] = c.label;
            }
          });
        }
        st.chart.data.datasets[di].backgroundColor = stripesPattern;
      } else if (di !== -1) {
        // месячный график: минуты простоя по дням (красно-чёрные столбики рядом)
        downData = showDown ? st.fullDown.slice(w.min, w.max + 1) : new Array(data.length).fill(0);
        st.chart.data.datasets[di].backgroundColor = stripesPattern;
      } else {
        downData = new Array(data.length).fill(0);
      }
      if (di !== -1) {
        st.chart.data.datasets[di].data = downData;
        st.chart.data.datasets[di].borderWidth = 0;
      }
      st.chart.update('none');
    }
    downInput.addEventListener('change', renderVisible);

    // --- построение графика блока ---
    function ensureDownDs() {
      if (st.downIdx() !== -1) return;
      st.chart.data.datasets.push({
        label: 'Простой',
        _down: true,
        data: [],
        backgroundColor: stripesPattern,
        borderWidth: 0,
        borderRadius: 0,
        barPercentage: 1.0,
        categoryPercentage: 1.0,
        stack: 'main',
        molvest3d: false,
      });
    }

    // Датасеты графика: по одному на продукт при многопродуктовых минутах
    // (столбец делится на цветные сегменты), иначе — единый датасет продукции.
    // Датасет простоя всегда существует и является последним.
    function syncReportDatasets() {
      if (!st.chart) return;
      ensureDownDs();
      const codes = new Set();
      if (st.usesParts) {
        st.parts.forEach((parts) => (parts || []).forEach((p) => {
          if (p && p.code) codes.add(p.code);
        }));
      }
      // удаляем устаревшие датасеты продуктов
      st.chart.data.datasets = st.chart.data.datasets.filter((ds) => {
        if (ds._down) return true;
        if (ds._code && codes.has(ds._code)) return true;
        delete st.codeToDs[ds._code];
        return false;
      });
      if (st.usesParts) {
        let insertIdx = st.downIdx();
        if (insertIdx === -1) insertIdx = st.chart.data.datasets.length;
        const sorted = Array.from(codes)
          .sort((a, b) => (parseInt(a, 10) || 0) - (parseInt(b, 10) || 0) || a.localeCompare(b));
        sorted.forEach((code) => {
          if (code in st.codeToDs) return;
          const p = st.productsMap[code] || null;
          st.chart.data.datasets.splice(insertIdx, 0, {
            label: 'Продукт ' + code,
            _code: code,
            data: [],
            backgroundColor: (p && p.color) || '#6c757d',
            borderWidth: 0,
            borderRadius: 0,
            barPercentage: 1.0,
            categoryPercentage: 1.0,
            stack: 'main',
          });
          insertIdx += 1;
        });
      } else {
        // единый датасет продукции (нет многопродуктовых минут)
        if (!st.chart.data.datasets.length || st.chart.data.datasets[0]._down) {
          st.chart.data.datasets.splice(0, 0, {
            label: 'Продукция',
            data: [],
            backgroundColor: [],
            borderWidth: 0,
            borderRadius: 0,
            barPercentage: 1.0,
            categoryPercentage: 1.0,
            stack: 'main',
          });
        }
      }
      // пересчёт индексов датасетов продуктов
      Object.keys(st.codeToDs).forEach((k) => delete st.codeToDs[k]);
      st.chart.data.datasets.forEach((ds, i) => {
        if (!ds._down && ds._code) st.codeToDs[ds._code] = i;
      });
    }

    function renderChart(cfg) {
      if (!cfg || !cfg.labels || !cfg.labels.length) {
        chartCard.classList.add('d-none');
        return;
      }
      chartCard.classList.remove('d-none');
      st.fullLabels = cfg.labels || [];
      st.fullData = (cfg.datasets && cfg.datasets[0] && cfg.datasets[0].data) || [];
      st.chartDetails = cfg.details || [];
      st.minuteTs = cfg.minute_ts || [];
      st.fullDown = cfg.downtime_by_day || [];
      st.downColumns = buildDownColumns(st.minuteTs, cfg.downtime || [], st.fullData);
      st.chartColors = (cfg.colors && cfg.colors.length === st.fullData.length)
        ? cfg.colors.slice()
        : st.chartDetails.map((d) => (d && d.color) || '#6c757d');
      st.productsMap = cfg.products || {};
      st.parts = (cfg.parts && cfg.parts.length === st.fullLabels.length) ? cfg.parts : [];
      // многопродуктовые минуты — только на минутных графиках
      st.usesParts = st.minuteTs.length > 0 && st.parts.length === st.fullLabels.length;
      if (!st.chart) {
        st.chart = new Chart(canvas.getContext('2d'), {
          type: cfg.type || 'bar',
          data: {
            labels: st.fullLabels.slice(),
            datasets: [],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
              // Вместо легенды — чекбокс «Отображать график простоя»
              legend: { display: false },
              tooltip: { enabled: false, external: makeTooltipHandler(st) },
              molvest3d: { enabled: true, depth: 9, outline: true },
              // Жёлтый «!» над каждым столбиком простоя
              datalabels: {
                display: (ctx) => ctx.datasetIndex === st.downIdx() && !!st.downLabels[ctx.dataIndex],
                color: '#ffc107',
                textStrokeColor: 'rgba(0,0,0,0.85)',
                textStrokeWidth: 1.5,
                anchor: 'end',
                align: 'end',
                offset: 1,
                font: { weight: 'bold', size: 12 },
                formatter: (value, ctx) => st.downLabels[ctx.dataIndex] || '',
              },
            },
            scales: {
              x: { stacked: st.usesParts, grid: { display: false }, ticks: { maxTicksLimit: 16, maxRotation: 0, autoSkip: true } },
              y: { stacked: st.usesParts, beginAtZero: true, ticks: { precision: 0 } },
            },
          },
        });
        if (window.MolvestZoom) {
          st.chartApi = MolvestZoom.attach(st.chart, {
            container: zoomWrap,
            onWindow: renderVisible,
          });
        }
        st.chart.canvas.addEventListener('mouseleave', hideTooltip);
      } else {
        st.chart.data.labels = st.fullLabels.slice();
      }
      syncReportDatasets();
      if (st.chartApi) {
        st.chartApi.setData(st.fullLabels.length);
        // Минутные графики (много точек) открываются окном 30 минут;
        // графики по дням/месяцам показываются целиком
        if (st.fullLabels.length > 100) st.chartApi.setStep(1);
      }
      renderVisible();
    }

    // --- формирование отчёта блока (Ajax) ---
    async function build() {
      const params = collectParams();
      statusEl.innerHTML = 'Формирование…';
      try {
        const resp = await fetch('/reports/build/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
          body: JSON.stringify(params),
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) {
          statusEl.innerHTML = '<span class="text-danger fw-semibold">Ошибка:</span> ' +
            escapeHtml(data.error || ('HTTP ' + resp.status));
          return;
        }
        st.lastParams = params;
        st.lastReportId = data.result.report_id || null;
        st.built = true;
        resultEl.classList.remove('d-none');
        tablesEl.innerHTML = data.html || '';
        const hasChart = !!(data.result.chart && data.result.chart.labels && data.result.chart.labels.length);
        emptyEl.classList.toggle('d-none', !!data.html || hasChart);
        renderChart(data.result.chart);
        statusEl.textContent = 'Готово.';
        updateExportHint();
      } catch (e) {
        statusEl.innerHTML = '<span class="text-danger fw-semibold">Ошибка:</span> ' + escapeHtml(e.message);
      }
    }
    node.querySelector('.rb-build').addEventListener('click', build);

    // --- удаление блока ---
    node.querySelector('.rb-remove').addEventListener('click', () => removeBlock(st));

    // Нумерация и добавление в контейнер
    node.querySelector('.rb-index').textContent = String(blocks.length + 1);
    blocksContainer.appendChild(node);
    blocks.push(st);
    refreshRemoveButtons();
    updateExportHint();
    return st;
  }

  function removeBlock(st) {
    if (blocks.length <= 1) return; // последний блок не удаляем
    if (st.chart) { st.chart.destroy(); st.chart = null; }
    st.node.remove();
    const i = blocks.indexOf(st);
    if (i !== -1) blocks.splice(i, 1);
    // перенумеровать оставшиеся блоки
    blocks.forEach((b, idx) => { b.node.querySelector('.rb-index').textContent = String(idx + 1); });
    refreshRemoveButtons();
    updateExportHint();
  }

  function refreshRemoveButtons() {
    const single = blocks.length <= 1;
    blocks.forEach((b) => {
      b.node.querySelector('.rb-remove').classList.toggle('d-none', single);
    });
  }

  // --- «Добавить отчет для сравнения» ---
  btnAddReport.addEventListener('click', () => {
    if (blocks.length >= MAX_REPORTS) {
      showAddError('Превышен лимит сформированных отчетов');
      return;
    }
    hideAddError();
    createBlock();
  });

  // --- «Выгрузить отчёты»: все сформированные отчёты в один файл ---
  async function exportBundle(fmt) {
    const built = blocks.filter((b) => b.built && b.lastParams);
    if (!built.length) {
      showAddError('Сначала сформируйте хотя бы один отчёт.');
      return;
    }
    hideAddError();
    const payload = {
      fmt: fmt,
      reports: built.map((b) => Object.assign({}, b.lastParams, { report_id: b.lastReportId })),
    };
    try {
      const resp = await fetch('/reports/export-multi/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        let err = 'HTTP ' + resp.status;
        try {
          const d = await resp.json();
          if (d && d.error) err = d.error;
        } catch (_) { /* не JSON — оставляем HTTP-статус */ }
        showAddError(err);
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = EXPORT_FILE[fmt] || 'reports_comparison.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (e) {
      showAddError(e.message);
    }
  }
  $('btnExportXlsx').addEventListener('click', (e) => { e.preventDefault(); exportBundle('xlsx'); });
  $('btnExportCsv').addEventListener('click', (e) => { e.preventDefault(); exportBundle('csv'); });

  // Стартовый блок
  createBlock();
})();
