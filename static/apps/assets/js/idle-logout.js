/**
 * Déconnexion automatique après inactivité (boutique + magasin).
 *
 * - « Activité » = clic, touche, défilement, toucher, souris (limité à 1 relevé / 5 s).
 * - Partagé entre onglets via localStorage : agir dans un onglet garde les autres ouverts.
 * - Tant que l'utilisateur agit sans recharger de page, un « maintien » est envoyé au serveur
 *   (au plus une fois par minute) : le serveur reste la source de vérité (Userauths/idle_timeout.py).
 * - 2 min avant la fin : avertissement avec compte à rebours et bouton « Rester connecté ».
 *
 * Réglages sur la balise <script> : data-timeout (s), data-warning (s),
 * data-keepalive-url, data-logout-url.
 */
(function (window, document) {
  'use strict';

  if (window.__apIdleLogout) return;   // une seule instance (navigation fluide)
  window.__apIdleLogout = true;

  var script = document.currentScript;
  var cfg = script ? script.dataset : {};
  var TIMEOUT_MS = (parseInt(cfg.timeout, 10) || 1800) * 1000;
  var WARNING_MS = (parseInt(cfg.warning, 10) || 120) * 1000;
  var KEEPALIVE_URL = cfg.keepaliveUrl || '';
  var LOGOUT_URL = cfg.logoutUrl || '/';
  var KEEPALIVE_EVERY_MS = 60 * 1000;
  var STORAGE_KEY = 'ap_idle_last_activity';
  var MOVE_THROTTLE_MS = 5000;

  /* setInterval/setTimeout natifs : ecom-spa-nav.js ne doit jamais les nettoyer */
  var setTimer = window.setTimeout.bind(window);
  var setRepeat = window.setInterval.bind(window);

  var lastLocal = Date.now();
  var lastPing = Date.now();
  var lastMove = 0;
  var loggingOut = false;
  var dialog = null;
  var countdownEl = null;

  function readShared() {
    try {
      var v = parseInt(window.localStorage.getItem(STORAGE_KEY), 10);
      return Number.isFinite(v) ? v : 0;
    } catch (e) {
      return 0;
    }
  }

  function lastActivity() {
    return Math.max(lastLocal, readShared());
  }

  function markActivity() {
    if (loggingOut) return;
    lastLocal = Date.now();
    try { window.localStorage.setItem(STORAGE_KEY, String(lastLocal)); } catch (e) { /* ignore */ }
    hideWarning();
    if (lastLocal - lastPing >= KEEPALIVE_EVERY_MS) keepAlive();
  }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function keepAlive() {
    if (!KEEPALIVE_URL || !window.fetch) return;
    lastPing = Date.now();
    fetch(KEEPALIVE_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
    }).then(function (resp) {
      if (resp.status === 401) logout();
    }).catch(function () { /* réseau : on réessaiera au prochain geste */ });
  }

  function logout() {
    if (loggingOut) return;
    loggingOut = true;
    var sep = LOGOUT_URL.indexOf('?') === -1 ? '?' : '&';
    window.location.href = LOGOUT_URL + sep + 'inactivite=1';
  }

  /* ---------- Avertissement ---------- */
  function injectStyles() {
    if (document.getElementById('ap-idle-style')) return;
    var css = [
      '.ap-idle-backdrop{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;padding:16px;background:rgba(15,23,42,.55);}',
      '.ap-idle-box{width:100%;max-width:400px;padding:24px 22px 20px;border-radius:14px;background:#fff;box-shadow:0 24px 60px rgba(15,23,42,.3);font-family:inherit;text-align:center;color:#111827;}',
      '.ap-idle-icon{width:52px;height:52px;margin:0 auto 12px;display:flex;align-items:center;justify-content:center;border-radius:50%;background:#fff7ed;color:#ea580c;font-size:24px;}',
      '.ap-idle-title{margin:0 0 8px;font-size:19px;font-weight:800;line-height:1.3;}',
      '.ap-idle-text{margin:0 0 6px;font-size:14px;line-height:1.5;color:#4b5563;}',
      '.ap-idle-count{display:block;margin:6px 0 18px;font-size:30px;font-weight:800;color:#ea580c;font-variant-numeric:tabular-nums;}',
      '.ap-idle-actions{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;}',
      '.ap-idle-btn{min-width:140px;padding:10px 16px;border-radius:8px;border:1px solid #f97316;font-size:14px;font-weight:700;cursor:pointer;line-height:1.2;}',
      '.ap-idle-btn--stay{background:#f97316;color:#fff;}',
      '.ap-idle-btn--stay:hover{background:#ea580c;}',
      '.ap-idle-btn--out{background:#fff;color:#c2410c;}',
      '.ap-idle-btn--out:hover{background:#fff7ed;}',
    ].join('');
    var style = document.createElement('style');
    style.id = 'ap-idle-style';
    style.textContent = css;
    document.head.appendChild(style);
  }

  function showWarning() {
    if (dialog) return;
    injectStyles();
    dialog = document.createElement('div');
    dialog.className = 'ap-idle-backdrop';
    dialog.setAttribute('role', 'alertdialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'ap-idle-title');
    dialog.innerHTML =
      '<div class="ap-idle-box">' +
        '<div class="ap-idle-icon" aria-hidden="true">&#9203;</div>' +
        '<h2 class="ap-idle-title" id="ap-idle-title">Êtes-vous toujours là&nbsp;?</h2>' +
        '<p class="ap-idle-text">Sans action de votre part, vous serez déconnecté pour inactivité dans&nbsp;:</p>' +
        '<span class="ap-idle-count" aria-live="polite"></span>' +
        '<div class="ap-idle-actions">' +
          '<button type="button" class="ap-idle-btn ap-idle-btn--out" data-idle-out>Se déconnecter</button>' +
          '<button type="button" class="ap-idle-btn ap-idle-btn--stay" data-idle-stay>Rester connecté</button>' +
        '</div>' +
      '</div>';
    countdownEl = dialog.querySelector('.ap-idle-count');
    dialog.querySelector('[data-idle-stay]').addEventListener('click', function () {
      markActivity();
      keepAlive();
    });
    dialog.querySelector('[data-idle-out]').addEventListener('click', logout);
    document.body.appendChild(dialog);
    dialog.querySelector('[data-idle-stay]').focus();
  }

  function hideWarning() {
    if (!dialog) return;
    dialog.remove();
    dialog = null;
    countdownEl = null;
  }

  function formatRemaining(ms) {
    var s = Math.max(0, Math.ceil(ms / 1000));
    var m = Math.floor(s / 60);
    s = s % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function tick() {
    if (loggingOut) return;
    var idle = Date.now() - lastActivity();
    if (idle >= TIMEOUT_MS) {
      logout();
      return;
    }
    if (idle >= TIMEOUT_MS - WARNING_MS) {
      showWarning();
      if (countdownEl) countdownEl.textContent = formatRemaining(TIMEOUT_MS - idle);
    } else {
      hideWarning();   // un autre onglet a repris l'activité
    }
  }

  /* ---------- Écoute de l'activité ---------- */
  ['mousedown', 'keydown', 'touchstart', 'wheel', 'scroll'].forEach(function (type) {
    window.addEventListener(type, function () {
      /* Pendant l'avertissement, seul « Rester connecté » (ou une touche) prolonge */
      if (dialog && type !== 'keydown') return;
      markActivity();
    }, { passive: true, capture: true });
  });
  window.addEventListener('mousemove', function () {
    if (dialog) return;
    var now = Date.now();
    if (now - lastMove < MOVE_THROTTLE_MS) return;
    lastMove = now;
    markActivity();
  }, { passive: true, capture: true });
  window.addEventListener('storage', function (e) {
    if (e.key === STORAGE_KEY) tick();
  });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) tick();   // retour sur un onglet resté en veille
  });

  markActivity();
  setRepeat(tick, 1000);
  setTimer(tick, 0);
})(window, document);
