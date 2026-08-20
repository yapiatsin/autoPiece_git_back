from rest_framework import serializers

from Userauths.models import ProfilUser


class AccountProfileSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    contact = serializers.CharField(source='user.contact', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = ProfilUser
        fields = [
            'first_name', 'last_name', 'email', 'contact', 'username',
            'date_naissance', 'bio', 'photo',
        ]


class AccountAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProfilUser
        fields = ['adresse', 'ville', 'pays', 'code_postal']
