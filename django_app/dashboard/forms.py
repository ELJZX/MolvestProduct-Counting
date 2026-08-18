"""Формы приложения."""
from django import forms

from .models import Product, Shop


class ProductForm(forms.ModelForm):
    """Форма продукта (код, название, цех, код 1С, цвет, изображение)."""

    class Meta:
        model = Product
        fields = ['code', 'name', 'shop', 'code_1c', 'color', 'image', 'description']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control',
                                           'maxlength': 3, 'placeholder': '001'}),
            'name': forms.TextInput(attrs={'class': 'form-control',
                                           'placeholder': 'Молоко 3,2%'}),
            'shop': forms.Select(attrs={'class': 'form-select'}),
            'code_1c': forms.TextInput(attrs={'class': 'form-control',
                                              'placeholder': 'Например: 00-00012345'}),
            'color': forms.TextInput(attrs={'class': 'form-control form-control-color',
                                            'type': 'color', 'id': 'id_color_picker'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Пустой вариант «— без цеха —» (общий продукт)
        self.fields['shop'].empty_label = '— без цеха (общий продукт) —'
        self.fields['shop'].queryset = Shop.objects.order_by('code')
        self.fields['shop'].required = False

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip().zfill(3)
        if not (code.isdigit() and 1 <= int(code) <= 999):
            raise forms.ValidationError('Код должен быть числом в диапазоне 001..999.')
        return code

    def clean_color(self):
        color = (self.cleaned_data.get('color') or '').strip()
        if not color.startswith('#') or len(color) != 7:
            raise forms.ValidationError('Укажите цвет в формате #RRGGBB.')
        return color
