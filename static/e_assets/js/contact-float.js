(function () {
  var chatBtn = document.getElementById('contact-float-chat-btn');
  var chatPanel = document.getElementById('contact-chatbot');
  var chatClose = document.getElementById('contact-chatbot-close');
  var chatForm = document.getElementById('contact-chatbot-form');
  if (!chatBtn || !chatPanel) return;

  var chatIsOpen = false;
  var chatAnimating = false;
  var chatOriginReady = false;
  var openAnim = 'ecom-genie-open';
  var closeAnim = 'ecom-genie-close';
  var threadUrl = chatPanel.getAttribute('data-thread-url') || '/chat/thread/';
  var pollMs = parseInt(chatPanel.getAttribute('data-poll-ms') || '4000', 10) || 4000;
  var bodyEl = document.getElementById('contact-chatbot-body');
  var chipsEl = document.getElementById('contact-chatbot-chips');
  var newWrap = document.getElementById('contact-chatbot-new-wrap');
  var newBtn = document.getElementById('contact-chatbot-new');
  var statusEl = document.getElementById('contact-chatbot-status');
  var typingEl = document.getElementById('contact-chatbot-typing');
  var typingLabelEl = typingEl ? typingEl.querySelector('.contact-chatbot__typing-label') : null;
  var scrollEl = chatPanel.querySelector('.contact-chatbot__scroll');
  var pollTimer = null;
  var lastMessageIds = '';
  var knownStatus = null;
  var knownFlags = '';
  var knownTyping = '';
  var sending = false;
  var currentConversationId = null;
  var lastTypingSent = 0;
  var typingPulseTimer = null;

  var STATUS_LABELS = {
    pending: 'Un conseiller va prendre en charge…',
    active: 'Discussion avec un conseiller',
    refused: 'Conseiller indisponible',
    closed: 'Conversation terminée'
  };

  function csrfToken() {
    var input = chatForm ? chatForm.querySelector('input[name="csrfmiddlewaretoken"]') : null;
    if (input && input.value) return input.value;
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function measureGenieTarget() {
    var wasHidden = chatPanel.hasAttribute('hidden');
    if (wasHidden) {
      chatPanel.removeAttribute('hidden');
      chatPanel.classList.add('is-animating');
      chatPanel.style.cssText += 'visibility:hidden;opacity:0;pointer-events:none;';
      chatPanel.classList.add('is-open');
      chatPanel.classList.remove('is-opening', 'is-closing');
    }

    var panelRect = chatPanel.getBoundingClientRect();
    var btnRect = chatBtn.getBoundingClientRect();
    chatPanel.style.setProperty('--genie-ox', (btnRect.left + btnRect.width / 2 - panelRect.left) + 'px');
    chatPanel.style.setProperty('--genie-oy', (btnRect.top + btnRect.height / 2 - panelRect.top) + 'px');
    chatOriginReady = true;

    if (wasHidden) {
      chatPanel.classList.remove('is-open');
      chatPanel.style.visibility = '';
      chatPanel.style.opacity = '';
      chatPanel.style.pointerEvents = '';
    }
  }

  function openChatbot() {
    if (chatAnimating || chatIsOpen) return;
    chatAnimating = true;
    measureGenieTarget();

    requestAnimationFrame(function () {
      chatPanel.classList.remove('is-closing', 'is-open');
      chatPanel.classList.add('is-opening', 'is-animating');
      chatBtn.classList.add('is-open');
      chatBtn.setAttribute('aria-expanded', 'true');
    });

    function onOpenEnd(event) {
      if (event.target !== chatPanel || event.animationName !== openAnim) return;
      chatPanel.removeEventListener('animationend', onOpenEnd);
      chatPanel.classList.remove('is-opening');
      chatPanel.classList.add('is-open');
      chatIsOpen = true;
      chatAnimating = false;
      var input = chatForm ? chatForm.querySelector('input[name="message"]') : null;
      if (input && chatForm && !chatForm.hidden) input.focus();
      startPolling();
      refreshThread();
    }
    chatPanel.addEventListener('animationend', onOpenEnd);
  }

  function closeChatbot() {
    if (chatAnimating || !chatIsOpen) return;
    chatAnimating = true;
    stopPolling();
    if (!chatOriginReady) measureGenieTarget();
    else {
      var panelRect = chatPanel.getBoundingClientRect();
      var btnRect = chatBtn.getBoundingClientRect();
      chatPanel.style.setProperty('--genie-ox', (btnRect.left + btnRect.width / 2 - panelRect.left) + 'px');
      chatPanel.style.setProperty('--genie-oy', (btnRect.top + btnRect.height / 2 - panelRect.top) + 'px');
    }

    requestAnimationFrame(function () {
      chatPanel.classList.remove('is-open', 'is-opening');
      chatPanel.classList.add('is-closing', 'is-animating');
      chatBtn.classList.remove('is-open');
      chatBtn.setAttribute('aria-expanded', 'false');
    });

    function onCloseEnd(event) {
      if (event.target !== chatPanel || event.animationName !== closeAnim) return;
      chatPanel.removeEventListener('animationend', onCloseEnd);
      chatPanel.classList.remove('is-closing', 'is-animating', 'is-open');
      chatPanel.setAttribute('hidden', '');
      chatIsOpen = false;
      chatAnimating = false;
    }
    chatPanel.addEventListener('animationend', onCloseEnd);
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(function () {
      if (chatIsOpen) refreshThread();
    }, pollMs);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function bubbleClass(senderType) {
    if (senderType === 'client') return 'contact-chatbot__bubble contact-chatbot__bubble--client';
    if (senderType === 'staff') return 'contact-chatbot__bubble contact-chatbot__bubble--staff';
    if (senderType === 'system') return 'contact-chatbot__bubble contact-chatbot__bubble--system';
    return 'contact-chatbot__bubble contact-chatbot__bubble--bot';
  }

  function setChipsVisible(show) {
    if (!chipsEl) return;
    chipsEl.hidden = !show;
  }

  function renderTypingBubble(show, label) {
    if (!bodyEl) return;
    var existing = bodyEl.querySelector('[data-chat-typing]');
    if (existing) existing.remove();
    if (typingEl) typingEl.hidden = true;
    if (!show) {
      knownTyping = '';
      return;
    }
    var text = label || 'Écrit…';
    var el = document.createElement('div');
    el.className = 'contact-chatbot__bubble contact-chatbot__bubble--staff contact-chatbot__bubble--typing';
    el.setAttribute('data-chat-typing', '1');
    el.innerHTML =
      '<span>' + text + '</span>' +
      '<span class="contact-chatbot__typing-dots" aria-hidden="true"><i></i><i></i><i></i></span>';
    bodyEl.appendChild(el);
    knownTyping = text;
    if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
  }

  function showTypingIndicator(show, label) {
    renderTypingBubble(show, label);
  }

  function handleTypingEvent(payload) {
    if (!payload || !currentConversationId) return;
    if (String(payload.conversation_id) !== String(currentConversationId)) return;
    if (payload.who !== 'staff') return;
    showTypingIndicator(!!payload.typing, payload.label || 'Conseiller écrit…');
  }

  function signalTyping() {
    var now = Date.now();
    if (now - lastTypingSent < 1000) return;
    lastTypingSent = now;
    fetch(threadUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken()
      },
      body: JSON.stringify({ action: 'typing' })
    }).catch(function () {});
  }

  function scheduleTypingPulse() {
    signalTyping();
    if (typingPulseTimer) clearTimeout(typingPulseTimer);
    typingPulseTimer = setTimeout(function () {
      var input = chatForm ? chatForm.querySelector('input[name="message"]') : null;
      if (input && input.value.trim()) signalTyping();
    }, 1400);
  }

  function setNewVisible(show) {
    if (!newWrap) return;
    newWrap.hidden = !show;
  }

  function setFormVisible(show) {
    if (!chatForm) return;
    chatForm.hidden = !show;
  }

  function renderWelcome() {
    if (!bodyEl) return;
    bodyEl.innerHTML = '';
    var welcome = document.createElement('div');
    welcome.className = 'contact-chatbot__bubble contact-chatbot__bubble--bot';
    welcome.setAttribute('data-welcome', '1');
    welcome.textContent = 'Bonjour ! Comment puis-je vous aider aujourd’hui ?';
    bodyEl.appendChild(welcome);
    setChipsVisible(true);
    setNewVisible(false);
    setFormVisible(true);
    if (statusEl) statusEl.textContent = 'En ligne · répond rapidement';
    lastMessageIds = '';
    knownStatus = null;
    knownFlags = '';
    currentConversationId = null;
    showTypingIndicator(false);
  }

  function renderThread(data) {
    if (!bodyEl) return;
    var messages = (data && data.messages) || [];
    var status = data && data.status;
    var showChips = !!(data && data.show_chips);
    var canSend = data && data.can_send !== false;
    var canStartNew = !!(data && data.can_start_new);
    var messagesHidden = !!(data && data.messages_hidden);
    var typing = !!(data && data.typing);
    var typingLabel = (data && data.typing_label) || 'Conseiller écrit…';
    var ids = messages.map(function (m) { return m.id; }).join(',');
    var flags = [showChips, canSend, canStartNew, messagesHidden, typing, typingLabel].join('|');

    currentConversationId = (data && data.conversation && data.conversation.id) || data.conversation_id || currentConversationId;

    if (statusEl) {
      statusEl.textContent = STATUS_LABELS[status] || 'En ligne · répond rapidement';
    }

    if (!messages.length && !status) {
      renderWelcome();
      return;
    }

    if (ids === lastMessageIds && status === knownStatus && flags === knownFlags) {
      setChipsVisible(showChips);
      setNewVisible(canStartNew);
      setFormVisible(canSend && !canStartNew);
      renderTypingBubble(typing, typingLabel);
      return;
    }

    lastMessageIds = ids;
    knownStatus = status;
    knownFlags = flags;
    bodyEl.innerHTML = '';

    if (messagesHidden || (!messages.length && status === 'closed')) {
      var ended = document.createElement('div');
      ended.className = 'contact-chatbot__bubble contact-chatbot__bubble--system';
      ended.textContent = messagesHidden
        ? 'Cette conversation est terminée. Vous pouvez en démarrer une nouvelle.'
        : 'La conversation est terminée.';
      bodyEl.appendChild(ended);
      setChipsVisible(false);
      setNewVisible(true);
      setFormVisible(false);
      renderTypingBubble(false);
      return;
    }

    if (!messages.length) {
      renderWelcome();
      setChipsVisible(showChips || true);
      renderTypingBubble(typing, typingLabel);
      return;
    }

    messages.forEach(function (m) {
      var el = document.createElement('div');
      el.className = bubbleClass(m.sender_type);
      el.textContent = m.body || '';
      bodyEl.appendChild(el);
    });

    setChipsVisible(showChips);
    setNewVisible(canStartNew);
    setFormVisible(canSend && !canStartNew);
    renderTypingBubble(typing, typingLabel);
    if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
  }

  function refreshThread() {
    fetch(threadUrl, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.ok !== false) renderThread(data);
      })
      .catch(function () { /* ignore poll errors */ });
  }

  function sendMessage(text) {
    if (sending || !text) return;
    sending = true;
    showTypingIndicator(false);
    var token = csrfToken();
    fetch(threadUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-CSRFToken': token
      },
      body: JSON.stringify({ message: text })
    })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (res) {
        sending = false;
        if (res.data) {
          if (res.data.conversation_id) currentConversationId = res.data.conversation_id;
          if (res.data.conversation && res.data.conversation.id) {
            currentConversationId = res.data.conversation.id;
          }
          renderThread(res.data);
        } else refreshThread();
      })
      .catch(function () {
        sending = false;
      });
  }

  function startNewConversation() {
    if (sending) return;
    sending = true;
    fetch(threadUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken()
      },
      body: JSON.stringify({ action: 'new' })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        sending = false;
        renderWelcome();
        if (data) renderThread(data);
        var input = chatForm ? chatForm.querySelector('input[name="message"]') : null;
        if (input) input.focus();
      })
      .catch(function () {
        sending = false;
      });
  }

  chatBtn.addEventListener('click', function () {
    if (chatAnimating) return;
    if (!chatIsOpen) openChatbot();
    else closeChatbot();
  });
  if (chatClose) chatClose.addEventListener('click', closeChatbot);
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closeChatbot();
  });

  if (chatForm) {
    chatForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var input = chatForm.querySelector('input[name="message"]');
      if (!input || !input.value.trim()) return;
      var text = input.value.trim();
      input.value = '';
      sendMessage(text);
    });
    var chatInput = chatForm.querySelector('input[name="message"]');
    if (chatInput) {
      chatInput.addEventListener('input', scheduleTypingPulse);
      chatInput.addEventListener('blur', function () {
        if (typingPulseTimer) clearTimeout(typingPulseTimer);
      });
    }
  }

  if (window.ecomChatPusher) {
    try {
      var chatChannel = window.ecomChatPusher.subscribe('magasin-chat');
      chatChannel.bind('typing', function (payload) {
        handleTypingEvent(payload);
      });
    } catch (e) {}
  }

  if (newBtn) {
    newBtn.addEventListener('click', startNewConversation);
  }

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stopPolling();
    else if (chatIsOpen) startPolling();
  });
})();
