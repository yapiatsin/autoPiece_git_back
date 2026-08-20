from rest_framework import serializers

from stock.models import Categorie, Piece


class CategorieSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categorie
        fields = ['cid', 'categorie']


class LocaliteSerializer(serializers.Serializer):
    code = serializers.UUIDField()
    nom = serializers.CharField()
    nb_pieces = serializers.IntegerField(required=False)


class PieceCardSerializer(serializers.Serializer):
    """Carte produit style Cdiscount."""
    id = serializers.IntegerField()
    designation = serializers.CharField()
    slug = serializers.CharField()
    numero_piece = serializers.CharField()
    image_url = serializers.CharField(allow_null=True)
    prix_affiche = serializers.DecimalField(max_digits=12, decimal_places=2)
    quantite_stock = serializers.IntegerField(allow_null=True)
    en_stock = serializers.BooleanField()
    categorie = CategorieSerializer()
    url_path = serializers.CharField()
    est_favori = serializers.BooleanField(default=False)
    quantite_panier = serializers.IntegerField(default=0)
    localite_code = serializers.CharField(allow_blank=True)
    localite_nom = serializers.CharField(allow_blank=True)


class PieceDetailSerializer(PieceCardSerializer):
    description_html = serializers.CharField(allow_blank=True, required=False)
    stocks_par_localite = serializers.ListField(child=serializers.DictField(), required=False)


def build_piece_card(
    piece: Piece,
    *,
    request,
    prix_affiche,
    quantite=None,
    localite_code='',
    localite_nom='',
    est_favori=False,
    quantite_panier=0,
) -> dict:
    image_url = None
    if piece.image:
        image_url = request.build_absolute_uri(piece.image.url) if request else piece.image.url
    en_stock = quantite is None or quantite > 0
    return {
        'id': piece.pk,
        'designation': piece.designation,
        'slug': piece.slug,
        'numero_piece': piece.numero_piece,
        'image_url': image_url,
        'prix_affiche': prix_affiche,
        'quantite_stock': quantite,
        'en_stock': en_stock,
        'categorie': {'cid': piece.categorie.cid, 'categorie': piece.categorie.categorie},
        'url_path': piece.get_absolute_url(),
        'est_favori': est_favori,
        'quantite_panier': quantite_panier,
        'localite_code': localite_code,
        'localite_nom': localite_nom,
    }


def row_to_piece_card(row, request, *, favori_ids=None, panier_qty_by_piece=None):
    piece = row['piece']
    favori_ids = favori_ids or set()
    panier_qty_by_piece = panier_qty_by_piece or {}
    return build_piece_card(
        piece,
        request=request,
        prix_affiche=row['prix_affiche'],
        quantite=row.get('quantite'),
        localite_code=row.get('localite_code', ''),
        localite_nom=row.get('localite_nom', ''),
        est_favori=piece.pk in favori_ids,
        quantite_panier=panier_qty_by_piece.get(piece.pk, 0),
    )
