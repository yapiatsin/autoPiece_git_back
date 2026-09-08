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

    function csrfToken() {
        var match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? match[1] : '';
    }

    function notify(level, message) {
        if (typeof global.toastr !== 'undefined' && global.toastr[level]) {
            global.toastr[level](message);
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
        printTest: printTest,
        printReceipt: printReceipt,
        autoPrintReceipt: autoPrintReceipt,
        reprintReceipt: reprintReceipt,
        notify: notify,
    };
})(window);
