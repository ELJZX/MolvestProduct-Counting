/* Масштабирование диаграмм кнопками + прокрутка по всему периоду.
   Используется на страницах: Линия, Отчёты, Отчёты о простоях.

   Возможности:
   - кнопка «+» — увеличить масштаб (окно меньше), «−» — уменьшить (окно больше),
     «Весь период» — показать выбранный период целиком;
   - шаги окна: 10, 30, 60 минут (плюс «Весь период»);
   - при изменении шага окно можно ПРОКРУЧИВАТЬ по всему периоду:
       * полоса прокрутки под графиком (тянуть за бегунок, клик — прыжок),
       * колесо мыши над графиком,
       * перетаскивание графика мышью;
   - подписи оси времени и подсказки обновляются вместе с окном.

   Подключение:
     const api = MolvestZoom.attach(chart, {
       container: <куда вставить панель управления>,
       onWindow: (minIdx, maxIdx) => { ... }   // перерисовать данные по индексам
     });
     api.setData(length);   // вызвать при загрузке нового ряда
     api.reset();           // показать весь период
*/
(function (window) {
  'use strict';

  var STEPS = [10, 30, 60]; // минуты в окне

  function stepLabel(minutes) {
    if (minutes < 60) return minutes + ' мин';
    var h = minutes / 60;
    return (h % 1 === 0 ? h : h.toFixed(1)) + ' ч';
  }

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function buildPanel(container) {
    var panel = document.createElement('div');
    panel.className = 'zoom-panel';
    panel.innerHTML =
      '<div class="zoom-top">' +
        '<div class="zoom-btns">' +
          '<button type="button" class="zoom-btn" data-zoom="out" title="Уменьшить масштаб (больше времени)" tabindex="-1">−</button>' +
          '<button type="button" class="zoom-btn" data-zoom="reset" title="Показать весь период" tabindex="-1">Весь период</button>' +
          '<button type="button" class="zoom-btn" data-zoom="in" title="Увеличить масштаб (меньше времени)" tabindex="-1">+</button>' +
        '</div>' +
        '<span class="zoom-label" data-role="label">весь период</span>' +
      '</div>' +
      '<div class="zoom-scroll" data-role="scroll">' +
        '<div class="zoom-thumb" data-role="thumb"></div>' +
      '</div>';
    container.appendChild(panel);
    return panel;
  }

  function attach(chart, opts) {
    opts = opts || {};
    var container = opts.container || (chart.canvas && chart.canvas.parentNode) || document.body;
    var panel = buildPanel(container);
    var label = panel.querySelector('[data-role="label"]');
    var scrollEl = panel.querySelector('[data-role="scroll"]');
    var thumb = panel.querySelector('[data-role="thumb"]');

    var state = {
      length: 0,          // всего точек (минут) в ряде
      minIdx: 0,          // видимое окно (индексы точек)
      maxIdx: 0,
      stepIdx: -1,        // индекс в STEPS; -1 = весь период
    };

    function windowSize() {
      return state.maxIdx - state.minIdx + 1;
    }

    function updateLabel() {
      if (state.stepIdx < 0) {
        label.textContent = 'весь период';
      } else {
        label.textContent = 'окно ' + stepLabel(STEPS[state.stepIdx]) +
          (state.length > 1 ? ' · ' + (state.minIdx + 1) + '–' + (state.maxIdx + 1) + ' мин из ' + state.length : '');
      }
    }

    function updateThumb() {
      var w = scrollEl.clientWidth || 1;
      var span = Math.max(1, state.length - 1);
      var left = (state.minIdx / span) * w;
      var tw = Math.max(14, (windowSize() / span) * w);
      thumb.style.left = left + 'px';
      thumb.style.width = tw + 'px';
    }

    function emit() {
      if (opts.onWindow) opts.onWindow(state.minIdx, state.maxIdx);
    }

    function applyWindow(minIdx, maxIdx) {
      if (state.length === 0) return;
      // размер окна берём из переданного диапазона (меняется при смене шага)
      var size = clamp(Math.round(maxIdx - minIdx + 1), 1, state.length);
      minIdx = Math.round(minIdx);
      minIdx = clamp(minIdx, 0, Math.max(0, state.length - size));
      state.minIdx = minIdx;
      state.maxIdx = minIdx + size - 1;
      updateLabel();
      updateThumb();
      emit();
    }

    // Сдвиг окна на delta минут (положительное — вперёд к концу периода).
    function moveWindow(delta) {
      if (state.stepIdx < 0 || state.length === 0) return;
      delta = Math.round(delta);
      if (delta === 0) return;
      applyWindow(state.minIdx + delta, state.maxIdx + delta);
    }

    function setStep(idx) {
      if (state.length === 0) return;
      idx = clamp(idx, 0, STEPS.length - 1);
      var wasFull = state.stepIdx < 0;
      state.stepIdx = idx;
      var size = Math.min(STEPS[idx], state.length);
      var center;
      if (wasFull) {
        // первое приближение — конец периода (свежие данные)
        center = state.length - 1 - (size - 1) / 2;
      } else {
        center = (state.minIdx + state.maxIdx) / 2;
      }
      var min = Math.round(center - size / 2);
      min = clamp(min, 0, Math.max(0, state.length - size));
      applyWindow(min, min + size - 1);
    }

    function reset() {
      state.stepIdx = -1;
      state.minIdx = 0;
      state.maxIdx = Math.max(0, state.length - 1);
      updateLabel();
      updateThumb();
      emit();
    }

    // ---- кнопки ----
    panel.querySelectorAll('.zoom-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        // Кнопка не должна удерживать фокус/курсор после нажатия
        btn.blur();
        var kind = btn.dataset.zoom;
        if (kind === 'reset') {
          reset();
        } else if (kind === 'in') {
          if (state.stepIdx < 0) setStep(STEPS.length - 1);
          else if (state.stepIdx > 0) setStep(state.stepIdx - 1);
        } else if (kind === 'out') {
          if (state.stepIdx < 0) { /* уже весь период */ }
          else if (state.stepIdx < STEPS.length - 1) setStep(state.stepIdx + 1);
          else reset();
        }
      });
    });

    // ---- полоса прокрутки ----
    function idxFromClientX(clientX) {
      var r = scrollEl.getBoundingClientRect();
      var frac = (clientX - r.left) / (r.width || 1);
      return Math.round(clamp(frac, 0, 1) * (state.length - 1));
    }

    var scrollDrag = null;
    scrollEl.addEventListener('pointerdown', function (e) {
      if (state.stepIdx < 0 || state.length === 0) return;
      e.preventDefault();
      if (e.target === thumb || e.target.closest('[data-role="thumb"]')) {
        scrollDrag = { mode: 'thumb', startX: e.clientX, startMin: state.minIdx };
      } else {
        // клик по треку — центрируем окно в точке клика
        var center = idxFromClientX(e.clientX);
        var half = (windowSize() - 1) / 2;
        scrollDrag = { mode: 'jump', startX: e.clientX, startMin: center - half, startMax: center + half };
      }
      window.addEventListener('pointermove', onScrollMove);
      window.addEventListener('pointerup', onScrollUp);
    });

    function onScrollMove(e) {
      if (!scrollDrag) return;
      var w = scrollEl.clientWidth || 1;
      var delta = Math.round((e.clientX - scrollDrag.startX) / w * (state.length - 1));
      if (scrollDrag.mode === 'thumb') {
        applyWindow(scrollDrag.startMin + delta, scrollDrag.startMin + delta + windowSize() - 1);
      } else {
        applyWindow(scrollDrag.startMin + delta, scrollDrag.startMax + delta);
      }
    }

    function onScrollUp() {
      scrollDrag = null;
      window.removeEventListener('pointermove', onScrollMove);
      window.removeEventListener('pointerup', onScrollUp);
    }

    // ---- колесо мыши над графиком ----
    function onCanvasWheel(e) {
      if (state.stepIdx < 0 || state.length === 0) return; // весь период — не мешаем скроллу страницы
      e.preventDefault();
      var d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      var stepMin = STEPS[state.stepIdx];
      var perNotch = Math.max(1, Math.round(stepMin / 10));
      moveWindow((d / 100) * perNotch);
    }

    // ---- перетаскивание графика мышью ----
    var dragState = null;
    function onCanvasPointerDown(e) {
      if (state.stepIdx < 0 || state.length === 0) return;
      dragState = { startX: e.clientX, startMin: state.minIdx };
      try { chart.canvas.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    }
    function onCanvasPointerMove(e) {
      if (!dragState) return;
      var rect = chart.canvas.getBoundingClientRect();
      var delta = Math.round((e.clientX - dragState.startX) / (rect.width || 1) * (state.length - 1));
      applyWindow(dragState.startMin + delta, dragState.startMin + delta + windowSize() - 1);
    }
    function onCanvasPointerUp() {
      dragState = null;
    }

    if (chart.canvas) {
      chart.canvas.addEventListener('wheel', onCanvasWheel, { passive: false });
      chart.canvas.addEventListener('pointerdown', onCanvasPointerDown);
      chart.canvas.addEventListener('pointermove', onCanvasPointerMove);
      chart.canvas.addEventListener('pointerup', onCanvasPointerUp);
      chart.canvas.addEventListener('pointercancel', onCanvasPointerUp);
    }

    // ---- данные ----
    function setData(length) {
      var prevLen = state.length;
      state.length = Math.max(0, length || 0);
      if (state.length === 0) {
        state.minIdx = 0;
        state.maxIdx = 0;
        updateLabel();
        updateThumb();
        return;
      }
      if (prevLen !== state.length) {
        if (state.stepIdx >= 0) {
          var size = Math.min(STEPS[state.stepIdx], state.length);
          var wasAtEnd = prevLen > 0 && state.maxIdx >= prevLen - 1;
          if (wasAtEnd) {
            // окно было прижато к концу — следуем за новыми данными (реальное время)
            state.maxIdx = state.length - 1;
            state.minIdx = Math.max(0, state.maxIdx - size + 1);
          } else {
            // пользователь просматривает период — сохраняем позицию
            state.minIdx = Math.min(state.minIdx, Math.max(0, state.length - size));
            state.maxIdx = state.minIdx + size - 1;
          }
        } else {
          state.minIdx = 0;
          state.maxIdx = state.length - 1;
        }
        updateLabel();
        updateThumb();
      }
      emit();
    }

    function getWindow() {
      return { min: state.minIdx, max: state.maxIdx, length: state.length };
    }

    // Показывается ли сейчас весь период целиком (максимальное уменьшение).
    // Используется для отключения чёрной окантовки столбиков.
    function isFullPeriod() {
      return state.stepIdx < 0;
    }

    chart._molvestZoom = {
      setData: setData,
      reset: reset,
      getWindow: getWindow,
      setStep: setStep,
      isFullPeriod: isFullPeriod,
    };
    return chart._molvestZoom;
  }

  function getApi(chart) {
    return chart && chart._molvestZoom;
  }

  window.MolvestZoom = {
    attach: attach,
    get: getApi,
  };
})(window);
