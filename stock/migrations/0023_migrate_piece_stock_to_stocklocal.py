from django.db import migrations


def migrer_vers_stock_local(apps, schema_editor):
    Piece = apps.get_model('stock', 'Piece')
    StockLocal = apps.get_model('stock', 'StockLocal')
    EntrePiece = apps.get_model('stock', 'EntrePiece')
    LocalEntrepot = apps.get_model('Userauths', 'LocalEntrepot')

    default_local = LocalEntrepot.objects.first()

    for piece in Piece.objects.all().iterator():
        local_id = getattr(piece, 'local_piece_id', None)
        if not local_id and default_local:
            local_id = default_local.pk
        if not local_id:
            continue
        StockLocal.objects.update_or_create(
            piece_id=piece.pk,
            local_entrepot_id=local_id,
            defaults={
                'quantite_disponible': getattr(piece, 'quantite_disponible', 0) or 0,
                'seuil_local': piece.seuil or 0,
                'emplacement': piece.emplacement or '',
            },
        )

    for entree in EntrePiece.objects.filter(local_entrepot__isnull=True).iterator():
        local_id = entree.piece.local_piece_id if hasattr(entree.piece, 'local_piece_id') else None
        if not local_id and default_local:
            local_id = default_local.pk
        if local_id:
            entree.local_entrepot_id = local_id
            entree.save(update_fields=['local_entrepot_id'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0022_stocklocal_transfertstock'),
    ]

    operations = [
        migrations.RunPython(migrer_vers_stock_local, noop),
    ]
