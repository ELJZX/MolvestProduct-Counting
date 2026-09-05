/* Эмулятор линии: проверка подключения к Django, выбор линий и продукта,
   клик — насчёт продукции через тот же API, что использует контроллер ОВЕН. */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const connStatus = $('connStatus');
  const connDetail = $('connDetail');
  const djangoUrlEl = $('djangoUrl');
  const btnCheck = $('btnCheck');
  const btnRefresh = $('btnRefresh');
  const linesList = $('linesList');
  const linesSummary = $('linesSummary');
  const btnSelectAll = $('btnSelectAll');
  const btnSelectNone = $('btnSelectNone');
  const productFilter = $('productFilter');
  const productSelect = $('productSelect');
  const productInfo = $('productInfo');
  const stepInput = $('stepInput');
  const linesWrap = $('linesWrap');

  let lines = [];
  let products = [];
  let selected = {}; // lineId -> true/false
  let djangoUrl = '';

  // ------------------------------------------------------------------
  function setConn(state, text, detail) {
    connStatus.className = 'conn conn-' + state;
    connStatus.textContent = text;
    connDetail.className = 'conn-detail' + (state === 'err' ? ' err' : (state === 'ok' ? ' ok' : ''));
    connDetail.textContent = detail || '';
  }

  function toast(text, kind) {
    let el = document.getElementById('toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast';
      el.className = 'toast';
      document.body.appendChild(el);
    }
    el.textContent = text;
    el.className = 'toast show' + (kind ? ' ' + kind : '');
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.className = 'toast'; }, 2600);
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function apiGet(path) {
    const resp = await fetch(path);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.ok) throw new Error((data && data.error) || ('HTTP ' + resp.status));
    return data;
  }

  // ------------------------------------------------------------------
  // Проверка подключения к основному серверу проекта
  // ------------------------------------------------------------------
  async function checkConnection(showDetail) {
    setConn('unknown', 'проверка…', 'Запрос к серверу Django…');
    try {
      const cfg = await apiGet('api/config');
      djangoUrl = cfg.django_url || '';
      djangoUrlEl.textContent = djangoUrl || '—';
      const health = await apiGet('api/health');
      const detail = 'Сервер доступен: ' + djangoUrl + ' · линий в системе: ' + (health.lines != null ? health.lines : '?') +
        ' · время сервера: ' + (health.time ? String(health.time).replace('T', ' ').slice(0, 19) : '');
      setConn('ok', 'подключено', detail);
      loadLines();
      loadProducts();
      return true;
    } catch (e) {
      setConn('err', 'нет подключения',
        'Не удалось связаться с сервером Django (' + (djangoUrl || 'http://127.0.0.1:8000') + '): ' + e.message +
        '. Убедитесь, что сервер запущен (python manage.py runserver) и нажмите «Проверить подключение».');
      linesWrap.innerHTML = '<div class="empty">Нет подключения к серверу проекта. Проверьте подключение выше.</div>';
      return false;
    }
  }

  // ------------------------------------------------------------------
  // Линии
  // ------------------------------------------------------------------
  function renderLineList() {
    if (!lines.length) {
      linesList.innerHTML = '<div class="hint" style="padding:.5rem">Линии не найдены. Создайте их в системе (python manage.py seed_data).</div>';
      return;
    }
    linesList.innerHTML = lines.map((l) =>
      '<label class="line-item' + (selected[l.id] ? ' selected' : '') + '" data-id="' + l.id + '">' +
      '<input type="checkbox" class="cb" ' + (selected[l.id] ? 'checked' : '') + '>' +
      '<span>' +
      '<div class="li-name">Л' + l.number + ' — ' + l.name + '</div>' +
      '<div class="li-meta">' + (l.shop_code || '') + ' · контроллер: ' + l.controller_id + '</div>' +
      '</span>' +
      '<span class="li-status">' +
      (l.product_code
        ? '<span class="badge badge-ok">' + l.product_code + '</span>'
        : '<span class="badge badge-off">нет продукта</span>') +
      '</span>' +
      '</label>'
    ).join('');
    const selCount = Object.keys(selected).filter((k) => selected[k]).length;
    linesSummary.textContent = selCount > 0
      ? ('Выбрано линий: ' + selCount + ' из ' + lines.length)
      : 'Выберите линии, по которым будет насчитываться продукция.';
    renderCards();
  }

  function toggleLine(id, on) {
    selected[id] = !!on;
    const item = linesList.querySelector('.line-item[data-id="' + id + '"]');
    if (item) {
      item.classList.toggle('selected', !!on);
      const cb = item.querySelector('.cb');
      if (cb) cb.checked = !!on;
    }
    renderLineList();
  }

  linesList.addEventListener('change', (ev) => {
    const item = ev.target.closest('.line-item');
    if (item) toggleLine(parseInt(item.dataset.id, 10), ev.target.checked);
  });

  btnSelectAll.addEventListener('click', () => {
    lines.forEach((l) => { selected[l.id] = true; });
    renderLineList();
  });
  btnSelectNone.addEventListener('click', () => {
    lines.forEach((l) => { selected[l.id] = false; });
    renderLineList();
  });

  function fmt(n) { return Number(n || 0).toLocaleString('ru-RU'); }
  function fmtDT(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    const pad = (x) => String(x).padStart(2, '0');
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function renderCards() {
    const sel = lines.filter((l) => selected[l.id]);
    if (!sel.length) {
      linesWrap.innerHTML = '<div class="empty">Выберите хотя бы одну линию в панели слева.</div>';
      return;
    }
    linesWrap.innerHTML = sel.map((l) =>
      '<div class="line-card" data-id="' + l.id + '" data-controller="' + l.controller_id + '" data-product="' + (l.product_code || '') + '">' +
        '<div class="line-head">' +
          '<div class="line-name">Л' + l.number + ' — ' + l.name + '</div>' +
          '<div class="line-shop">' + (l.shop_code || '') + '</div>' +
        '</div>' +
        '<div class="line-controller">контроллер: ' + l.controller_id + '</div>' +
        '<div class="line-product">' +
          (l.product_code
            ? '<span class="code">' + l.product_code + '</span>' + (l.product_name || '')
            : '<span class="hint">продукт не задан</span>') +
        '</div>' +
        '<div class="line-total"><span class="num" data-field="total">' + fmt(l.total_count) + '</span><span class="unit">шт. по заданию</span></div>' +
        '<div class="line-foot">' +
          '<div class="line-assignment">' + (l.assignment_started_at ? 'смена с ' + fmtDT(l.assignment_started_at) : 'задание не начато') + '</div>' +
          '<div class="line-btns">' +
            '<button class="switch-btn" title="Сменить код продукта (с вводом пин-кода)">Изменить код</button>' +
            '<button class="count-btn">Насчитать</button>' +
          '</div>' +
        '</div>' +
      '</div>'
    ).join('');
  }

  async function loadLines() {
    try {
      const data = await apiGet('api/lines');
      lines = data.lines || [];
      // новые линии по умолчанию выбраны
      lines.forEach((l) => { if (!(l.id in selected)) selected[l.id] = true; });
      renderLineList();
    } catch (e) {
      linesList.innerHTML = '<div class="hint" style="padding:.5rem">Ошибка загрузки линий: ' + e.message + '</div>';
    }
  }

  // ------------------------------------------------------------------
  // Продукты
  // ------------------------------------------------------------------
  function renderProductFilter() {
    const q = productFilter.value.trim().toLowerCase();
    const opts = products.filter((p) =>
      !q || p.name.toLowerCase().indexOf(q) !== -1 ||
      p.code.indexOf(q) !== -1 || (p.code_1c || '').toLowerCase().indexOf(q) !== -1
    );
    productSelect.innerHTML = opts.map((p) =>
      '<option value="' + p.code + '">' + p.code + ' — ' + p.name +
      (p.code_1c ? ' (1С: ' + p.code_1c + ')' : '') + '</option>'
    ).join('');
    if (!opts.length) {
      productSelect.innerHTML = '<option value="" disabled>Ничего не найдено</option>';
    }
    productSelect.selectedIndex = 0;
    updateProductInfo();
  }

  function updateProductInfo() {
    const code = productSelect.value;
    const p = products.find((x) => x.code === code);
    productInfo.textContent = p
      ? ('Выбран: ' + p.code + ' — ' + p.name + (p.code_1c ? ' · Код 1С: ' + p.code_1c : ''))
      : 'Выберите продукт из списка';
  }

  async function loadProducts() {
    try {
      const data = await apiGet('api/products');
      products = data.products || [];
      renderProductFilter();
    } catch (e) {
      productInfo.textContent = 'Не удалось загрузить справочник продукции: ' + e.message;
    }
  }

  function currentStep() {
    let v = parseInt(stepInput.value, 10);
    if (!(v >= 1)) v = 1;
    stepInput.value = v;
    return v;
  }

  // ------------------------------------------------------------------
  // Насчёт продукции
  // ------------------------------------------------------------------
  async function countOnCard(card) {
    const product = productSelect.value;
    if (!product) {
      toast('Сначала выберите продукт', 'err');
      return;
    }
    // Симулятор сам код продукта не меняет: насчитывать можно только тот
    // продукт, который уже стоит на линии
    const lineProduct = card.dataset.product || '';
    if (lineProduct !== product) {
      toast('Код продукции не соответствует', 'err');
      return;
    }
    const controllerId = card.dataset.controller;
    const delta = currentStep();
    card.classList.add('locked');
    const btn = card.querySelector('.count-btn');
    if (btn) btn.disabled = true;
    try {
      const resp = await fetch('api/count', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ controller_id: controllerId, product: product, delta: delta }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.ok) {
        throw new Error((data && data.error) || ('HTTP ' + resp.status));
      }
      const num = card.querySelector('[data-field="total"]');
      if (num) num.textContent = fmt(data.total_count);
      const prodEl = card.querySelector('.line-product');
      if (prodEl) {
        prodEl.innerHTML = '<span class="code">' + data.product + '</span>' + (data.line_name ? ' · +' + data.delta + ' шт.' : '');
      }
      toast('+' + data.delta + ' шт. по линии «' + data.line_name + '» (продукт ' + data.product + ')', 'ok');
      // обновляем список линий, чтобы счётчики были актуальными
      loadLines();
    } catch (e) {
      toast('Ошибка: ' + e.message, 'err');
    } finally {
      card.classList.remove('locked');
      if (btn) btn.disabled = false;
    }
  }

  // ------------------------------------------------------------------
  // Смена кода продукта (только пользователем, с вводом пин-кода)
  // ------------------------------------------------------------------
  const pinModal = document.getElementById('pinModal');
  const pinInput = document.getElementById('pinInput');
  const pinError = document.getElementById('pinError');
  const pinOk = document.getElementById('pinOk');
  const pinCancel = document.getElementById('pinCancel');
  const confirmModal = document.getElementById('confirmModal');
  const confirmText = document.getElementById('confirmText');
  const confirmOk = document.getElementById('confirmOk');
  const confirmCancel = document.getElementById('confirmCancel');

  let pendingCard = null;   // карточка линии, для которой меняем код
  let pendingPin = '';      // подтверждённый пин-код

  function showModal(modal) { if (modal) modal.hidden = false; }
  function hideModal(modal) { if (modal) modal.hidden = true; }

  function openPinDialog(card) {
    pendingCard = card;
    pendingPin = '';
    if (pinInput) pinInput.value = '';
    if (pinError) pinError.hidden = true;
    showModal(pinModal);
    if (pinInput) pinInput.focus();
  }

  function cancelSwitchOp() {
    toast('Операция отменена пользователем', 'warn');
    hideModal(pinModal);
    hideModal(confirmModal);
    pendingCard = null;
    pendingPin = '';
  }

  if (pinInput) {
    pinInput.addEventListener('input', () => {
      pinInput.value = pinInput.value.replace(/\D/g, '');
      if (pinError) pinError.hidden = true;
    });
    pinInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); if (pinOk) pinOk.click(); }
    });
  }
  if (pinCancel) pinCancel.addEventListener('click', cancelSwitchOp);
  if (confirmCancel) confirmCancel.addEventListener('click', cancelSwitchOp);
  // клик по подложке или Escape — отмена
  [pinModal, confirmModal].forEach((m) => {
    if (!m) return;
    m.addEventListener('click', (ev) => { if (ev.target === m) cancelSwitchOp(); });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && (!pinModal.hidden || !confirmModal.hidden)) cancelSwitchOp();
  });

  if (pinOk) {
    pinOk.addEventListener('click', async () => {
      if (!pendingCard) return;
      const product = productSelect.value;
      if (!product) { toast('Сначала выберите продукт', 'err'); return; }
      const pin = pinInput ? pinInput.value : '';
      if (!pin) {
        if (pinError) { pinError.textContent = 'Введите пин-код'; pinError.hidden = false; }
        return;
      }
      pinOk.disabled = true;
      try {
        const resp = await fetch('api/switch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            controller_id: pendingCard.dataset.controller,
            product_code: product,
            pin: pin,
            action: 'verify',
          }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.ok) {
          // Неверный пин-код — «Операция отклонена»
          if (pinError) {
            pinError.textContent = data.error || 'Операция отклонена';
            pinError.hidden = false;
          }
          return;
        }
        pendingPin = pin;
        const currentCode = data.current_code || pendingCard.dataset.product || '—';
        if (confirmText) {
          confirmText.innerHTML = 'Вы точно хотите изменить код продукта с «<b>' +
            escapeHtml(currentCode) + '</b>» на «<b>' + escapeHtml(product) + '</b>»?';
        }
        hideModal(pinModal);
        showModal(confirmModal);
      } catch (e) {
        if (pinError) { pinError.textContent = 'Ошибка: ' + e.message; pinError.hidden = false; }
      } finally {
        pinOk.disabled = false;
      }
    });
  }

  if (confirmOk) {
    confirmOk.addEventListener('click', async () => {
      if (!pendingCard || !pendingPin) return;
      const product = productSelect.value;
      confirmOk.disabled = true;
      try {
        const resp = await fetch('api/switch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            controller_id: pendingCard.dataset.controller,
            product_code: product,
            pin: pendingPin,
            action: 'confirm',
          }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.ok) {
          toast((data && data.error) || 'Не удалось изменить код продукта', 'err');
          return;
        }
        toast('Код продукта изменён на ' + (data.product || product), 'ok');
        hideModal(confirmModal);
        pendingCard = null;
        pendingPin = '';
        loadLines();
      } catch (e) {
        toast('Ошибка: ' + e.message, 'err');
      } finally {
        confirmOk.disabled = false;
      }
    });
  }

  linesWrap.addEventListener('click', (ev) => {
    const card = ev.target.closest('.line-card');
    if (!card || card.classList.contains('locked')) return;
    if (ev.target.closest('.switch-btn')) {
      openPinDialog(card);
      return;
    }
    countOnCard(card);
  });

  productFilter.addEventListener('input', renderProductFilter);
  productSelect.addEventListener('change', updateProductInfo);
  document.querySelectorAll('.btn-quick').forEach((b) => {
    b.addEventListener('click', () => { stepInput.value = b.dataset.step; });
  });

  // ------------------------------------------------------------------
  btnCheck.addEventListener('click', () => checkConnection(true));
  btnRefresh.addEventListener('click', () => {
    checkConnection(false);
    loadLines();
    loadProducts();
  });

  // старт: проверка подключения + автопроверка раз в 30 секунд
  checkConnection(false);
  setInterval(() => {
    fetch('api/health').then((r) => {
      if (r.ok) {
        if (connStatus.className.indexOf('conn-err') !== -1) checkConnection(false);
      } else {
        setConn('err', 'нет подключения', 'Соединение с сервером проекта потеряно. Нажмите «Проверить подключение».');
      }
    }).catch(() => {
      setConn('err', 'нет подключения', 'Соединение с сервером проекта потеряно. Нажмите «Проверить подключение».');
    });
  }, 30000);
})();
