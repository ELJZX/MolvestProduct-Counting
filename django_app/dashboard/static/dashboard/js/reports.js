/* Вкладка «Отчёты»: несколько независимых блоков отчётов для сравнения.
   Каждый блок — свой счётчик, вкладка, тип и период. Кнопка «Формировать»
   строит таблицы + график через Ajax (fetch); «Добавить отчет для сравнения»
   добавляет ещё один блок (максимум 8); «Выгрузить отчёты» — все
   сформированные отчёты в один файл (в Excel — отдельный лист на отчёт). */
(function () {
  'use strict';

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

  // Столбцы простоя на минутном графике: один красно-чёрный столбец на событие
  function buildDownColumns(minuteTs, events, seriesData) {
    const cols = [];
    (events || []).forEach((ev) => {
      const end = new Date(ev.end).getTime();
      let resumeIdx = -1;
      for (let i = 0; i < minuteTs.length; i++) {
        if (new Date(minuteTs[i]).getTime() >= end) { resumeIdx = i; break; }
      }
      let idx;
      if (resumeIdx === -1) {
        idx = Math.max(0, minuteTs.length - 1);
      } else if ((seriesData[resumeIdx] || 0) > 0) {
        idx = resumeIdx - 1;
      } else {
        idx = resumeIdx;
      }
      if (idx < 0) idx = 0;
      const text = 'Простой: ' + fmtDT(ev.start) + ' – ' + fmtDT(ev.end) +
        ' · ' + fmtDuration(ev.minutes);
      cols.push({ idx: idx, text: text });
    });
    return cols;
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
      const didx = dp.datasetIndex;
      const pos = ch.canvas.getBoundingClientRect();
      const px = pos.left + tooltip.caretX;
      const py = pos.top + tooltip.caretY;
      // столбец простоя (красно-чёрный): показываем период простоя
      if (didx === 1) {
        const val = dp.parsed.y || 0;
        const text = st.downTexts[idx] || ('Простой: ' + fmtDuration(val));
        el.innerHTML = '<div class="tt-body"><div class="tt-noimg"><span class="badge text-bg-danger">↓</span></div>' +
          '<div class="tt-text"><div class="tt-count text-danger">Простой</div>' +
          '<div class="tt-1c">' + text + '</div></div></div>';
        placeTooltip(el, px, py);
        return;
      }
      const d = st.visibleDetails[idx] || null;
      const value = dp.parsed.y;
      const label = st.visibleLabels[idx] || '';
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
      visibleLabels: [], visibleDetails: [],
      minuteTs: [], fullDown: [], downColumns: [], downTexts: {},
      lastParams: null,
      lastReportId: null,
      built: false,
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
      st.chart.data.labels = labels;
      st.chart.data.datasets[0].data = data;
      // Цвет столбцов — цвет продукта; обязательно срез по видимому окну
      st.chart.data.datasets[0].backgroundColor = st.chartColors.slice(w.min, w.max + 1);
      // Запас по оси Y: максимум (продукция + простои) + 20% сверху
      let maxVal = st.fullData.reduce((m, v) => Math.max(m, v || 0), 0);
      if (st.fullDown.length) maxVal = st.fullDown.reduce((m, v) => Math.max(m, v || 0), maxVal);
      st.chart.options.scales.y.max = window.Molvest3D
        ? Molvest3D.yAxisMax(maxVal)
        : Math.max(1, Math.ceil(maxVal * 1.25));
      // Данные простоя: набор столбцов не скрываем (ширина столбцов не меняется),
      // при выключенном чекбоксе просто обнуляем значения
      const showDown = downInput.checked;
      st.downTexts = {};
      let downData;
      if (st.downColumns.length) {
        downData = new Array(data.length).fill(0);
        if (showDown) {
          st.downColumns.forEach((c) => {
            const local = c.idx - w.min;
            if (local >= 0 && local < data.length) {
              downData[local] = maxVal;
              st.downTexts[local] = c.text;
            }
          });
        }
      } else {
        downData = showDown ? st.fullDown.slice(w.min, w.max + 1) : new Array(data.length).fill(0);
      }
      st.chart.data.datasets[1].data = downData;
      st.chart.update('none');
    }
    downInput.addEventListener('change', renderVisible);

    // --- построение графика блока ---
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
      if (!st.chart) {
        st.chart = new Chart(canvas.getContext('2d'), {
          type: cfg.type || 'bar',
          data: {
            labels: st.fullLabels.slice(),
            datasets: [
              {
                label: 'Продукция',
                data: st.fullData.slice(),
                backgroundColor: st.chartColors.slice(),
                borderWidth: 0,
                borderRadius: 3,
              },
              {
                // Простои: на минутном графике — красно-чёрные столбцы,
                // на месячном — минуты простоя по дням
                label: 'Простой',
                data: [],
                backgroundColor: stripesPattern,
                borderWidth: 0,
                borderRadius: 2,
                molvest3d: false,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
              // Вместо легенды — чекбокс «Отображать график простоя»
              legend: { display: false },
              tooltip: { enabled: false, external: makeTooltipHandler(st) },
              molvest3d: { enabled: true, depth: 9 },
            },
            scales: {
              x: { grid: { display: false }, ticks: { maxTicksLimit: 16, maxRotation: 0, autoSkip: true } },
              y: { beginAtZero: true, ticks: { precision: 0 } },
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
        st.chart.data.datasets[0].data = st.fullData.slice();
        st.chart.data.datasets[0].backgroundColor = st.chartColors.slice();
      }
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
