from rest_framework import serializers

from stock.models import PanierItem


class CartItemSerializer(serializers.ModelSerializer):
    piece_id = serializers.IntegerField(source='piece.id', read_only=True)
    designation = serializers.CharField(source='piece.designation', read_only=True)
    slug = serializers.CharField(source='piece.slug', read_only=True)
    image_url = serializers.SerializerMethodField()
    prix_unitaire = serializers.DecimalField(
        source='prix_unitaire_applique', max_digits=12, decimal_places=2, read_only=True,
    )
    prix_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    stock_disponible = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = PanierItem
        fields = [
            'id', 'piece_id', 'designation', 'slug', 'image_url',
            'quantite', 'prix_unitaire', 'prix_total', 'stock_disponible',
        ]

    def get_image_url(self, obj):
        if not obj.piece.image:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.piece.image.url)
        return obj.piece.image.url


class CartSerializer(serializers.Serializer):
    id = serializers.CharField()
    localite = serializers.DictField()
    items = CartItemSerializer(many=True)
    sous_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_quantite = serializers.IntegerField()
    free_shipping_threshold = serializers.DecimalField(max_digits=12, decimal_places=2)


class CartAddItemSerializer(serializers.Serializer):
    piece_id = serializers.IntegerField()
    quantite = serializers.IntegerField(min_value=1, default=1)


class CartUpdateItemSerializer(serializers.Serializer):
    quantite = serializers.IntegerField(min_value=0)


class CartSetPieceQtySerializer(serializers.Serializer):
    quantite = serializers.IntegerField(min_value=0)
