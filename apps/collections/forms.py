"""Collection form."""
from django import forms

from apps.collections.models import Collection


class CollectionForm(forms.ModelForm):
    class Meta:
        model = Collection
        fields = ["name", "description", "visibility"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "visibility": forms.Select(attrs={"class": "form-select"}),
        }
