from django import forms
from .models import Categorie, SousCategorie, EntrePiece, Piece, Fournisseur, MoyenPaiement, StockLocal
from Userauths.models import CustomUser, LocalEntrepot
from django.forms import DateInput

class DateForm(forms.Form):
    date_debut = forms.DateField(widget=forms.DateInput(attrs={'type': 'date','class':'form-control'}), required=False)
    date_fin = forms.DateField(widget=forms.DateInput(attrs={'type': 'date','class':'form-control'}), required=False)
    categorie = forms.ModelChoiceField(
        queryset=Categorie.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control', 'data-sous-target': '#id_sous_categorie'}),
        empty_label="Toutes les catégories"
    )
    sous_categorie = forms.ModelChoiceField(
        queryset=SousCategorie.objects.filter(actif=True).select_related('categorie').order_by(
            'categorie__categorie', 'ordre', 'nom'
        ),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="Toutes les sous-catégories"
    )
    caissier = forms.ModelChoiceField(
        queryset=CustomUser.objects.filter(role='caissier'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="Tous les caissiers"
    )
    moyen_paiement = forms.ModelChoiceField(
        queryset=MoyenPaiement.objects.filter(actif=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="Tous les moyens de paiement"
    )
    localite = forms.ModelChoiceField(
        queryset=LocalEntrepot.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="Toutes les localités"
    )


class CategorieForm(forms.ModelForm):
    class Meta:
        model = Categorie
        fields = ('categorie', 'description', 'image',)
        widgets = {
            'categorie': forms.TextInput(attrs={'class':'form-control',"placeholder":"Nom de la categorie"}),
            'description': forms.Textarea(attrs={'class':'form-control',"placeholder":"Description...","row":"3"}),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
        }


class SousCategorieForm(forms.ModelForm):
    class Meta:
        model = SousCategorie
        fields = ('categorie', 'nom', 'description', 'image', 'ordre', 'actif')
        widgets = {
            'categorie': forms.Select(attrs={'class': 'form-control'}),
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom de la sous-catégorie'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 'placeholder': 'Description...', 'rows': '3',
            }),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'ordre': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'actif': forms.CheckboxInput(attrs={'id': 'id_sous_categorie_actif'}),
        }


def _sous_categorie_queryset(categorie=None):
    qs = SousCategorie.objects.filter(actif=True).select_related('categorie').order_by(
        'ordre', 'nom'
    )
    if categorie is not None:
        qs = qs.filter(categorie=categorie)
    return qs


class PieceForm(forms.ModelForm):
    class Meta:
        model = Piece
        exclude = ['categorie', 'utilisateur']
        widgets = {
            'numero_piece': forms.TextInput(attrs={'class':'form-control',"placeholder":"N°000A"}),
            'designation': forms.TextInput(attrs={'class':'form-control',"placeholder":"Nom..."}),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'sous_categorie': forms.Select(attrs={'class': 'form-control'}),
            'prix_achat': forms.NumberInput(attrs={'class':'form-control',"placeholder":"0","min":"0"}),
            'prix_unitaire': forms.NumberInput(attrs={
                'class': 'form-control', 'placeholder': 'Prix catalogue', 'min': '0',
            }),
            'seuil': forms.NumberInput(attrs={'class':'form-control',"placeholder":"", "min":"0"}),
            'emplacement': forms.TextInput(attrs={'class':'form-control',"placeholder":"E1 R1",}),
        }

    def __init__(self, *args, categorie=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sous_categorie'].queryset = _sous_categorie_queryset(categorie)
        self.fields['sous_categorie'].required = False
        self.fields['sous_categorie'].empty_label = 'Aucune'


class UpdatePieceForm(forms.ModelForm):
    class Meta:
        model = Piece
        fields = (
            'categorie', 'sous_categorie', 'numero_piece', 'designation', 'image',
            'prix_achat', 'prix_unitaire', 'seuil', 'emplacement',
        )
        widgets = {
            'categorie': forms.Select(attrs={'class': 'form-control'}),
            'sous_categorie': forms.Select(attrs={'class': 'form-control'}),
            'numero_piece': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'N°000A'}),
            'designation': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Désignation...'}),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'prix_achat': forms.NumberInput(attrs={
                'class': 'form-control', 'placeholder': '0', 'min': '0', 'step': '0.01',
            }),
            'prix_unitaire': forms.NumberInput(attrs={
                'class': 'form-control', 'placeholder': 'Prix catalogue', 'min': '0', 'step': '0.01',
            }),
            'seuil': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0', 'min': '0'}),
            'emplacement': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'E1 R1'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sous_categorie'].queryset = _sous_categorie_queryset()
        self.fields['sous_categorie'].required = False
        self.fields['sous_categorie'].empty_label = 'Aucune'
        self.fields['image'].required = False
        self.fields['emplacement'].required = False
        for name in ('prix_achat', 'prix_unitaire'):
            self.fields[name].localize = False
            self.fields[name].widget.is_localized = False

class StockLocalPrixForm(forms.Form):
    prix_unitaire_local = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=10,
        decimal_places=2,
        label='Prix de vente (localité)',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
            'step': '0.01',
            'placeholder': 'Laisser vide = prix catalogue',
        }),
    )


class EntrePieceForm(forms.ModelForm):
    class Meta:
        model = EntrePiece
        exclude = ['utilisateur','piece',]
        widgets = {
            'prix_achat': forms.NumberInput(attrs={'class':'form-control', "min":"0", "step":"0.01"}),
            'quantitajout': forms.NumberInput(attrs={'class':'form-control', "min":"0"}),
            'fournisseur': forms.Select(attrs={'class':'form-control',}),
        }
  
class FournisseurForm(forms.ModelForm):
    class Meta:
        model = Fournisseur
        fields = ['nom', 'contact',]
        widgets = {
            'nom': forms.TextInput(attrs={'class':'form-control',"placeholder":"Nom"}),
            'contact': forms.TextInput(attrs={'class':'form-control',"placeholder":"(+)....",}),
        }
        
        
class AjouterAuPanierForm(forms.Form):
    pieces = forms.ModelMultipleChoiceField(queryset=Piece.objects.all(), widget=forms.CheckboxSelectMultiple)
    quantites = forms.CharField(widget=forms.HiddenInput)

