from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from .models import Answer, Category, Question


class QuestionForm(forms.ModelForm):
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.order_by('name'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_('Categories'),
    )

    class Meta:
        model = Question
        fields = ['title', 'text', 'image', 'categories']
        labels = {
            'title': _('Title'),
            'text': _('Question'),
            'image': _('Picture (optional)'),
        }
        widgets = {
            'text': forms.Textarea(attrs={'rows': 8}),
        }


class AnswerForm(forms.ModelForm):
    class Meta:
        model = Answer
        fields = ['text']
        labels = {'text': _('Answer')}
        widgets = {
            'text': forms.Textarea(attrs={'rows': 5}),
        }


class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        max_length=254,
        label=_('E-mail'),
        help_text=_('Used for notifications about your questions.'),
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')
