from rest_framework import serializers


class CheckoutConfirmSerializer(serializers.Serializer):
    mode_reception = serializers.ChoiceField(choices=['livraison', 'retrait'], default='livraison')
    pays_id = serializers.IntegerField(required=False, allow_null=True)
    ville_id = serializers.IntegerField(required=False, allow_null=True)
    commune_id = serializers.IntegerField(required=False, allow_null=True)
    adresse_domicile = serializers.CharField(required=False, allow_blank=True, max_length=255)
    telephone_livraison = serializers.CharField(required=False, allow_blank=True, max_length=20)
    instruction_livraison = serializers.CharField(required=False, allow_blank=True)
    accepte_cgv = serializers.BooleanField()

    def validate(self, attrs):
        if not attrs.get('accepte_cgv'):
            raise serializers.ValidationError({'accepte_cgv': 'Vous devez accepter les conditions générales.'})
        if attrs.get('mode_reception') == 'livraison':
            for field in ('pays_id', 'ville_id', 'commune_id'):
                if not attrs.get(field):
                    raise serializers.ValidationError({field: 'Champ requis pour la livraison.'})
            if not (attrs.get('adresse_domicile') or '').strip():
                raise serializers.ValidationError({'adresse_domicile': 'Adresse requise.'})
        return attrs
