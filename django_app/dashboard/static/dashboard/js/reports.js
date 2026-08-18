/* Вкладка «Отчёты»: Смена/Сутки/Месяц/Квартал/Год/Период.
   Выбор счётчика (закреплён за линией), типа отчёта, периода; кнопка
   «Формировать» строит таблицы + график сразу на странице; «Выгрузить
   отчёт» — XLSX/CSV с теми же параметрами. */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const counters = JSON.parse($('countersJson').textContent);
  const counterById = {};
  counters.forEach((c) => { counterById[c.id] = c; });

  const tabs = Array.prototype.slice.call(document.querySelectorAll('#reportTabs .nav-link'));
  const panels = Array.prototype.slice.call(document.querySelectorAll('.report-panel'));

  const counterSelect = $('counterSelect');
  const btnBuild = $('btnBuild');
  const buildStatus = $('buildStatus');
  const resultWrap = $('reportResultWrap');
  const reportTables = $('reportTables');
  const reportTitle = $('reportTitle');
  const reportPeriod = $('reportPeriod');
  const chartCard = $('reportChartCard');
  const btnExportXlsx = $('btnExportXlsx');
  const btnExportCsv = $('btnExportCsv');
  const btnExportToggle = $('btnExportToggle');

  let chart = null;
  let chartApi = null;
  let fullLabels = [];
  let fullData = [];
  let chartDetails = [];
  let chartColors = [];
  let visibleLabels = [];
  let visibleDetails = [];
  let lastParams = null;

  // Данные простоя на графике
  let minuteTs = [];      // ISO-минуты (минутный график), индекс == индекс столбца
  let fullDown = [];      // минуты простоя по дням (месячный график)
  let downColumns = [];   // [{idx, text}] события простоя на минутном графике
  let downTexts = {};     // idx в видимом окне -> текст подсказки простоя

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

  function getCookie(name) {
    const m = document.cookie.match('(^|;)\\s*' + name + '=([^;]*)');
    return m ? decodeURIComponent(m[2]) : '';
  }

  function fmtLocalInput(dt) {
    const pad = (n) => String(n).padStart(2, '0');
    return dt.getFullYear() + '-' + pad(dt.getMonth() + 1) + '-' + pad(dt.getDate()) +
      'T' + pad(dt.getHours()) + ':' + pad(dt.getMinutes());
  }

  // --- переключение вкладок ---
  function switchTab(tab) {
    tabs.forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
    panels.forEach((p) => { p.style.display = p.dataset.tab === tab ? '' : 'none'; });
  }
  tabs.forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));

  // --- «Весь период» на вкладке «Период» ---
  document.querySelectorAll('.btn-full-period').forEach((btn) => {
    btn.addEventListener('click', () => {
      const c = counterById[parseInt(counterSelect.value, 10)];
      if (!c) return;
      if (c.first_record) $('period_start').value = fmtLocalInput(new Date(c.first_record));
      if (c.now) $('period_end').value = fmtLocalInput(new Date(c.now));
    });
  });

  // --- сбор параметров ---
  function collectParams() {
    const tab = (document.querySelector('#reportTabs .nav-link.active') || {}).dataset.tab || 'shift';
    const panel = $('panel-' + tab);
    const typeEl = panel.querySelector('input.report-type:checked');
    const params = {
      counter: counterSelect.value,
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
      const month = $('monthSelect'), year = $('year_month');
      if (month && month.value) params.month = month.value;
      if (year && year.value) params.year = year.value;
    } else if (tab === 'quarter') {
      const year = $('year_quarter'), q = $('quarterSelect');
      if (year && year.value) params.year = year.value;
      if (q && q.value) params.quarter = q.value;
    } else if (tab === 'year') {
      const year = $('year_year');
      if (year && year.value) params.year = year.value;
    } else if (tab === 'period') {
      const start = $('period_start'), end = $('period_end');
      if (start && start.value) params.start = start.value;
      if (end && end.value) params.end = end.value;
    }
    return params;
  }

  function toQuery(p) {
    return Object.keys(p).map((k) => encodeURIComponent(k) + '=' + encodeURIComponent(p[k])).join('&');
  }

  function fmtDT(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    const pad = (n) => String(n).padStart(2, '0');
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear() +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
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
        (ev.ongoing ? ' (продолжается)' : '') + ' · ' + ev.minutes + ' мин.';
      cols.push({ idx: idx, text: text });
    });
    return cols;
  }

  // Тултип графика: время, кол-во, код продукта, название, цвет, картинка
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

  // Позиция подсказки с ограничением по границам окна (не выходит за экран)
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

  function reportTooltipHandler(context) {
    const { chart: ch, tooltip } = context;
    const el = ensureReportTooltip();
    // Не полагаемся на tooltip.opacity (при animation:false он может не меняться)
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
      const text = downTexts[idx] ||
        ('Простой: ' + Number(val).toLocaleString('ru-RU') + ' мин.');
      el.innerHTML = '<div class="tt-body"><div class="tt-noimg"><span class="badge text-bg-danger">↓</span></div>' +
        '<div class="tt-text"><div class="tt-count text-danger">Простой</div>' +
        '<div class="tt-1c">' + text + '</div></div></div>';
      placeTooltip(el, px, py);
      return;
    }
    const d = visibleDetails[idx] || null;
    const value = dp.parsed.y;
    const label = visibleLabels[idx] || '';
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
      (label ? '<div class="tt-time">' + label + '</div>' : '') +
      (d && d.ts ? '<div class="tt-1c">' + d.ts + '</div>' : '') +
      prodHtml +
      '</div></div>';
    placeTooltip(el, px, py);
  }

  // Навигация по графику (как на вкладке «Линии»): кнопки −/+,
  // «Весь период», полоса прокрутки, колесо мыши, перетаскивание.
  function renderVisible() {
    if (!chart) return;
    const w = chartApi ? chartApi.getWindow() : { min: 0, max: Math.max(0, fullLabels.length - 1) };
    visibleLabels = fullLabels.slice(w.min, w.max + 1);
    const labels = visibleLabels;
    const data = fullData.slice(w.min, w.max + 1);
    visibleDetails = chartDetails.slice(w.min, w.max + 1);
    chart.data.labels = labels;
    chart.data.datasets[0].data = data;
    // Цвет столбцов — цвет продукта; ОБЯЗАТЕЛЬНО срез по видимому окну,
    // иначе цвета смещаются относительно минут (баг с окном 30 минут)
    chart.data.datasets[0].backgroundColor = chartColors.slice(w.min, w.max + 1);
    // Запас по оси Y: максимум (продукция + простои) + 20% сверху
    let maxVal = fullData.reduce((m, v) => Math.max(m, v || 0), 0);
    if (fullDown.length) maxVal = fullDown.reduce((m, v) => Math.max(m, v || 0), maxVal);
    chart.options.scales.y.max = window.Molvest3D
      ? Molvest3D.yAxisMax(maxVal)
      : Math.max(1, Math.ceil(maxVal * 1.25));
    // Данные простоя:
    //  - минутный график: красно-чёрные столбцы в минуты возобновления,
    //  - месячный график: минуты простоя по каждому дню (столбики рядом).
    downTexts = {};
    let downData;
    if (downColumns.length) {
      downData = new Array(data.length).fill(0);
      downColumns.forEach((c) => {
        const local = c.idx - w.min;
        if (local >= 0 && local < data.length) {
          downData[local] = maxVal;
          downTexts[local] = c.text;
        }
      });
    } else {
      downData = fullDown.slice(w.min, w.max + 1);
    }
    chart.data.datasets[1].data = downData;
    chart.update('none');
  }

  function renderChart(cfg) {
    if (!cfg || !cfg.labels || !cfg.labels.length) {
      chartCard.classList.add('d-none');
      return;
    }
    chartCard.classList.remove('d-none');
    fullLabels = cfg.labels || [];
    fullData = (cfg.datasets && cfg.datasets[0] && cfg.datasets[0].data) || [];
    chartDetails = cfg.details || [];
    minuteTs = cfg.minute_ts || [];
    fullDown = cfg.downtime_by_day || [];
    downColumns = buildDownColumns(minuteTs, cfg.downtime || [], fullData);
    // Цвета столбцов по продуктам (из details) — для 3D-столбцов и тултипов
    chartColors = (cfg.colors && cfg.colors.length === fullData.length)
      ? cfg.colors.slice()
      : chartDetails.map((d) => (d && d.color) || '#6c757d');
    if (!chart) {
      chart = new Chart($('reportChart').getContext('2d'), {
        type: cfg.type || 'bar',
        data: {
          labels: fullLabels.slice(),
          datasets: [
            {
              label: 'Продукция',
              data: fullData.slice(),
              backgroundColor: chartColors.slice(),
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
            // «Кол-во, шт./мин» не показываем; в легенде только «Простой»
            legend: {
              display: true,
              position: 'top',
              labels: {
                boxWidth: 14,
                filter: (item) => item.datasetIndex === 1,
              },
            },
            tooltip: { enabled: false, external: reportTooltipHandler },
            // 3D-столбцы, цвет каждого — цвет продукта за эту минуту/день
            molvest3d: { enabled: true, depth: 9 },
          },
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 16, maxRotation: 0, autoSkip: true } },
            y: { beginAtZero: true, ticks: { precision: 0 } },
          },
        },
      });
      if (window.MolvestZoom) {
        chartApi = MolvestZoom.attach(chart, {
          container: $('reportZoom'),
          onWindow: () => renderVisible(),
        });
      }
      // курсор ушёл с холста — подсказка скрывается
      chart.canvas.addEventListener('mouseleave', hideTooltip);
    } else {
      chart.data.labels = fullLabels.slice();
      chart.data.datasets[0].data = fullData.slice();
      chart.data.datasets[0].backgroundColor = chartColors.slice();
    }
    if (chartApi) {
      chartApi.setData(fullLabels.length);
      // По умолчанию минутный график открывается в масштабе «окно 30 минут»,
      // каждая минута — отдельный столбик. Для графиков по дням (мало точек)
      // окно не применяется — показывается весь период.
      if (fullLabels.length > 100) chartApi.setStep(1);
    }
    renderVisible();
  }

  async function build() {
    const params = collectParams();
    buildStatus.textContent = 'Формирование…';
    try {
      const resp = await fetch('/reports/build/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify(params),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        buildStatus.textContent = 'Ошибка: ' + (data.error || resp.status);
        return;
      }
      lastParams = params;
      resultWrap.classList.remove('d-none');
      const emptyEl = $('reportsEmpty');
      if (emptyEl) emptyEl.classList.add('d-none');
      reportTables.innerHTML = data.html;
      // Отчёт-график (без таблиц): скрываем карточку «Отчёт»,
      // заголовок показываем в шапке карточки графика
      const tablesCard = $('reportTablesCard');
      if (tablesCard) tablesCard.classList.toggle('d-none', !data.html);
      const chartHeader = $('reportChartHeader');
      if (chartHeader) {
        chartHeader.textContent = data.html
          ? 'График'
          : (data.result.title || 'График') +
            (data.result.period_label ? ' · ' + data.result.period_label : '');
      }
      reportTitle.innerHTML = '<i class="bi bi-table me-1"></i>' + data.result.title;
      reportPeriod.textContent = data.result.period_label + ' · Счетчик: ' +
        (counterById[parseInt(params.counter, 10)] ? counterById[parseInt(params.counter, 10)].name + ' (' + counterById[parseInt(params.counter, 10)].line + ')' : '');
      renderChart(data.result.chart);
      btnExportXlsx.href = '/reports/export/?fmt=xlsx&' + toQuery(params);
      btnExportCsv.href = '/reports/export/?fmt=csv&' + toQuery(params);
      btnExportToggle.disabled = false;
      buildStatus.textContent = 'Готово.';
    } catch (e) {
      buildStatus.textContent = 'Ошибка: ' + e.message;
    }
  }

  btnBuild.addEventListener('click', build);
  switchTab('shift');
})();