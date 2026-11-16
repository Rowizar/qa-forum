
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from qa_app.models import Answer, Question


class ApiPermissionTests(TestCase):
    """REST API: anyone can read, only the author can write."""

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user('author', password='pass12345')
        cls.stranger = User.objects.create_user('stranger', password='pass12345')
        cls.question = Question.objects.create(author=cls.author, title='API question', text='text')
        cls.answer = Answer.objects.create(user=cls.author, question=cls.question, text='answer')
        cls.question_url = reverse('question-detail', args=[cls.question.id])
        cls.answer_url = reverse('answer-detail', args=[cls.answer.id])
        cls.close_url = reverse('question-close', args=[cls.question.id])

    def setUp(self):
        self.client = APIClient()

    def test_anonymous_can_read(self):
        urls = [reverse('question-list'), self.question_url, reverse('answer-list'),
                self.answer_url, reverse('question-search') + '?search=API']
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def assert_cannot_change_existing(self):
        requests = [
            ('patch', self.question_url, {'title': 'Hacked'}),
            ('delete', self.question_url, None),
            ('post', self.close_url, None),
            ('patch', self.answer_url, {'text': 'Hacked'}),
            ('delete', self.answer_url, None),
        ]
        for method, url, data in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, data, format='json')
                self.assertEqual(response.status_code, 403)
        self.question.refresh_from_db()
        self.answer.refresh_from_db()
        self.assertEqual(self.question.title, 'API question')
        self.assertFalse(self.question.is_closed)
        self.assertEqual(self.answer.text, 'answer')

    def test_anonymous_cannot_write(self):
        self.assert_cannot_change_existing()
        response = self.client.post(reverse('question-list'), {'title': 'New', 'text': 'text'}, format='json')
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            reverse('answer-list'), {'question': self.question.id, 'text': 'text'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(Answer.objects.count(), 1)

    def test_other_user_cannot_change_content_of_others(self):
        self.client.force_authenticate(self.stranger)
        self.assert_cannot_change_existing()

    def test_author_is_taken_from_the_request(self):
        self.client.force_authenticate(self.stranger)
        response = self.client.post(reverse('question-list'), {
            'title': 'Mine', 'text': 'text', 'author': self.author.id, 'is_closed': True,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        question = Question.objects.get(title='Mine')
        self.assertEqual(question.author, self.stranger)
        self.assertFalse(question.is_closed)

        response = self.client.post(reverse('answer-list'), {
            'question': self.question.id, 'text': 'my answer', 'user': self.author.id,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Answer.objects.get(text='my answer').user, self.stranger)

    def test_author_can_edit_close_and_delete(self):
        self.client.force_authenticate(self.author)
        response = self.client.patch(self.question_url, {'title': 'Edited'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post(self.close_url).status_code, 200)
        self.question.refresh_from_db()
        self.assertEqual(self.question.title, 'Edited')
        self.assertEqual(self.question.author, self.author)
        self.assertTrue(self.question.is_closed)
        self.assertEqual(self.client.delete(self.answer_url).status_code, 204)
        self.assertEqual(self.client.delete(self.question_url).status_code, 204)

    def test_bad_start_date_is_a_client_error(self):
        response = self.client.get(reverse('question-list') + '?start_date=yesterday')
        self.assertEqual(response.status_code, 400)
