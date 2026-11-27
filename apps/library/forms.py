"""Library forms: the librarian's book review/edit form."""
from django import forms

from apps.library.models import Book, Category, Tag
from apps.authors.models import Author


class BookForm(forms.ModelForm):
    """Pre-filled from extracted metadata; the librarian reviews every field."""

    authors_text = forms.CharField(
        required=False, label="Authors",
        help_text="Comma-separated, e.g. “Ursula K. Le Guin, Terry Pratchett”.",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    categories_text = forms.CharField(
        required=False, label="Categories",
        help_text="Comma-separated.",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    tags_text = forms.CharField(
        required=False, label="Tags",
        help_text="Comma-separated.",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = Book
        fields = [
            "title", "subtitle", "description", "isbn", "language",
            "publication_date", "publisher", "pages", "series", "series_order",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "subtitle": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "isbn": forms.TextInput(attrs={"class": "form-control"}),
            "language": forms.TextInput(attrs={"class": "form-control"}),
            "publication_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "publisher": forms.TextInput(attrs={"class": "form-control"}),
            "pages": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "series": forms.Select(attrs={"class": "form-select"}),
            "series_order": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["series"].required = False
        if self.instance.pk:
            self.fields["authors_text"].initial = ", ".join(
                self.instance.authors.values_list("name", flat=True)
            )
            self.fields["categories_text"].initial = ", ".join(
                self.instance.categories.values_list("name", flat=True)
            )
            self.fields["tags_text"].initial = ", ".join(
                self.instance.tags.values_list("name", flat=True)
            )

    def save(self, commit=True):
        book = super().save(commit=commit)
        if commit:
            self._apply_m2m(book)
        return book

    def _apply_m2m(self, book: Book) -> None:
        from django.utils.text import slugify

        for name in _split(self.cleaned_data.get("authors_text")):
            author, _ = Author.objects.get_or_create(name=name)
            book.authors.add(author)
        for name in _split(self.cleaned_data.get("categories_text")):
            cat, _ = Category.objects.get_or_create(
                name=name, defaults={"slug": slugify(name)[:140] or "cat"}
            )
            book.categories.add(cat)
        for name in _split(self.cleaned_data.get("tags_text")):
            tag, _ = Tag.objects.get_or_create(
                name=name, defaults={"slug": slugify(name)[:140] or "tag"}
            )
            book.tags.add(tag)
        book.refresh_search_text()


def _split(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]
