from django import forms
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _lazy

from core.models import Recipe


class RecipeForm(forms.ModelForm):
    ingredient_text = forms.CharField(
        label=_lazy("Ingredienser"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 12, "placeholder": "500 g mjölig potatis\n0,5 förp vegobullar\n2 dl havredryck\nSalt"}),
        help_text=_lazy("En ingrediens per rad: mängd, enhet, ingrediens. Anteckning efter komma."),
    )
    image_url = forms.URLField(required=False, widget=forms.HiddenInput, assume_scheme="https")
    source_url = forms.URLField(required=False, widget=forms.HiddenInput, assume_scheme="https")
    remove_image = forms.BooleanField(label=_lazy("Ta bort bilden"), required=False)

    class Meta:
        model = Recipe
        fields = ["name", "description", "image", "servings", "minutes", "instructions", "source_url"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "instructions": forms.Textarea(attrs={"rows": 10}),
            "image": forms.FileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.initial.setdefault("ingredient_text", self.instance.ingredient_text())

    def clean_servings(self):
        s = self.cleaned_data["servings"]
        if not s or s < 1:
            raise forms.ValidationError(gettext("Minst 1 portion."))
        return s
