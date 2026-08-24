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
      if (input) input.focus();
    }
    chatPanel.addEventListener('animationend', onOpenEnd);
  }

  function closeChatbot() {
    if (chatAnimating || !chatIsOpen) return;
    chatAnimating = true;
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

  function replyFor(text) {
    var t = (text || '').toLowerCase();
    if (/whatsapp|whats\s?app|0787532210/.test(t)) {
      return 'Vous pouvez nous joindre sur WhatsApp au 07 87 53 22 10. Le bouton vert ouvre la conversation.';
    }
    if (/livr|retrait|commande|suivi/.test(t)) {
      return 'Après paiement, l’agence prépare votre commande. En livraison, confirmez la réception une fois livrée. Consultez « Mes commandes » dans votre compte.';
    }
    if (/pai|wave|orange|mtn|genius/.test(t)) {
      return 'Le paiement en ligne se fait via GeniusPay (Wave, Orange Money, MTN ou carte). L’espèce est possible à la livraison ou au retrait.';
    }
    if (/pi[eè]ce|stock|prix|dispo/.test(t)) {
      return 'Parcourez la boutique et choisissez votre agence pour voir le stock local. Un conseiller WhatsApp peut aussi vous aider à identifier une pièce.';
    }
    return 'Merci pour votre message. Un conseiller vous répondra bientôt, ou contactez-nous via WhatsApp / le centre d’assistance.';
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
      var body = chatPanel.querySelector('.contact-chatbot__body');
      if (!input || !body || !input.value.trim()) return;

      var userBubble = document.createElement('div');
      userBubble.className = 'contact-chatbot__bubble';
      userBubble.style.marginTop = '10px';
      userBubble.style.marginLeft = 'auto';
      userBubble.style.display = 'block';
      userBubble.style.borderRadius = '14px 14px 4px 14px';
      userBubble.style.background = '#ff8b00';
      userBubble.style.color = '#fff';
      userBubble.textContent = input.value.trim();
      body.appendChild(userBubble);

      var reply = document.createElement('div');
      reply.className = 'contact-chatbot__bubble';
      reply.style.marginTop = '10px';
      reply.style.display = 'block';
      reply.textContent = replyFor(input.value);
      body.appendChild(reply);
      body.scrollTop = body.scrollHeight;
      input.value = '';
    });
  }
})();
