/**
 * Mag SPA navigation — HTMX boost + Alpine re-init.
 * Swaps #main-content; syncs title, flash, page CSS/JS; re-runs Chart.js scripts.
 */
(function (window, document) {
  'use strict';

  var EXCLUDE_PATH_RE = /\/stocks\/(caisse\/|nouveau-panier|Article\/\d+\/ajouter_au_panier)|\/mag\/chat|\/authentification\/(Se-connecter|deconnexion|logout)/i;
  var EXCLUDE_URL_NAMES = {
    caissiere: 1,
    paniers: 1,
    add_panier: 1,
    add_panier_proforma: 1,
    ecom_chat_inbox: 1,
    historique_chat_inbox: 1,
    deconnexion: 1,
  };

  function pathOf(href) {
    try {
      return new URL(href, window.location.origin).pathname;
    } catch (e) {
      return href || '';
    }
  }

  function shouldExcludeUrl(href) {
    if (!href || href === '#' || href.indexOf('javascript:') === 0) return true;
    var path = pathOf(href);
    if (EXCLUDE_PATH_RE.test(path) || EXCLUDE_PATH_RE.test(href)) return true;
    /* Exports Excel/PDF (pas d’extension dans l’URL Django) */
    if (/\/export\//i.test(path) || /\/export-/i.test(path) || /export[_-]/i.test(path)) return true;
    if (/\.(xlsx?|pdf|csv|zip|png|jpe?g|gif|webp)(\?|$)/i.test(href)) return true;
    if (/[?&](export|download)=/i.test(href)) return true;
    return false;
  }

  function markExclusions(root) {
    var scope = root || document;
    scope.querySelectorAll('a[href]').forEach(function (a) {
      if (a.getAttribute('hx-boost') === 'false' || a.getAttribute('data-hx-boost') === 'false') return;
      if (a.target === '_blank' || a.hasAttribute('download')) {
        a.setAttribute('hx-boost', 'false');
        return;
      }
      if (a.getAttribute('data-toggle') === 'modal' || a.getAttribute('data-bs-toggle') === 'modal') {
        a.setAttribute('hx-boost', 'false');
        return;
      }
      if (shouldExcludeUrl(a.getAttribute('href'))) {
        a.setAttribute('hx-boost', 'false');
      }
    });
    scope.querySelectorAll('form').forEach(function (form) {
      if (form.getAttribute('hx-boost') === 'false') return;
      var action = form.getAttribute('action') || window.location.href;
      if (shouldExcludeUrl(action) || form.enctype === 'multipart/form-data') {
        form.setAttribute('hx-boost', 'false');
      }
      if (form.classList.contains('js-no-spa') || form.hasAttribute('data-no-spa')) {
        form.setAttribute('hx-boost', 'false');
      }
    });
  }

  function nprogressStart() {
    if (window.NProgress) window.NProgress.start();
    document.documentElement.classList.add('mag-spa-loading');
  }

  function nprogressDone() {
    if (window.NProgress) window.NProgress.done();
    document.documentElement.classList.remove('mag-spa-loading');
    var loader = document.querySelector('.page-loader-wrapper');
    if (loader) {
      loader.style.display = 'none';
      loader.classList.add('mag-spa-loader-hidden');
    }
  }

  function updateTitle(doc) {
    if (doc && doc.title) document.title = doc.title;
  }

  function syncFlash(doc) {
    if (!doc) return;
    var incoming = doc.getElementById('magFlashMessages');
    var existing = document.getElementById('magFlashMessages');
    if (existing) existing.remove();
    if (!incoming) return;
    var clone = incoming.cloneNode(true);
    document.body.insertBefore(clone, document.body.firstChild);
    clone.querySelectorAll('.ecom-flash-toast').forEach(function (toast) {
      var closeBtn = toast.querySelector('.ecom-flash-toast-close');
      function dismiss() {
        if (!toast || toast.classList.contains('is-leaving')) return;
        toast.classList.add('is-leaving');
        setTimeout(function () {
          if (toast.parentNode) toast.parentNode.removeChild(toast);
          if (clone && !clone.children.length && clone.parentNode) {
            clone.parentNode.removeChild(clone);
          }
        }, 320);
      }
      if (closeBtn) closeBtn.addEventListener('click', dismiss);
      setTimeout(dismiss, 5000);
    });
  }

  function syncPageStyles(doc) {
    document.querySelectorAll('link[data-mag-spa-css]').forEach(function (el) {
      el.remove();
    });
    if (!doc || !doc.head) return;
    doc.head.querySelectorAll('link[rel="stylesheet"]').forEach(function (link) {
      var href = link.getAttribute('href');
      if (!href) return;
      if (document.querySelector('link[rel="stylesheet"][href="' + href + '"]')) return;
      var injected = document.createElement('link');
      injected.rel = 'stylesheet';
      injected.href = href;
      injected.setAttribute('data-mag-spa-css', '1');
      document.head.appendChild(injected);
    });
  }

  function destroyCharts(root) {
    if (typeof window.Chart === 'undefined' || typeof window.Chart.getChart !== 'function') return;
    (root || document).querySelectorAll('canvas').forEach(function (canvas) {
      try {
        var chart = window.Chart.getChart(canvas);
        if (chart) chart.destroy();
      } catch (e) { /* ignore */ }
    });
  }

  /**
   * Re-exécute les <script> dans l’ordre (attend les src externes avant le suivant).
   * Indispensable pour Chart.js puis les scripts inline du dashboard.
   */
  function executeScriptsSequential(source, mount, done) {
    /* HTMX 2 retire les <script> du fragment inséré : on les lit dans la réponse parsée (source)
       et on en ajoute des copies exécutables dans le DOM vivant (mount). */
    if (!source || !mount) {
      if (done) done();
      return;
    }
    var scripts = Array.prototype.slice.call(source.querySelectorAll('script'));
    var i = 0;

    function next() {
      if (i >= scripts.length) {
        if (done) done();
        return;
      }
      var oldScript = scripts[i++];
      var s = document.createElement('script');
      Array.from(oldScript.attributes).forEach(function (attr) {
        if (attr.name === 'async' || attr.name === 'defer') return;
        s.setAttribute(attr.name, attr.value);
      });
      s.setAttribute('data-mag-spa-page', '1');
      s.async = false;

      var type = (oldScript.getAttribute('type') || '').toLowerCase();
      if (type && type !== 'text/javascript' && type !== 'application/javascript' && type !== 'module') {
        next();
        return;
      }

      if (oldScript.src) {
        var src = oldScript.getAttribute('src') || oldScript.src;
        /* Ne pas recharger Chart.js s’il est déjà global */
        if (/chart\.js/i.test(src) && typeof window.Chart !== 'undefined') {
          next();
          return;
        }
        s.onload = function () { next(); };
        s.onerror = function () { next(); };
        s.src = src;
        mount.appendChild(s);
      } else {
        /* Bloc {} : isole const/let entre deux visites sans masquer les function globales (onclick). */
        var code = oldScript.textContent || '';
        s.textContent = type === 'module' ? code : '{\n' + code + '\n}';
        mount.appendChild(s);
        next();
      }
    }

    next();
  }

  function syncPageScripts(doc, done) {
    var slot = document.getElementById('mag-page-scripts');
    if (!slot) {
      if (done) done();
      return;
    }
    var incoming = doc ? doc.getElementById('mag-page-scripts') : null;
    slot.innerHTML = '';
    if (!incoming) {
      if (done) done();
      return;
    }
    executeScriptsSequential(incoming, slot, done);
  }

  function reinitAlpine(el) {
    if (!window.Alpine || typeof window.Alpine.initTree !== 'function') return;
    try {
      window.Alpine.initTree(el || document.body);
    } catch (e) { /* ignore */ }
  }

  function highlightActiveNav() {
    var path = window.location.pathname;
    document.querySelectorAll('.mag-nav-dropdown-link, .box-menu a[href]').forEach(function (a) {
      var href = a.getAttribute('href');
      if (!href || href.indexOf('javascript:') === 0) return;
      try {
        var p = pathOf(href);
        if (p === path) a.classList.add('is-active');
        else a.classList.remove('is-active');
      } catch (e) { /* ignore */ }
    });
  }

  function parseDoc(xhr) {
    if (!xhr || !xhr.responseText) return null;
    try {
      return new DOMParser().parseFromString(xhr.responseText, 'text/html');
    } catch (e) {
      return null;
    }
  }

  function isHtmlResponse(xhr) {
    if (!xhr) return true;
    var ct = (xhr.getResponseHeader('Content-Type') || '').toLowerCase();
    if (!ct) return true;
    return ct.indexOf('text/html') !== -1 || ct.indexOf('application/xhtml') !== -1;
  }

  function forceDownloadNavigation(url) {
    nprogressDone();
    if (url) window.location.href = url;
  }

  function finishNavigation(target, doc) {
    markExclusions(document);
    if (target) reinitAlpine(target);
    highlightActiveNav();
    document.dispatchEvent(new CustomEvent('mag:navigated', {
      detail: { path: window.location.pathname, target: target, doc: doc },
    }));
    nprogressDone();
  }

  function cleanupModals() {
    if (window.jQuery && window.jQuery.fn && window.jQuery.fn.modal) {
      try { window.jQuery('.modal.show').modal('hide'); } catch (e) { /* ignore */ }
    }
    document.querySelectorAll('.modal-backdrop').forEach(function (el) { el.remove(); });
    document.body.classList.remove('modal-open');
    document.body.style.removeProperty('padding-right');
    document.body.style.removeProperty('overflow');
  }

  /* Réponse parsée en attente entre afterSwap et afterSettle */
  var pendingDoc = null;

  function onAfterSwap(evt) {
    var xhr = evt && evt.detail && evt.detail.xhr;
    cleanupModals();
    var doc = parseDoc(xhr);
    updateTitle(doc);
    syncFlash(doc);
    syncPageStyles(doc);
    pendingDoc = doc;
  }

  /**
   * Les scripts tournent après le settle HTMX, pas après le swap : quand la page revient sur
   * elle-même (Réinitialiser, Filtre), les <canvas> gardent les mêmes id et HTMX leur remet
   * leurs attributs d'origine au settle, ce qui retire width/height posés par Chart.js et
   * efface les courbes déjà dessinées.
   */
  function onAfterSettle() {
    if (pendingDoc === null) return;
    var doc = pendingDoc;
    pendingDoc = null;
    /* outerHTML : detail.target est l'ancien nœud détaché, on relit le nouveau */
    var target = document.getElementById('main-content');

    /* 1) scripts du slot extra_js, 2) scripts de #main-content (Chart.js puis courbes) */
    var incomingMain = doc ? doc.getElementById('main-content') : null;
    syncPageScripts(doc, function () {
      if (target && incomingMain) {
        executeScriptsSequential(incomingMain, target, function () {
          finishNavigation(target, doc);
        });
      } else {
        finishNavigation(target, doc);
      }
    });
  }

  function onBeforeRequest(evt) {
    var elt = evt && evt.detail && evt.detail.elt;
    if (elt) {
      if (elt.tagName === 'A') {
        var href = elt.getAttribute('href');
        if (href && href.indexOf('javascript:') !== 0 && href !== '#' && shouldExcludeUrl(href)) {
          evt.preventDefault();
          nprogressDone();
          window.location.href = href;
          return;
        }
      }
      if (elt.tagName === 'FORM') {
        var action = elt.getAttribute('action') || window.location.href;
        if (shouldExcludeUrl(action) || elt.enctype === 'multipart/form-data' ||
            elt.classList.contains('js-no-spa') || elt.hasAttribute('data-no-spa')) {
          evt.preventDefault();
          nprogressDone();
          if (typeof elt.submit === 'function') {
            HTMLFormElement.prototype.submit.call(elt);
          }
          return;
        }
      }
    }
    nprogressStart();
  }

  function onBeforeSwap(evt) {
    var xhr = evt && evt.detail && evt.detail.xhr;
    if (xhr && xhr.status >= 400) {
      nprogressDone();
      return;
    }
    /* Réponse fichier (Excel/PDF) : ne pas injecter dans le DOM */
    if (xhr && !isHtmlResponse(xhr)) {
      evt.detail.shouldSwap = false;
      forceDownloadNavigation(xhr.responseURL || window.location.href);
      return;
    }
    /* Page d'un autre gabarit (boutique, support…) : pas de #main-content à sélectionner,
       HTMX viderait la zone. On bascule en navigation classique. */
    if (xhr && xhr.responseText && !/id=["']main-content["']/.test(xhr.responseText)) {
      evt.detail.shouldSwap = false;
      forceDownloadNavigation(xhr.responseURL || window.location.href);
      return;
    }
    cleanupModals();
    destroyCharts(document.getElementById('main-content'));
  }

  function onHistoryRestore() {
    /* historyCacheSize = 0 : le retour arrière recharge la page, rien à rejouer ici */
    markExclusions(document);
    highlightActiveNav();
  }

  function init() {
    if (window.htmx && window.htmx.config) {
      /* Scripts exécutés par executeScriptsSequential (ordre + attente de Chart.js) */
      window.htmx.config.allowScriptTags = false;
      /* Retour arrière = rechargement complet : le snapshot HTMX perd les graphiques et les listeners */
      window.htmx.config.historyCacheSize = 0;
      window.htmx.config.refreshOnHistoryMiss = true;
    }
    if (window.NProgress) {
      NProgress.configure({ showSpinner: false, trickleSpeed: 180, minimum: 0.08 });
    }
    markExclusions(document);
    highlightActiveNav();

    document.body.addEventListener('htmx:configRequest', function (evt) {
      var meta = document.querySelector('meta[name="csrf-token"]');
      if (meta && meta.content) {
        evt.detail.headers['X-CSRFToken'] = meta.content;
      }
    });
    document.body.addEventListener('htmx:beforeRequest', onBeforeRequest);
    document.body.addEventListener('htmx:beforeSwap', onBeforeSwap);
    document.body.addEventListener('htmx:afterSwap', onAfterSwap);
    document.body.addEventListener('htmx:afterSettle', onAfterSettle);
    document.body.addEventListener('htmx:historyRestore', onHistoryRestore);
    document.body.addEventListener('htmx:responseError', nprogressDone);
    document.body.addEventListener('htmx:sendError', nprogressDone);
    document.body.addEventListener('htmx:timeout', nprogressDone);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.MagSpaNav = {
    markExclusions: markExclusions,
    shouldExcludeUrl: shouldExcludeUrl,
    executeScriptsSequential: executeScriptsSequential,
    EXCLUDE_URL_NAMES: EXCLUDE_URL_NAMES,
  };
})(window, document);
