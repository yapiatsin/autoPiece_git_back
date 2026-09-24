"""Reçu FNE (facture normalisée électronique) : mise en page partagée thermique / PDF.

Le reçu reprend ce que la DGI a certifié : numéro FNE, NCC, articles envoyés,
montants renvoyés par la plateforme et QR code du lien de vérification.
"""
from __future__ import annotations

import textwrap
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from stock.fne_service import LIBELLES_TAXE, _env
from stock.receipt_layout import (
    DESIGNATION_COL,
    RECEIPT_INNER,
    caissier_label,
    spaced_line,
    total_line,
)

TITRE = 'FACTURE NORMALISEE ELECTRONIQUE'

# Éléments de mise en page : ('text', texte, align, style) ou ('qr', donnée).
# style : 'title', 'subtitle', 'bold' ou ''.


def _date_label(facture) -> str:
    date = facture.date_certification or facture.date_creation
    return timezone.localtime(date).strftime('%d/%m/%Y %H:%M') if date else ''


def _ht_brut(items) -> Decimal:
    return sum(
        (Decimal(str(i.get('amount') or 0)) * Decimal(str(i.get('quantity') or 0)) for i in items),
        Decimal('0'),
    )


def build_fne_receipt_elements(facture, width: int = RECEIPT_INNER):
    commande = facture.commande
    payload = facture.payload or {}
    items = payload.get('items') or []
    elements = []

    def add(text='', align='left', style=''):
        elements.append(('text', text, align, style))

    add('P&B Auto-Pieces', 'center', 'title')
    ncc = facture.ncc or _env('FNE_NCC') or ''
    if ncc:
        add(f'NCC : {ncc}', 'center', 'bold')
    add('*' * width, 'center')
    add(TITRE, 'center', 'subtitle')
    add('*' * width, 'center')
    add(spaced_line('N° FNE', facture.reference, width), style='bold')
    add(spaced_line('Date', _date_label(facture), width))
    if facture.etablissement:
        add(f'Etablissement : {facture.etablissement}'[:width])
    if facture.point_de_vente and facture.point_de_vente != facture.etablissement:
        add(f'Point de vente : {facture.point_de_vente}'[:width])
    ticket = getattr(commande, 'ticket', None)
    if ticket:
        add(spaced_line('Ref. caisse', ticket.numero, width))
    add(f'Caissier : {caissier_label(commande)}'[:width])
    add(f"Client : {payload.get('clientCompanyName') or '—'}"[:width])
    add('-' * width, 'center')

    add(f"{'Désignation':<20}{'Qte':>4}{'PU HT':>7}{'Tot':>7}", style='bold')
    for item in items:
        qte = int(Decimal(str(item.get('quantity') or 0)))
        pu = Decimal(str(item.get('amount') or 0))
        wrapped = textwrap.wrap(str(item.get('description') or ''), width=DESIGNATION_COL) or ['']
        add(f'{wrapped[0]:<20}{qte:>4}{int(pu):>7}{int(pu * qte):>7}')
        for extra in wrapped[1:]:
            add(extra)
    add('-' * width, 'center')

    ht = _ht_brut(items)
    add(total_line('Total HT', ht, width))
    remise = Decimal(str(payload.get('discount') or 0))
    if remise > 0:
        add(spaced_line('Remise', f'-{remise.quantize(Decimal("0.01"))} %', width))
        net = (ht * (Decimal('100') - remise) / Decimal('100')).quantize(
            Decimal('1'), rounding=ROUND_HALF_UP
        )
        add(total_line('Total HT net', net, width))
    taxes = (items[0].get('taxes') or ['']) if items else ['']
    add(total_line(LIBELLES_TAXE.get(taxes[0], 'TVA'), facture.montant_tva, width))
    if facture.timbre and facture.timbre > 0:
        add(total_line('Timbre de quittance', facture.timbre, width))
    add(total_line('TOTAL TTC', facture.montant_ttc, width), style='bold')
    add(spaced_line('Paiement', 'Espèces', width))
    add('-' * width, 'center')

    if facture.url_verification:
        elements.append(('qr', facture.url_verification))
        add('Scannez pour vérifier cette facture', 'center')
        for part in textwrap.wrap(facture.url_verification, width=width, break_on_hyphens=False):
            add(part, 'center')
    add('Facture certifiée par la DGI', 'center')
    return elements


# --------------------------------------------------------------------- PDF


def render_fne_receipt_pdf(facture) -> bytes:
    """PDF 80 mm du reçu FNE : repli quand le poste n'a pas d'imprimante WebUSB."""
    import io

    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.pdfgen import canvas

    from stock.receipt_ticket_pdf import (
        FONT_NAME,
        FONT_SIZE,
        FONT_SIZE_SUBTITLE,
        FONT_SIZE_TITLE,
        LINE_HEIGHT,
        MARGIN_H,
        MARGIN_V,
        RECEIPT_WIDTH,
        _page_height,
    )

    qr_size = 40 * 2.8346  # 40 mm en points
    elements = build_fne_receipt_elements(facture)
    nb_lignes = sum(1 for e in elements if e[0] == 'text')
    nb_qr = sum(1 for e in elements if e[0] == 'qr')
    page_h = _page_height(nb_lignes) + nb_qr * (qr_size + LINE_HEIGHT)
    page_w = RECEIPT_WIDTH

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_w, page_h))
    c.setTitle(f'FNE {facture.reference}')
    y = page_h - MARGIN_V
    fonts = {
        'title': (f'{FONT_NAME}-Bold', FONT_SIZE_TITLE),
        'subtitle': (f'{FONT_NAME}-Bold', FONT_SIZE_SUBTITLE),
        'bold': (f'{FONT_NAME}-Bold', FONT_SIZE),
    }
    for element in elements:
        if element[0] == 'qr':
            widget = QrCodeWidget(element[1])
            x0, y0, x1, y1 = widget.getBounds()
            drawing = Drawing(
                qr_size, qr_size,
                transform=[qr_size / (x1 - x0), 0, 0, qr_size / (y1 - y0), 0, 0],
            )
            drawing.add(widget)
            y -= qr_size
            renderPDF.draw(drawing, c, (page_w - qr_size) / 2, y)
            y -= LINE_HEIGHT / 2
            continue
        _, text, align, style = element
        c.setFont(*fonts.get(style, (FONT_NAME, FONT_SIZE)))
        if align == 'center':
            c.drawCentredString(page_w / 2, y, text)
        else:
            c.drawString(MARGIN_H, y, text)
        y -= LINE_HEIGHT
    c.save()
    return buffer.getvalue()
