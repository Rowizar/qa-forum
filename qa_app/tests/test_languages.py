
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from qa_app.models import Answer, Question


class LanguageTests(TestCase):
    """The interface is in English or Russian: the browser's language by default, or the visitor's choice."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('asker', 'asker@example.com', 'pass12345')
        cls.question = Question.objects.create(author=cls.user, title='Mine', text='text')

    def test_follows_the_language_of_the_browser(self):
        russian = self.client.get(reverse('feed'), HTTP_ACCEPT_LANGUAGE='ru-RU,ru;q=0.9,en;q=0.8')
        self.assertContains(russian, '<html lang="ru">')
        self.assertContains(russian, 'Лента')
        self.assertContains(russian, 'Задать вопрос')
        english = self.client.get(reverse('feed'), HTTP_ACCEPT_LANGUAGE='en-GB,en;q=0.9')
        self.assertContains(english, '<html lang="en">')
        self.assertContains(english, 'Ask a question')

    def test_other_languages_get_english(self):
        response = self.client.get(reverse('feed'), HTTP_ACCEPT_LANGUAGE='de-DE,de;q=0.9')
        self.assertContains(response, '<html lang="en">')

    def test_switch_overrides_the_browser_and_is_remembered(self):
        response = self.client.post(
            reverse('set_language'), {'language': 'ru', 'next': reverse('popular')})
        self.assertRedirects(response, reverse('popular'), fetch_redirect_response=False)
        response = self.client.get(reverse('popular'), HTTP_ACCEPT_LANGUAGE='en')
        self.assertContains(response, 'Популярные')
        # ...and back again.
        self.client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        response = self.client.get(reverse('popular'), HTTP_ACCEPT_LANGUAGE='ru')
        self.assertContains(response, 'Popular')

    def test_switch_is_on_every_page_and_marks_the_current_language(self):
        response = self.client.get(reverse('login'), HTTP_ACCEPT_LANGUAGE='ru')
        self.assertContains(response, 'action="{}"'.format(reverse('set_language')))
        self.assertContains(response, 'aria-pressed="true">RU</button>')
        self.assertContains(response, 'aria-pressed="false">EN</button>')

    def test_russian_plural_forms(self):
        url = reverse('question_detail', args=[self.question.id])
        expected = {0: '0 ответов', 1: '1 ответ', 2: '2 ответа', 5: '5 ответов'}
        for count, text in expected.items():
            while self.question.answer_set.count() < count:
                Answer.objects.create(user=self.user, question=self.question, text='answer')
            with self.subTest(count=count):
                self.assertContains(self.client.get(url, HTTP_ACCEPT_LANGUAGE='ru'), text)

    def test_form_errors_and_notices_are_translated(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('ask_question'), {'title': ''}, HTTP_ACCEPT_LANGUAGE='ru')
        self.assertContains(response, 'Обязательное поле.')
        response = self.client.post(
            reverse('ask_question'), {'title': 'Как?', 'text': 'Вот так'},
            HTTP_ACCEPT_LANGUAGE='ru', follow=True)
        self.assertContains(response, 'Вопрос опубликован.')

    def test_email_uses_the_language_of_the_author(self):
        self.client.force_login(self.user)
        self.client.post(reverse('ask_question'), {'title': 'Как?', 'text': 'Вот так'}, HTTP_ACCEPT_LANGUAGE='ru')
        self.client.post(reverse('ask_question'), {'title': 'How?', 'text': 'Like this'}, HTTP_ACCEPT_LANGUAGE='en')
        self.assertEqual(mail.outbox[0].subject, 'Ваш вопрос опубликован')
        self.assertIn('«Как?»', mail.outbox[0].body)
        self.assertEqual(mail.outbox[1].subject, 'Your question has been posted')
