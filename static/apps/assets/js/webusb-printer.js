/*
 * Impression thermique depuis le poste de caisse — Auto-Pièce
 * ---------------------------------------------------------------------------
 * L'application tourne sur un serveur distant, qui ne voit aucun périphérique
 * USB. Le serveur se contente donc de composer le flux ESC/POS (même code que
 * l'impression USB directe, cf. stock/printer_service.py), et c'est ce module
 * qui le pousse vers l'imprimante réellement branchée sur la machine du
 * caissier, via l'API WebUSB du navigateur.
 *
 * Prérequis côté poste :
 *   - Chrome ou Edge (WebUSB n'existe ni sur Firefox ni sur Safari) ;
 *   - la page servie en HTTPS (WebUSB exige un contexte sécurisé) ;
 *   - le pilote WinUSB installé sur l'imprimante via Zadig, sous Windows.
 *
 * Les URL sont injectées par le gabarit Django dans window.AUTOPIECE_PRINT_URLS.
 */
(function (global) {
    'use strict';

    // Classe USB « Printer ». Les imprimantes thermiques l'exposent, ce qui
    // permet de filtrer le sélecteur de périphériques du navigateur.
    var USB_PRINTER_CLASS = 0x07;
    var EPSON_VENDOR_ID = 0x04B8;

    // Les imprimantes thermiques encaissent mal un envoi massif d'un bloc :
    // on découpe en paquets, comme le ferait un pilote.
    var CHUNK_SIZE = 4096;

    function urls() {
        return global.AUTOPIECE_PRINT_URLS || {};
    }

    function isSupported() {
        return typeof navigator !== 'undefined' && !!navigator.usb;
    }

    function hex4(value) {
        return '0x' + value.toString(16).toUpperCase().padStart(4, '0');
    }

    /* Décrit un périphérique WebUSB avec les mêmes clés que le scan serveur,
       afin que la boîte de dialogue s'affiche à l'identique dans les deux modes. */
    function describe(device) {
        if (!device) return null;
        return {
            manufacturer: device.manufacturerName || '',
            product: device.productName || '',
            vid: device.vendorId,
            pid: device.productId,
            vid_hex: hex4(device.vendorId),
            pid_hex: hex4(device.productId),
            serial: device.serialNumber || '',
            bus: null,
            address: null,
            source: 'webusb',
        };
    }

    /* Périphériques déjà autorisés par l'utilisateur sur cette origine.
       Aucune interaction : utilisable au chargement de la page. */
    function authorizedDevices() {
        if (!isSupported()) return Promise.resolve([]);
        return navigator.usb.getDevices().catch(function () { return []; });
    }

    /* Ouvre le sélecteur du navigateur. À n'appeler que depuis un gestionnaire
       de clic : les navigateurs exigent un geste utilisateur. */
    function requestDevice() {
        if (!isSupported()) {
            return Promise.reject(new Error(
                "Ce navigateur ne gère pas WebUSB. Utilisez Chrome ou Edge."
            ));
        }
        return navigator.usb.requestDevice({
            filters: [
                { classCode: USB_PRINTER_CLASS },
                { vendorId: EPSON_VENDOR_ID },
            ],
        });
    }

    /* Trouve une interface exposant un point de terminaison bulk sortant.
       Les interfaces de classe « Printer » sont examinées en premier. */
    function findOutputEndpoint(device) {
        var candidates = [];
        device.configuration.interfaces.forEach(function (iface) {
            iface.alternates.forEach(function (alt) {
                alt.endpoints.forEach(function (endpoint) {
                    if (endpoint.direction === 'out' && endpoint.type === 'bulk') {
                        candidates.push({
                            interfaceNumber: iface.interfaceNumber,
                            alternateSetting: alt.alternateSetting,
                            endpointNumber: endpoint.endpointNumber,
                            isPrinterClass: alt.interfaceClass === USB_PRINTER_CLASS,
                        });
                    }
                });
            });
        });
        if (!candidates.length) return null;
        candidates.sort(function (a, b) {
            return (b.isPrinterClass ? 1 : 0) - (a.isPrinterClass ? 1 : 0);
        });
        return candidates[0];
    }

    /* Envoie un flux ESC/POS au périphérique, puis relâche l'interface.
       L'interface est systématiquement libérée, même en cas d'échec : sans
       cela, l'impression suivante échouerait sur un périphérique verrouillé. */
    function send(device, bytes) {
        var target = null;
        return Promise.resolve()
            .then(function () {
                if (!device.opened) return device.open();
            })
            .then(function () {
                if (device.configuration === null) {
                    return device.selectConfiguration(1);
                }
            })
            .then(function () {
                target = findOutputEndpoint(device);
                if (!target) {
                    throw new Error(
                        "Aucun point de terminaison d'impression sur ce périphérique. "
                        + "Vérifiez que WinUSB est bien installé via Zadig."
                    );
                }
                return device.claimInterface(target.interfaceNumber);
            })
            .then(function () {
                if (target.alternateSetting !== 0) {
                    return device.selectAlternateInterface(
                        target.interfaceNumber, target.alternateSetting
                    );
                }
            })
            .then(function () {
                var chain = Promise.resolve();
                for (var offset = 0; offset < bytes.length; offset += CHUNK_SIZE) {
                    (function (slice) {
                        chain = chain.then(function () {
                            return device.transferOut(target.endpointNumber, slice);
                        });
                    })(bytes.slice(offset, offset + CHUNK_SIZE));
                }
                return chain;
            })
            .then(function () {
                return release(device, target);
            })
            .catch(function (error) {
                return release(device, target).then(function () {
                    throw error;
                });
            });
    }

    function release(device, target) {
        return Promise.resolve()
            .then(function () {
                if (target) return device.releaseInterface(target.interfaceNumber);
            })
            .catch(function () { /* déjà relâchée */ })
            .then(function () {
                if (device.opened) return device.close();
            })
            .catch(function () { /* déjà fermée */ });
    }

    /* Récupère un flux ESC/POS composé par le serveur. */
    function fetchBytes(url) {
        return fetch(url, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        }).then(function (response) {
            if (!response.ok) {
                // Les erreurs applicatives (commande non payée, accès refusé)
                // arrivent en JSON ; on remonte le message tel quel.
                return response.json()
                    .then(function (data) {
                        throw new Error(data.error || 'Erreur ' + response.status);
                    })
                    .catch(function (parseError) {
                        if (parseError instanceof Error && parseError.message) throw parseError;
                        throw new Error('Erreur ' + response.status);
                    });
            }
            return response.arrayBuffer();
        }).then(function (buffer) {
            return new Uint8Array(buffer);
        });
    }

    /* Périphérique à utiliser : le premier déjà autorisé, sinon on demande.
       `interactive` doit être vrai uniquement dans un gestionnaire de clic. */
    function resolveDevice(interactive) {
        return authorizedDevices().then(function (devices) {
            if (devices.length) return devices[0];
            if (!interactive) return null;
            return requestDevice();
        });
    }

    /* En-têtes à joindre aux requêtes qui encaissent (validation, suivi
       GeniusPay) : si ce poste imprime via WebUSB, le serveur s'abstient, sinon
       le ticket sortirait deux fois sur un poste où Django tourne en local. */
    function impressionHeaders() {
        return authorizedDevices().then(function (devices) {
            return { 'X-Impression-Poste': devices.length ? '1' : '0' };
        });
    }

    function printBytes(bytes, interactive) {
        return resolveDevice(interactive !== false).then(function (device) {
            if (!device) {
                throw new Error(
                    "Aucune imprimante autorisée. Ouvrez « Connexion d'imprimante USB » "
                    + "et cliquez sur « Détecter »."
                );
            }
            return send(device, bytes).then(function () { return device; });
        });
    }

    function printTest(interactive) {
        var url = urls().escposTest;
        if (!url) return Promise.reject(new Error('URL de test absente.'));
        return fetchBytes(url).then(function (bytes) {
            return printBytes(bytes, interactive);
        });
    }

    /* `interactive` doit valoir false hors d'un clic : le selecteur de
       peripheriques du navigateur exige un geste utilisateur et leverait une
       exception depuis un rappel asynchrone (impression apres paiement). */
    function printReceipt(ticketNumero, interactive) {
        var template = urls().escposRecu;
        if (!template) return Promise.reject(new Error('URL de reçu absente.'));
        var url = template.replace('TICKET_ID', encodeURIComponent(ticketNumero));
        return fetchBytes(url).then(function (bytes) {
            return printBytes(bytes, interactive);
        });
    }

    /* Impression automatique apres encaissement. Silencieuse si aucune
       imprimante n'a encore ete autorisee sur ce poste : le recu reste
       accessible en PDF depuis la liste des tickets, on n'interrompt pas le
       caissier au milieu d'une vente. */
    function autoPrintReceipt(ticketNumero) {
        if (!isSupported() || !ticketNumero) return Promise.resolve(false);
        return authorizedDevices().then(function (devices) {
            if (!devices.length) return false;
            return printReceipt(ticketNumero, false)
                .then(function () {
                    notify('success', 'Reçu imprimé.');
                    return true;
                })
                .catch(function (error) {
                    notify('warning', "Reçu non imprimé : " + (error.message || 'erreur inconnue'));
                    return false;
                });
        });
    }

    /* Réimpression d'un reçu, avec repli automatique.
       Si WebUSB n'est pas disponible, on ouvre le PDF du ticket : le caissier
       imprime depuis son navigateur. Le service reste utilisable partout. */
    function reprintReceipt(ticketNumero) {
        if (!isSupported()) {
            return fallbackToPdf(ticketNumero, "Ce navigateur ne gère pas WebUSB.");
        }
        return printReceipt(ticketNumero)
            .then(function () {
                notify('success', 'Reçu ' + ticketNumero + ' envoyé à l\'imprimante.');
            })
            .catch(function (error) {
                return fallbackToPdf(ticketNumero, error.message);
            });
    }

    function fallbackToPdf(ticketNumero, reason) {
        var template = urls().recuPdf;
        if (!template) {
            notify('error', reason || "Impression impossible.");
            return Promise.resolve();
        }
        var url = template.replace('TICKET_ID', encodeURIComponent(ticketNumero));
        return fetch(url, {
            method: 'POST',  // la vue est protegee par @require_POST
            credentials: 'same-origin',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken(),
            },
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data && data.success && data.pdf_url) {
                    notify('info', (reason ? reason + ' ' : '') + 'Ouverture du reçu PDF.');
                    global.open(data.pdf_url, '_blank', 'noopener');
                } else {
                    notify('error', (data && data.error) || reason || "Impression impossible.");
                }
            })
            .catch(function () {
                notify('error', reason || "Impression impossible.");
            });
    }

    /* Reçu FNE (facture normalisée électronique certifiée par la DGI). Il suit
       le reçu de caisse : le serveur ne le rend que pour une vente certifiée. */
    function printFneReceipt(ticketNumero, interactive) {
        var template = urls().escposFne;
        if (!template) return Promise.reject(new Error('URL de reçu FNE absente.'));
        var url = template.replace('TICKET_ID', encodeURIComponent(ticketNumero));
        return fetchBytes(url).then(function (bytes) {
            return printBytes(bytes, interactive);
        });
    }

    /* Impression automatique du reçu FNE, à enchaîner après autoPrintReceipt.
       Sans imprimante autorisée, on le signale : le client doit repartir avec
       sa facture certifiée, disponible en PDF depuis la liste des ventes. */
    function autoPrintFneReceipt(ticketNumero) {
        if (!ticketNumero) return Promise.resolve(false);
        return authorizedDevices().then(function (devices) {
            if (!devices.length) {
                notify('info', 'Reçu FNE à imprimer depuis la liste des ventes (bouton QR).');
                return false;
            }
            return printFneReceipt(ticketNumero, false)
                .then(function () {
                    notify('success', 'Reçu FNE imprimé.');
                    return true;
                })
                .catch(function (error) {
                    notify('warning', "Reçu FNE non imprimé : " + (error.message || 'erreur inconnue'));
                    return false;
                });
        });
    }

    /* Réimpression du reçu FNE, avec repli sur son PDF si WebUSB manque. */
    function reprintFneReceipt(ticketNumero) {
        if (!isSupported()) {
            return openFnePdf(ticketNumero, "Ce navigateur ne gère pas WebUSB.");
        }
        return printFneReceipt(ticketNumero)
            .then(function () {
                notify('success', "Reçu FNE " + ticketNumero + " envoyé à l'imprimante.");
            })
            .catch(function (error) {
                return openFnePdf(ticketNumero, error.message);
            });
    }

    function openFnePdf(ticketNumero, reason) {
        var template = urls().fnePdf;
        if (!template) {
            notify('error', reason || "Impression impossible.");
            return Promise.resolve();
        }
        notify('info', (reason ? reason + ' ' : '') + 'Ouverture du reçu FNE en PDF.');
        global.open(template.replace('TICKET_ID', encodeURIComponent(ticketNumero)), '_blank', 'noopener');
        return Promise.resolve();
    }

    /* Relance la certification DGI d'une vente encaissée dont la FNE a échoué. */
    function certifyFne(ticketNumero) {
        var template = urls().fneCertifier;
        if (!template) return Promise.reject(new Error('URL de certification FNE absente.'));
        if (!ticketNumero) return Promise.reject(new Error('Numéro de ticket manquant.'));
        return fetch(template.replace('TICKET_ID', encodeURIComponent(ticketNumero)), {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken(),
                'Accept': 'application/json',
            },
        })
            .then(function (r) {
                return r.text().then(function (text) {
                    var data = {};
                    if (text) {
                        try {
                            data = JSON.parse(text);
                        } catch (parseErr) {
                            data = {};
                        }
                    }
                    return { status: r.status, ok: r.ok, data: data };
                });
            })
            .then(function (result) {
                if (result.status === 403) {
                    throw new Error(
                        result.data.error
                        || 'Accès refusé : permission de certification FNE manquante.'
                    );
                }
                if (!result.data.success) {
                    throw new Error(
                        result.data.error
                        || (result.data.fne && result.data.fne.message)
                        || 'Certification FNE impossible.'
                    );
                }
                return result.data.fne;
            });
    }

    /* Bouton en attente pendant `work`, restauré en cas d'échec. */
    function withSpinner(btn, work) {
        var originalHTML = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i>';
        return Promise.resolve()
            .then(work)
            .then(
                function (value) {
                    btn.disabled = false;
                    btn.innerHTML = originalHTML;
                    return value;
                },
                function (error) {
                    btn.disabled = false;
                    btn.innerHTML = originalHTML;
                    throw error;
                }
            );
    }

    /* Boutons FNE des listes de ventes (partial _fne_actions.html), sur toute
       page qui charge ce module. */
    function onFneButtonClick(e) {
        if (!e.target || !e.target.closest) return;
        var reprint = e.target.closest('.reprint-fne');
        if (reprint) {
            e.preventDefault();
            e.stopPropagation();
            var reprintTicket = reprint.getAttribute('data-ticket') || reprint.dataset.ticket;
            notify('info', 'Impression du reçu FNE…');
            withSpinner(reprint, function () {
                return reprintFneReceipt(reprintTicket);
            }).catch(function (error) {
                notify('error', error.message || 'Impression FNE impossible.');
            });
            return;
        }
        var certify = e.target.closest('.certifier-fne');
        if (!certify) return;
        e.preventDefault();
        e.stopPropagation();
        var ticket = certify.getAttribute('data-ticket') || certify.dataset.ticket;
        if (!ticket) {
            notify('error', 'Numéro de ticket manquant sur le bouton FNE.');
            return;
        }
        notify('info', 'Certification FNE en cours…');
        withSpinner(certify, function () { return certifyFne(ticket); })
            .then(function (fne) {
                notify('success', (fne && fne.message) || 'Facture FNE certifiée.');
                // Le bouton devient celui de réimpression du reçu certifié.
                certify.classList.remove('certifier-fne', 'text-danger');
                certify.classList.add('reprint-fne');
                certify.title = 'Réimprimer le reçu FNE ' + ((fne && fne.reference) || '');
                certify.innerHTML = '<i class="fa fa-qrcode"></i>';
                return autoPrintFneReceipt(ticket);
            })
            .catch(function (error) {
                var msg = (error && error.message) || 'Certification FNE impossible.';
                certify.title = 'FNE non certifiée : ' + msg + ' — cliquer pour relancer';
                certify.classList.add('text-danger');
                notify('error', msg);
            });
    }

    /* Bon de commande mis en attente par la validation d'un panier.
       Celle-ci se termine par une redirection : l'impression ne peut pas partir
       dans sa reponse, c'est la page suivante qui reclame le ticket au serveur.
       L'endpoint ne le rend qu'une fois, sinon le bon se reimprimerait a chaque
       navigation. */
    function printOrderSlip(ticketNumero, interactive) {
        var template = urls().escposBon;
        if (!template) return Promise.reject(new Error('URL de bon absente.'));
        var url = template.replace('TICKET_ID', encodeURIComponent(ticketNumero));
        return fetchBytes(url).then(function (bytes) {
            return printBytes(bytes, interactive);
        });
    }

    function autoPrintPendingOrderSlip() {
        var url = urls().bonEnAttente;
        if (!url || !isSupported()) return Promise.resolve(false);
        return fetch(url, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
            .then(function (r) { return r.ok ? r.json() : {}; })
            .then(function (data) {
                if (!data || !data.ticket) return false;
                return authorizedDevices().then(function (devices) {
                    if (!devices.length) {
                        notify('warning',
                            "Bon de commande " + data.ticket + " non imprimé : "
                            + "aucune imprimante autorisée sur ce poste.");
                        return false;
                    }
                    return printOrderSlip(data.ticket, false)
                        .then(function () {
                            notify('success', 'Bon de commande ' + data.ticket + ' imprimé.');
                            return true;
                        })
                        .catch(function (error) {
                            notify('warning', "Bon non imprimé : " + (error.message || ''));
                            return false;
                        });
                });
            })
            .catch(function () { return false; });
    }

    function csrfToken() {
        if (global.AUTOPIECE_CSRF_TOKEN) {
            return String(global.AUTOPIECE_CSRF_TOKEN);
        }
        var meta = typeof document !== 'undefined'
            && document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.getAttribute('content')) {
            return meta.getAttribute('content');
        }
        var input = typeof document !== 'undefined'
            && document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input && input.value) {
            return input.value;
        }
        var match = typeof document !== 'undefined'
            && document.cookie
            && document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function notify(level, message) {
        if (!message) return;
        if (typeof global.toastr !== 'undefined' && typeof global.toastr[level] === 'function') {
            global.toastr[level](message);
            return;
        }
        if (typeof global.console !== 'undefined' && global.console[level === 'error' ? 'error' : 'log']) {
            global.console[level === 'error' ? 'error' : 'log']('[FNE]', message);
        }
        // Repli visible si toastr n'est pas chargé (évite l'impression « aucune action »).
        if (level === 'error' && typeof global.alert === 'function') {
            global.alert(message);
        }
    }

    if (typeof document !== 'undefined') {
        document.addEventListener('click', onFneButtonClick);
    }

    // Un bon peut attendre depuis la validation d'un panier : on regarde a
    // chaque chargement de page, sans jamais interrompre l'utilisateur.
    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', autoPrintPendingOrderSlip);
        } else {
            autoPrintPendingOrderSlip();
        }
    }

    global.AutoPiecePrinter = {
        isSupported: isSupported,
        describe: describe,
        authorizedDevices: authorizedDevices,
        requestDevice: requestDevice,
        resolveDevice: resolveDevice,
        send: send,
        fetchBytes: fetchBytes,
        printBytes: printBytes,
        impressionHeaders: impressionHeaders,
        printTest: printTest,
        printReceipt: printReceipt,
        autoPrintReceipt: autoPrintReceipt,
        printOrderSlip: printOrderSlip,
        autoPrintPendingOrderSlip: autoPrintPendingOrderSlip,
        reprintReceipt: reprintReceipt,
        printFneReceipt: printFneReceipt,
        autoPrintFneReceipt: autoPrintFneReceipt,
        reprintFneReceipt: reprintFneReceipt,
        certifyFne: certifyFne,
        notify: notify,
    };
})(window);
