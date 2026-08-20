from rest_framework import serializers

from stock.models import Commande


class OrderListSerializer(serializers.ModelSerializer):
    numero_commande = serializers.CharField()
    localite_nom = serializers.CharField(source='panier.local_entrepot.nom', read_only=True)
    mode_reception = serializers.CharField(source='panier.mode_reception', read_only=True)
    statut_label = serializers.SerializerMethodField()

    class Meta:
        model = Commande
        fields = [
            'id', 'numero_commande', 'statut_commande', 'statut_label',
            'total', 'paye', 'date', 'localite_nom', 'mode_reception',
            'client_confirme_reception',
        ]

    def get_statut_label(self, obj):
        return dict(Commande._meta.get_field('statut_commande').choices).get(
            obj.statut_commande, obj.statut_commande,
        )


class OrderItemSerializer(serializers.Serializer):
    piece_id = serializers.IntegerField()
    designation = serializers.CharField()
    quantite = serializers.IntegerField()
    prix_unitaire = serializers.DecimalField(max_digits=12, decimal_places=2)
    prix_total = serializers.DecimalField(max_digits=12, decimal_places=2)


class OrderDetailSerializer(OrderListSerializer):
    items = OrderItemSerializer(many=True)
    sous_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    frais_livraison = serializers.DecimalField(max_digits=12, decimal_places=2)
    adresse_livraison = serializers.DictField(required=False)
    ticket_numero = serializers.CharField(source='panier.ticket', read_only=True)
    invoice_url = serializers.SerializerMethodField()

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + [
            'items', 'sous_total', 'frais_livraison', 'adresse_livraison',
            'ticket_numero', 'invoice_url', 'date_reception_client',
        ]

    def get_invoice_url(self, obj):
        request = self.context.get('request')
        if not request:
            return None
        return request.build_absolute_uri(f'/api/v1/orders/{obj.pk}/invoice/')
