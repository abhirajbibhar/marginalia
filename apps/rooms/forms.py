"""Room form."""
from django import forms

from apps.rooms.models import ReadingRoom


class RoomForm(forms.ModelForm):
    class Meta:
        model = ReadingRoom
        fields = ["name", "expires_at"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "maxlength": 200}),
            "expires_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expires_at"].required = False
