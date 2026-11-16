from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Answer, Category, Question


class QuestionForm(forms.ModelForm):
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.order_by('name'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label='Категории',
    )

    class Meta:
        model = Question
        fields = ['title', 'text', 'image', 'categories']
        labels = {
            'title': 'Название вопроса',
            'text': 'Текст вопроса',
            'image': 'Картинка (необязательно)',
        }
        widgets = {
            'text': forms.Textarea(attrs={'rows': 6}),
        }


class AnswerForm(forms.ModelForm):
    class Meta:
        model = Answer
        fields = ['text']


class SignUpForm(UserCreationForm):
    email = forms.EmailField(max_length=254, help_text='Required. Inform a valid email address.')

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')
