/* Псевдо-3D столбцы для диаграмм Chart.js (проекция: фронтальная + верхняя
   и правая грани), запас по оси Y 20% сверху, вспомогательные утилиты.

   Подключение:
     <script src=".../chart3d.js"></script>
     new Chart(ctx, {
       ...,
       options: {
         plugins: {
           molvest3d: { enabled: true, depth: 9 },   // глобально для датасетов
         },
       },
       data: {
         datasets: [
           { ..., molvest3d: false },                // отказ от 3D для датасета
         ],
       },
     });

   Ось Y: Molvest3D.yAxisMax(max) — максимум + 20% запаса сверху, чтобы самый
   высокий столбец занимал ~80% высоты графика.
*/
(function (window) {
  'use strict';

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function hexToRgb(hex) {
    hex = String(hex || '#6c757d').replace('#', '');
    if (hex.length === 3) {
      hex = hex.split('').map(function (c) { return c + c; }).join('');
    }
    var n = parseInt(hex, 16);
    if (isNaN(n)) return { r: 108, g: 117, b: 125 };
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
  }

  // Светлее (percent > 0) или темнее (percent < 0). percent: -1..1
  function shade(hex, percent) {
    var rgb = hexToRgb(hex);
    var p = clamp(Math.abs(percent || 0), 0, 1);
    var t = percent < 0 ? 0 : 255;
    var nr = Math.round(rgb.r + (t - rgb.r) * p);
    var ng = Math.round(rgb.g + (t - rgb.g) * p);
    var nb = Math.round(rgb.b + (t - rgb.b) * p);
    return 'rgb(' + nr + ',' + ng + ',' + nb + ')';
  }

  // Максимум оси Y: значение + 40% запаса сверху (самый высокий столбец — ~71% высоты)
  function yAxisMax(max) {
    if (!(max > 0)) return 1;
    return Math.max(1, Math.ceil(max * 1.4));
  }

  // Рисует один 3D-столбец. x — центр столбца, top/bottom — пиксели (canvas: y вниз)
  function draw3DBar(ctx, x, top, bottom, w, color, depth, outline) {
    if (bottom - top < 1 || w < 1) return;
    // Выдавливание 3D — пропорционально ширине столбца (без жёсткого минимума).
    // Для очень узких столбцов (максимальное уменьшение, «Весь период») 3D-грани
    // не рисуем вообще — только плоский непрозрачный столбец: иначе выдавливание
    // накладывается на соседние столбцы, и график выглядит полупрозрачным
    // (видно соседний столбец сквозь текущий).
    var d = Math.min(depth || 8, w * 0.8);
    if (d < 2) {
      // плоский непрозрачный столбец без 3D-граней
      ctx.fillStyle = color;
      ctx.fillRect(x - w / 2, top, w, bottom - top);
      if (outline !== false && w >= 3) {
        ctx.strokeStyle = 'rgba(0,0,0,.75)';
        ctx.lineWidth = 1;
        ctx.strokeRect(x - w / 2 + .5, top + .5, w - 1, Math.max(0, bottom - top - 1));
      }
      return;
    }
    var dx = d * 0.75;
    var dy = d * 0.75;
    // Лёгкое затемнение/осветление граней 3D (без ухода в белый/чёрный —
    // столбцы остаются насыщенными и непрозрачными)
    var light = shade(color, 0.12);
    var dark = shade(color, -0.18);

    // правая грань (тёмная)
    ctx.fillStyle = dark;
    ctx.beginPath();
    ctx.moveTo(x + w / 2, top);
    ctx.lineTo(x + w / 2 + dx, top - dy);
    ctx.lineTo(x + w / 2 + dx, bottom - dy);
    ctx.lineTo(x + w / 2, bottom);
    ctx.closePath();
    ctx.fill();

    // верхняя грань (чуть светлее)
    ctx.fillStyle = light;
    ctx.beginPath();
    ctx.moveTo(x - w / 2, top);
    ctx.lineTo(x + w / 2, top);
    ctx.lineTo(x + w / 2 + dx, top - dy);
    ctx.lineTo(x - w / 2 + dx, top - dy);
    ctx.closePath();
    ctx.fill();

    // фронтальная грань — СПЛОШНОЙ непрозрачный цвет продукта (без градиента,
    // чтобы столбцы не выглядели полупрозрачными/выцветшими)
    ctx.fillStyle = color;
    ctx.fillRect(x - w / 2, top, w, bottom - top);

    // тонкая чёрная окантовка по периметру столбца (чтобы слипшиеся
    // столбики были визуально различимы). Окантовку можно отключить
    // (opts.outline === false) — при максимальном уменьшении графика
    // («Весь период»), когда столбики очень узкие, окантовка только
    // чернит график.
    if (outline !== false && w >= 3) {
      ctx.strokeStyle = 'rgba(0,0,0,.75)';
      ctx.lineWidth = 1;
      // фронтальная грань
      ctx.strokeRect(x - w / 2 + .5, top + .5, w - 1, Math.max(0, bottom - top - 1));
      // верхняя грань (контур «крышки»)
      ctx.beginPath();
      ctx.moveTo(x - w / 2, top);
      ctx.lineTo(x + w / 2, top);
      ctx.lineTo(x + w / 2 + dx, top - dy);
      ctx.lineTo(x - w / 2 + dx, top - dy);
      ctx.closePath();
      ctx.stroke();
    }
  }

  var plugin = {
    id: 'molvest3d',
    defaults: { enabled: false, depth: 8, outline: true },

    afterDatasetDraw: function (chart, args, opts) {
      var dataset = chart.data.datasets[args.index];
      if (!dataset) return;
      var o = opts || {};
      if (o.enabled !== true) return;        // глобально выключено
      if (dataset.molvest3d === false) return; // датасет отказался от 3D

      var meta = args.meta;
      var ctx = chart.ctx;
      var depth = o.depth || 8;
      var outline = o.outline;
      var elems = meta.data || [];
      for (var i = 0; i < elems.length; i++) {
        var el = elems[i];
        if (!el || el.skip) continue;
        var x = el.x;
        var top = el.y;
        var bottom = el.base;
        if (top === bottom) continue; // нулевое значение — 3D не рисуем
        var w = Math.max(1, el.width || 8);
        var color = (el.options && el.options.backgroundColor) || '#6c757d';
        draw3DBar(ctx, x, top, bottom, w, color, depth, outline);
      }
    },

    // Чёрная окантовка по периметру каждого столбика рисуется ПОСЛЕ всех
    // столбиков: при вплотную стоящих столбцах обычная обводка каждого
    // столбика перекрывается соседним. Здесь проходим по всем датасетам
    // (продукция + простой) и обводим левую/правую/нижнюю грани.
    // Окантовку можно отключить (opts.outline === false) — при максимальном
    // уменьшении графика («Весь период») она не рисуется, чтобы не чернить
    // график.
    afterDatasetsDraw: function (chart) {
      var o = (chart.options && chart.options.plugins && chart.options.plugins.molvest3d) || {};
      if (o.enabled !== true) return;    // плагин выключен — ничего не рисуем
      if (o.outline === false) return;
      var ctx = chart.ctx;
      ctx.save();
      ctx.strokeStyle = 'rgba(0,0,0,.85)';
      ctx.lineWidth = 1;
      for (var di = 0; di < chart.data.datasets.length; di++) {
        var meta = chart.getDatasetMeta(di);
        if (!meta || !meta.data) continue;
        var elems = meta.data;
        for (var i = 0; i < elems.length; i++) {
          var el = elems[i];
          if (!el || el.skip) continue;
          var top = el.y;
          var bottom = el.base;
          if (top === bottom) continue; // нулевой столбец не обводим
          var w = el.width || 8;
          if (w < 3) continue; // слишком узкий столбец — без окантовки
          var x0 = el.x - w / 2;
          var x1 = el.x + w / 2;
          ctx.beginPath();
          ctx.moveTo(x0 + .5, top); ctx.lineTo(x0 + .5, bottom);   // левая
          ctx.moveTo(x1 - .5, top); ctx.lineTo(x1 - .5, bottom);   // правая
          ctx.moveTo(x0 + .5, bottom - .5); ctx.lineTo(x1 - .5, bottom - .5); // низ
          ctx.stroke();
        }
      }
      ctx.restore();
    },
  };

  window.Molvest3D = {
    plugin: plugin,
    draw3DBar: draw3DBar,
    shade: shade,
    yAxisMax: yAxisMax,
    hexToRgb: hexToRgb,
  };
})(window);
