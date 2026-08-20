from django import forms

from Userauths.models import ProfilUser

from .models import NewsletterAbonne


ECOM_ACCOUNT_INPUT = {
    'class': 'ecom-account-input',
}


class EcomAccountProfileForm(forms.ModelForm):
    first_name = forms.CharField(
        label='Prénom',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={**ECOM_ACCOUNT_INPUT, 'placeholder': 'Prénom'}),
    )
    last_name = forms.CharField(
        label='Nom',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={**ECOM_ACCOUNT_INPUT, 'placeholder': 'Nom'}),
    )
    contact = forms.CharField(
        label='Téléphone',
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={**ECOM_ACCOUNT_INPUT, 'placeholder': '+225 …'}),
    )

    class Meta:
        model = ProfilUser
        fields = ('date_naissance', 'bio')
        widgets = {
            'date_naissance': forms.DateInput(
                attrs={**ECOM_ACCOUNT_INPUT, 'type': 'date'},
                format='%Y-%m-%d',
            ),
            'bio': forms.Textarea(
                attrs={**ECOM_ACCOUNT_INPUT, 'rows': 3, 'placeholder': 'Quelques mots sur vous…'},
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['contact'].initial = user.contact

    def save(self, commit=True):
        profil = super().save(commit=commit)
        if self.user is not None:
            self.user.first_name = self.cleaned_data.get('first_name', '')
            self.user.last_name = self.cleaned_data.get('last_name', '')
            self.user.contact = self.cleaned_data.get('contact', '')
            if commit:
                self.user.save(update_fields=['first_name', 'last_name', 'contact'])
        return profil


class EcomAccountAddressForm(forms.ModelForm):
    class Meta:
        model = ProfilUser
        fields = ('adresse', 'ville', 'pays', 'code_postal')
        widgets = {
            'adresse': forms.TextInput(attrs={**ECOM_ACCOUNT_INPUT, 'placeholder': 'Rue, quartier, immeuble…'}),
            'ville': forms.TextInput(attrs={**ECOM_ACCOUNT_INPUT, 'placeholder': 'Ville'}),
            'pays': forms.TextInput(attrs={**ECOM_ACCOUNT_INPUT, 'placeholder': 'Pays'}),
            'code_postal': forms.TextInput(attrs={**ECOM_ACCOUNT_INPUT, 'placeholder': 'Code postal'}),
        }


class NewsletterForm(forms.ModelForm):
    class Meta:
        model = NewsletterAbonne
        fields = ('email', 'accepte_offres')
        widgets = {
            'email': forms.EmailInput(
                attrs={
                    'placeholder': 'Votre adresse e-mail',
                    'required': True,
                    'autocomplete': 'email',
                }
            ),
            'accepte_offres': forms.CheckboxInput(),
        }

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()
