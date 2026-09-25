/**
 * Ecom SPA navigation — HTMX boost (même principe que mag-spa-nav.js).
 * Remplace #ecom-main ; synchronise titre, classes <body>, CSS de page, badges panier/favoris,
 * messages flash ; rejoue les scripts de page et réinitialise le thème (Swiper, nice-select…).
 *
 * Chargé SANS defer dans le <head>, avant htmx : il doit
 *  - installer la « portée page » avant l'exécution des scripts inline du corps ;
 *  - poser htmx.config avant que htmx ne traite la page (DOMContentLoaded).
 */
(function (window, document) {
  'use strict';

  /* ------------------------------------------------------------------ */
  /* 1. Portée « page » : écouteurs et minuteurs posés par les scripts   */
  /*    de page, retirés à la navigation suivante (sinon ils s'empilent) */
  /* ------------------------------------------------------------------ */
  var scope = { depth: 0, listeners: [], intervals: [], timeouts: [] };
  var nativeSetTimeout = window.setTimeout;
  var nativeSetInterval = window.setInterval;
  var nativeClearTimeout = window.clearTimeout;
  var nativeClearInterval = window.clearInterval;
  var ONE_SHOT = { DOMContentLoaded: 1, load: 1 };

  function inScope() {
    return scope.depth > 0;
  }

  function runInScope(fn, ctx, args) {
    scope.depth++;
    try {
      return fn.apply(ctx, args || []);
    } finally {
      scope.depth--;
    }
  }

  /* Le dispatcher unique de jQuery ne doit jamais être retiré : il sert aussi au thème. */
  function isJqueryDispatcher(fn) {
    try {
      return /event\.dispatch/.test(Function.prototype.toString.call(fn));
    } catch (e) {
      return false;
    }
  }

  function patchTarget(target) {
    var add = target.addEventListener;
    target.addEventListener = function (type, fn, opts) {
      if (!inScope() || !fn || isJqueryDispatcher(fn)) {
        return add.call(this, type, fn, opts);
      }
      if (ONE_SHOT[type]) {
        var self = this;
        var call = typeof fn === 'function' ? fn : fn.handleEvent;
        var ctx = typeof fn === 'function' ? self : fn;
        var wrapped = function (ev) { return runInScope(call, ctx, [ev]); };
        var passed = type === 'load'
          ? document.readyState === 'complete'
          : document.readyState !== 'loading';
        if (passed) {
          /* Page rejouée : DOMContentLoaded / load ne reviendront pas, on appelle tout de suite */
          nativeSetTimeout(function () { wrapped.call(self, new Event(type)); }, 0);
          return undefined;
        }
        scope.listeners.push([self, type, wrapped, opts]);
        return add.call(self, type, wrapped, opts);
      }
      scope.listeners.push([this, type, fn, opts]);
      return add.call(this, type, fn, opts);
    };
  }

  patchTarget(window);
  patchTarget(document);

  window.setTimeout = function (fn, ms) {
    if (!inScope() || typeof fn !== 'function') {
      return nativeSetTimeout.apply(window, arguments);
    }
    var args = Array.prototype.slice.call(arguments, 2);
    var id = nativeSetTimeout(function () {
      var i = scope.timeouts.indexOf(id);
      if (i !== -1) scope.timeouts.splice(i, 1);
      runInScope(fn, window, args);
    }, ms);
    scope.timeouts.push(id);
    return id;
  };

  window.setInterval = function (fn, ms) {
    if (!inScope() || typeof fn !== 'function') {
      return nativeSetInterval.apply(window, arguments);
    }
    var args = Array.prototype.slice.call(arguments, 2);
    var id = nativeSetInterval(function () { runInScope(fn, window, args); }, ms);
    scope.intervals.push(id);
    return id;
  };

  function teardownPageScope() {
    scope.listeners.forEach(function (l) {
      try { l[0].removeEventListener(l[1], l[2], l[3]); } catch (e) { /* ignore */ }
    });
    scope.intervals.forEach(function (id) { nativeClearInterval(id); });
    scope.timeouts.forEach(function (id) { nativeClearTimeout(id); });
    scope.listeners = [];
    scope.intervals = [];
    scope.timeouts = [];
  }

  /* Balises de base_ecom.html autour de #ecom-main et du slot extra_js (1er chargement) */
  function scopeBegin() { scope.depth++; }
  function scopeEnd() { if (scope.depth > 0) scope.depth--; }

  /* Compte les preventDefault : sert à savoir si un script de page a déjà pris le clic/submit */
  var nativePreventDefault = Event.prototype.preventDefault;
  Event.prototype.preventDefault = function () {
    this.__ecomPrevented = (this.__ecomPrevented || 0) + 1;
    return nativePreventDefault.apply(this, arguments);
  };

  /* ------------------------------------------------------------------ */
  /* 2. Règles d'exclusion (rechargement classique)                      */
  /* ------------------------------------------------------------------ */
  var EXCLUDE_PATH_RE = new RegExp(
    '^/(' + [
      'facture/',                    // factures : gabarit d'impression
      'checkout/',                   // paiement : redirection vers la passerelle
      'commande/valider',
      'commande/[^/]+/payer',
      'paiement/',
      'authentification/',           // connexion / Google / déconnexion
      'accounts/',
      'i18n/',                       // changement de langue : tout l'en-tête change
      'admin/',
      'stocks/',                     // back-office
      'mag/',
      'livraison/',
      'api/',
      'webhooks/',
      'media/',
      'static/'
    ].join('|') + ')',
    'i'
  );

  function pathOf(href) {
    try {
      return new URL(href, window.location.href).pathname;
    } catch (e) {
      return href || '';
    }
  }

  function shouldExcludeUrl(href) {
    if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) return true;
    if (/^(mailto|tel|sms|whatsapp):/i.test(href)) return true;
    try {
      if (new URL(href, window.location.href).origin !== window.location.origin) return true;
    } catch (e) {
      return true;
    }
    var path = pathOf(href);
    if (EXCLUDE_PATH_RE.test(path)) return true;
    if (/\/(export|imprimer|telecharger|download)(\/|$|-)/i.test(path)) return true;
    if (/\.(xlsx?|pdf|csv|zip|png|jpe?g|gif|webp|apk)(\?|$)/i.test(href)) return true;
    return false;
  }

  function markExclusions(root) {
    var scopeEl = root || document;
    scopeEl.querySelectorAll('a[href]').forEach(function (a) {
      if (a.hasAttribute('hx-boost')) return;
      if ((a.target && a.target !== '_self') || a.hasAttribute('download') ||
          a.hasAttribute('data-bs-toggle') || a.hasAttribute('data-toggle') ||
          shouldExcludeUrl(a.getAttribute('href'))) {
        a.setAttribute('hx-boost', 'false');
      }
    });
    scopeEl.querySelectorAll('form').forEach(function (form) {
      if (form.hasAttribute('hx-boost')) return;
      var action = form.getAttribute('action') || window.location.href;
      if (shouldExcludeUrl(action) || form.enctype === 'multipart/form-data' ||
          form.hasAttribute('data-no-spa') || (form.target && form.target !== '_self')) {
        form.setAttribute('hx-boost', 'false');
      }
    });
  }

  /* ------------------------------------------------------------------ */
  /* 3. Synchronisation de la page reçue                                 */
  /* ------------------------------------------------------------------ */
  function nprogressStart() {
    if (window.NProgress) window.NProgress.start();
    document.documentElement.classList.add('ecom-spa-loading');
  }

  function nprogressDone() {
    if (window.NProgress) window.NProgress.done();
    document.documentElement.classList.remove('ecom-spa-loading');
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
    var ct = (xhr.getResponseHeader('Content-Type') || '').toLowerCase();
    return !ct || ct.indexOf('text/html') !== -1 || ct.indexOf('application/xhtml') !== -1;
  }

  function hardNavigate(url) {
    nprogressDone();
    window.location.href = url || window.location.href;
  }

  var serverBodyClasses = null;

  function syncBodyClass(doc) {
    if (!doc || !doc.body) return;
    var body = document.body;
    if (serverBodyClasses === null) serverBodyClasses = Array.prototype.slice.call(body.classList);
    serverBodyClasses.forEach(function (c) { body.classList.remove(c); });
    serverBodyClasses = Array.prototype.slice.call(doc.body.classList);
    serverBodyClasses.forEach(function (c) { body.classList.add(c); });
  }

  function syncPageStyles(doc) {
    document.querySelectorAll('[data-ecom-spa-css]').forEach(function (el) { el.remove(); });
    if (!doc || !doc.head) return;
    doc.head.querySelectorAll('link[rel~="stylesheet"], style').forEach(function (node) {
      if (node.tagName === 'LINK') {
        var href = node.getAttribute('href');
        if (!href || document.querySelector('link[href="' + href + '"]')) return;
      }
      var clone = node.cloneNode(true);
      clone.setAttribute('data-ecom-spa-css', '1');
      document.head.appendChild(clone);
    });
  }

  function syncHeader(doc) {
    if (!doc) return;
    [
      '.accont-wishlist-cart-area-header .cart > .number',
      '.accont-wishlist-cart-area-header .wishlist > .number',
    ].forEach(function (sel) {
      var incoming = doc.querySelector(sel);
      var current = document.querySelector(sel);
      if (incoming && current) current.textContent = incoming.textContent;
    });
    var miniIn = doc.querySelector('.ecom-header-mini-cart');
    var miniCur = document.querySelector('.ecom-header-mini-cart');
    if (miniIn && miniCur) miniCur.replaceWith(document.importNode(miniIn, true));
    var mobIn = doc.querySelector('.ecom-mobile-header__icon-btn--cart');
    var mobCur = document.querySelector('.ecom-mobile-header__icon-btn--cart');
    if (mobIn && mobCur) mobCur.innerHTML = mobIn.innerHTML;
  }

  function bindFlashStack(stack) {
    function dismiss(toast) {
      if (!toast || toast.classList.contains('is-leaving')) return;
      toast.classList.add('is-leaving');
      nativeSetTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
        if (stack && !stack.children.length && stack.parentNode) stack.parentNode.removeChild(stack);
      }, 320);
    }
    stack.querySelectorAll('.ecom-flash-toast').forEach(function (toast) {
      var closeBtn = toast.querySelector('.ecom-flash-toast-close');
      if (closeBtn) closeBtn.addEventListener('click', function () { dismiss(toast); });
      nativeSetTimeout(function () { dismiss(toast); }, 5000);
    });
  }

  function syncFlash(doc) {
    var existing = document.getElementById('ecomFlashMessages');
    if (existing) existing.remove();
    var incoming = doc && doc.getElementById('ecomFlashMessages');
    if (!incoming) return;
    var clone = document.importNode(incoming, true);
    clone.querySelectorAll('script').forEach(function (s) { s.remove(); });
    document.body.insertBefore(clone, document.body.firstChild);
    bindFlashStack(clone);
  }

  /* ------------------------------------------------------------------ */
  /* 4. Scripts de page                                                  */
  /* ------------------------------------------------------------------ */
  var loadedSrc = {};

  function rememberLoadedScripts() {
    Array.prototype.forEach.call(document.scripts, function (s) {
      if (s.src) loadedSrc[s.src] = true;
    });
  }

  function isJsType(type) {
    type = (type || '').toLowerCase();
    return !type || type === 'text/javascript' || type === 'application/javascript' || type === 'module';
  }

  /** Rejoue dans l'ordre les <script> de ``source`` (réponse parsée) en les ajoutant à ``mount``. */
  function executeScriptsSequential(source, mount, done) {
    if (!source || !mount) { if (done) done(); return; }
    var scripts = Array.prototype.slice.call(source.querySelectorAll('script'));
    var i = 0;

    function next() {
      if (i >= scripts.length) { if (done) done(); return; }
      var old = scripts[i++];
      var type = old.getAttribute('type');
      if (!isJsType(type)) { next(); return; }

      var s = document.createElement('script');
      Array.prototype.forEach.call(old.attributes, function (attr) {
        if (attr.name === 'async' || attr.name === 'defer' || attr.name === 'src') return;
        s.setAttribute(attr.name, attr.value);
      });
      s.setAttribute('data-ecom-spa-page', '1');

      if (old.getAttribute('src')) {
        var src = new URL(old.getAttribute('src'), window.location.href).href;
        if (loadedSrc[src]) { next(); return; }          // bibliothèque déjà chargée (Leaflet…)
        loadedSrc[src] = true;
        s.async = false;
        s.onload = s.onerror = function () { next(); };
        s.src = src;
        mount.appendChild(s);
        return;
      }
      /* Bloc {} : const/let isolés entre deux visites ; les function restent globales (onclick) */
      var code = old.textContent || '';
      s.textContent = (type || '').toLowerCase() === 'module' ? code : '{\n' + code + '\n}';
      scope.depth++;
      try {
        mount.appendChild(s);
      } finally {
        scope.depth--;
      }
      next();
    }

    next();
  }

  /* ------------------------------------------------------------------ */
  /* 5. Réinitialisation du thème sur le nouveau contenu                 */
  /* ------------------------------------------------------------------ */
  function destroyWidgets(root) {
    if (!root) return;
    root.querySelectorAll('.swiper').forEach(function (el) {
      if (el.swiper && typeof el.swiper.destroy === 'function') {
        try { el.swiper.destroy(true, false); } catch (e) { /* ignore */ }
      }
    });
  }

  function bindThemeQtyButtons($, root) {
    /* Même comportement que rtsJs.cartNumberIncDec du thème, limité au nouveau contenu */
    $(root).find('.quantity-edit .button').off('click.ecomSpa').on('click.ecomSpa', function () {
      var $button = $(this);
      var $parent = $button.parents('.quantity-edit');
      if ($parent.hasClass('ecom-detail-qty-control') || $button.closest('.ecom-add-cart-form').length) return;
      var oldValue = parseFloat($parent.find('.input').val()) || 1;
      var newVal = ($button.hasClass('plus') || $button.hasClass('qty-plus'))
        ? oldValue + 1
        : Math.max(1, oldValue - 1);
      $parent.find('a.add-to-cart').attr('data-quantity', newVal);
      $parent.find('.input').val(newVal);
    });
  }

  function reinitTheme(root) {
    if (!root) return;
    if (window.Swiper) {
      root.querySelectorAll('.swiper-data').forEach(function (el) {
        if (el.swiper) return;
        var options = {};
        try { options = el.dataset.swiper ? JSON.parse(el.dataset.swiper) : {}; } catch (e) { options = {}; }
        try {
          new window.Swiper(el, Object.assign({ spaceBetween: 30, slidesPerView: 2 }, options));
        } catch (e) { /* ignore */ }
      });
    }
    var $ = window.jQuery;
    if ($) {
      if ($.fn.niceSelect) $(root).find('select').niceSelect();
      if ($.fn.theiaStickySidebar) {
        $(root).find('.rts-sticky-column-item').theiaStickySidebar({ additionalMarginTop: 130 });
      }
      bindThemeQtyButtons($, root);
    }
    if (window.Alpine && typeof window.Alpine.initTree === 'function') {
      try { window.Alpine.initTree(root); } catch (e) { /* ignore */ }
    }
  }

  function cleanupModals() {
    if (window.bootstrap && window.bootstrap.Modal) {
      document.querySelectorAll('.modal.show').forEach(function (el) {
        try { window.bootstrap.Modal.getOrCreateInstance(el).hide(); } catch (e) { /* ignore */ }
      });
    }
    document.querySelectorAll('.modal-backdrop, .offcanvas-backdrop').forEach(function (el) { el.remove(); });
    document.body.classList.remove('modal-open');
    document.body.style.removeProperty('padding-right');
    document.body.style.removeProperty('overflow');
    /* Menu mobile / recherche du thème */
    var side = document.getElementById('side-bar');
    if (side) side.classList.remove('show');
    var over = document.getElementById('anywhere-home');
    if (over) over.classList.remove('bgshow');
  }

  /* ------------------------------------------------------------------ */
  /* 6. Cycle HTMX                                                       */
  /* ------------------------------------------------------------------ */
  var pendingDoc = null;

  function onConfirm(evt) {
    var d = evt.detail || {};
    var elt = d.elt;
    var trigger = d.triggeringEvent;
    if (!elt || !trigger || (elt.tagName !== 'A' && elt.tagName !== 'FORM')) return;

    var href = elt.tagName === 'A'
      ? elt.getAttribute('href')
      : (elt.getAttribute('action') || window.location.href);

    evt.preventDefault();

    if (shouldExcludeUrl(href) || (elt.tagName === 'FORM' && elt.enctype === 'multipart/form-data')) {
      /* Exclu : navigation classique (htmx a déjà annulé l'événement) */
      if (elt.tagName === 'A') {
        window.location.href = elt.href;
      } else {
        submitNatively(elt, trigger.submitter);
      }
      return;
    }

    /* Laisser finir l'événement : si un script de page l'a aussi annulé
       (formulaire AJAX, lien JS…), c'est lui qui s'en occupe. */
    nativeSetTimeout(function () {
      if ((trigger.__ecomPrevented || 0) > 1) return;
      d.issueRequest(true);
    }, 0);
  }

  function submitNatively(form, submitter) {
    if (submitter && submitter.name) {
      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = submitter.name;
      hidden.value = submitter.value;
      form.appendChild(hidden);
    }
    HTMLFormElement.prototype.submit.call(form);
  }

  function onBeforeRequest() {
    nprogressStart();
  }

  function onBeforeSwap(evt) {
    var xhr = evt.detail && evt.detail.xhr;
    if (!xhr) return;
    if (xhr.status >= 400) {
      /* Laisser le navigateur afficher la vraie page d'erreur */
      evt.detail.shouldSwap = false;
      hardNavigate(xhr.responseURL);
      return;
    }
    if (!isHtmlResponse(xhr) || !/id=["']ecom-main["']/.test(xhr.responseText || '')) {
      /* Fichier, ou page d'un autre gabarit (connexion, back-office…) */
      evt.detail.shouldSwap = false;
      hardNavigate(xhr.responseURL);
      return;
    }
    cleanupModals();
    teardownPageScope();
    destroyWidgets(document.getElementById('ecom-main'));
  }

  function onAfterSwap(evt) {
    var doc = parseDoc(evt.detail && evt.detail.xhr);
    if (doc && doc.title) document.title = doc.title;
    syncBodyClass(doc);
    syncPageStyles(doc);
    syncHeader(doc);
    syncFlash(doc);
    pendingDoc = doc;
  }

  /* Scripts après le settle HTMX (sinon il remet les attributs des éléments de même id) */
  function onAfterSettle() {
    if (pendingDoc === null) return;
    var doc = pendingDoc;
    pendingDoc = null;
    var main = document.getElementById('ecom-main');
    var slot = document.getElementById('ecom-page-scripts');
    markExclusions(document);
    reinitTheme(main);

    var incomingMain = doc && doc.getElementById('ecom-main');
    var incomingScripts = doc && doc.getElementById('ecom-page-scripts');
    if (slot) slot.innerHTML = '';
    executeScriptsSequential(incomingMain, main, function () {
      executeScriptsSequential(incomingScripts, slot, function () {
        document.dispatchEvent(new CustomEvent('ecom:navigated', {
          detail: { path: window.location.pathname },
        }));
        nprogressDone();
      });
    });
  }

  function init() {
    rememberLoadedScripts();
    if (window.htmx && window.htmx.config) {
      window.htmx.config.allowScriptTags = false;   // rejoués par executeScriptsSequential
      window.htmx.config.historyCacheSize = 0;      // retour arrière = rechargement complet
      window.htmx.config.refreshOnHistoryMiss = true;
      window.htmx.config.scrollBehavior = 'instant';
    }
    if (window.NProgress) {
      window.NProgress.configure({ showSpinner: false, trickleSpeed: 180, minimum: 0.08 });
    }
    markExclusions(document);

    var body = document.body;
    body.addEventListener('htmx:configRequest', function (evt) {
      var meta = document.querySelector('meta[name="csrf-token"]');
      if (meta && meta.content) evt.detail.headers['X-CSRFToken'] = meta.content;
    });
    body.addEventListener('htmx:confirm', onConfirm);
    body.addEventListener('htmx:beforeRequest', onBeforeRequest);
    body.addEventListener('htmx:beforeSwap', onBeforeSwap);
    body.addEventListener('htmx:afterSwap', onAfterSwap);
    body.addEventListener('htmx:afterSettle', onAfterSettle);
    body.addEventListener('htmx:responseError', nprogressDone);
    body.addEventListener('htmx:sendError', function (evt) {
      /* Réseau coupé ou redirection vers un autre domaine : on retente en navigation classique
         (GET seulement : un POST ne doit pas être rejoué à l'aveugle) */
      var cfg = evt.detail && evt.detail.requestConfig;
      if (cfg && String(cfg.verb).toLowerCase() === 'get') {
        hardNavigate(cfg.path);
      } else {
        nprogressDone();
      }
    });
    body.addEventListener('htmx:timeout', nprogressDone);
  }

  /* Enregistré avant htmx (script placé avant lui) : htmx.config est posé avant qu'il ne traite la page */
  document.addEventListener('DOMContentLoaded', init);

  window.EcomSpaNav = {
    scopeBegin: scopeBegin,
    scopeEnd: scopeEnd,
    markExclusions: markExclusions,
    shouldExcludeUrl: shouldExcludeUrl,
    reinitTheme: reinitTheme,
  };
})(window, document);
