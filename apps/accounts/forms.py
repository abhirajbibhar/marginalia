"""Account forms."""
from django import forms

from apps.accounts.models import LayerPreference, Profile


class ProfileForm(forms.ModelForm):
    email = forms.EmailField(required=False)

    class Meta:
        model = Profile
        fields = ["display_name", "theme", "default_layer", "avatar"]
        widgets = {
            "display_name": forms.TextInput(attrs={"class": "form-control", "maxlength": 120}),
            "theme": forms.Select(attrs={"class": "form-select"}),
            "default_layer": forms.Select(attrs={"class": "form-select"}),
            "avatar": forms.HiddenInput(),  # storage key; set by the upload widget
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_layer"].choices = LayerPreference.choices
        self.fields["theme"].choices = [("auto", "Auto"), ("light", "Light"), ("dark", "Dark")]
