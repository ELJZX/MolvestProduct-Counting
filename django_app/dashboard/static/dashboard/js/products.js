/* Продукция: редактирование в диалоговом окне (карандаш).
   При закрытии окна с несохранёнными изменениями предлагается сохранить. */
(function () {
  'use strict';

  const modalEl = document.getElementById('productModal');
  if (!modalEl) return;
  const body = document.getElementById('productModalBody');
  const btnSave = document.getElementById('btnModalSave');

  const modal = new bootstrap.Modal(modalEl);
  let currentPk = null;
  let dirty = false;
  let saved = false;
  let form = null;

  function getCookie(name) {
    const m = document.cookie.match('(^|;)\\s*' + name + '=([^;]*)');
    return m ? decodeURIComponent(m[2]) : '';
  }

  function markDirty() { dirty = true; }
  function bindFormEvents(f) {
    if (!f) return;
    f.querySelectorAll('input, select, textarea').forEach((el) => {
      ['input', 'change'].forEach((ev) => el.addEventListener(ev, markDirty));
    });
  }

  async function openModal(pk) {
    currentPk = pk;
    dirty = false;
    saved = false;
    body.innerHTML = '<div class="text-center text-muted py-4">Загрузка…</div>';
    modal.show();
    try {
      const resp = await fetch('/products/' + pk + '/edit/modal/', { headers: { 'Accept': 'text/html' } });
      if (!resp.ok) {
        body.innerHTML = '<div class="alert alert-danger">Не удалось загрузить форму (статус ' + resp.status + ').</div>';
        return;
      }
      body.innerHTML = await resp.text();
      form = document.getElementById('productModalForm');
      bindFormEvents(form);
      // повторно выполняем встроенный скрипт RGB-сетки
      body.querySelectorAll('script').forEach((sc) => {
        const ns = document.createElement('script');
        ns.textContent = sc.textContent;
        sc.parentNode.replaceChild(ns, sc);
      });
    } catch (e) {
      body.innerHTML = '<div class="alert alert-danger">Ошибка загрузки: ' + e.message + '</div>';
    }
  }

  function collectErrors(errors) {
    if (!errors) return '';
    const msgs = [];
    Object.keys(errors).forEach((field) => {
      (errors[field] || []).forEach((e) => msgs.push(field + ': ' + e.message));
    });
    return msgs.join('<br>');
  }

  async function saveForm() {
    if (!form || !currentPk) return false;
    const fd = new FormData(form);
    try {
      const resp = await fetch('/products/' + currentPk + '/edit/modal/', {
        method: 'POST',
        body: fd,
        headers: { 'X-CSRFToken': getCookie('csrftoken') },
      });
      const data = await resp.json();
      if (data.ok) {
        saved = true;
        dirty = false;
        modal.hide();
        // обновляем строку на странице
        try { window.location.reload(); } catch (e) { /* ignore */ }
        return true;
      }
      // ошибки валидации — показываем в теле модального окна
      let errHtml = '<div class="alert alert-danger">' + collectErrors(data.errors) + '</div>';
      body.insertAdjacentHTML('afterbegin', errHtml);
      return false;
    } catch (e) {
      body.insertAdjacentHTML('afterbegin', '<div class="alert alert-danger">Ошибка сохранения: ' + e.message + '</div>');
      return false;
    }
  }

  document.querySelectorAll('.btn-edit-product').forEach((btn) => {
    btn.addEventListener('click', () => openModal(parseInt(btn.dataset.pk, 10)));
  });

  btnSave.addEventListener('click', () => saveForm());

  // При попытке закрыть окно с несохранёнными изменениями — предложить сохранить
  modalEl.addEventListener('hide.bs.modal', (e) => {
    if (!dirty || saved) return;
    e.preventDefault();
    const choice = window.confirm('Сохранить изменения?');
    if (choice) {
      saveForm().then((ok) => { if (!ok) dirty = true; });
    } else {
      dirty = false;
      saved = true;
      modal.hide();
    }
  });
})();
