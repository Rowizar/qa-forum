from io import BytesIO

import openpyxl
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from qa_app.models import Answer, Question, QuestionRating


class QuestionAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('boss', 'boss@example.com', 'pass12345')
        cls.question = Question.objects.create(author=cls.admin, title='Admin question', text='text')

    def setUp(self):
        self.client.force_login(self.admin)

    def test_pages_open(self):
        urls = [
            reverse('admin:qa_app_question_changelist'),
            reverse('admin:qa_app_question_add'),
            reverse('admin:qa_app_question_change', args=[self.question.id]),
            reverse('admin:qa_app_question_history', args=[self.question.id]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_close_action(self):
        response = self.client.post(reverse('admin:qa_app_question_changelist'), {
            'action': 'make_closed',
            '_selected_action': [self.question.id],
        })
        self.assertEqual(response.status_code, 302)
        self.question.refresh_from_db()
        self.assertTrue(self.question.is_closed)
        self.assertEqual(self.question.history.count(), 2)

    def test_created_question_belongs_to_the_admin(self):
        response = self.client.post(reverse('admin:qa_app_question_add'), {
            'title': 'From admin', 'text': 'text',
            'answer_set-TOTAL_FORMS': 0, 'answer_set-INITIAL_FORMS': 0,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Question.objects.get(title='From admin').author, self.admin)

    def test_export_to_excel(self):
        QuestionRating.objects.create(user=self.admin, question=self.question, rating=1)
        response = self.client.post(reverse('admin:qa_app_question_changelist'), {
            'action': 'export_to_excel',
            '_selected_action': [self.question.id],
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('questions.xlsx', response['Content-Disposition'])
        rows = list(openpyxl.load_workbook(BytesIO(response.content)).active.values)
        self.assertEqual(rows[0], ('ID', 'Title', 'Author', 'Publication Date', 'Rating'))
        self.assertEqual(rows[1][:3], (self.question.id, 'Admin question', 'boss'))
        self.assertEqual(rows[1][4], 1)

    def test_other_admin_pages_open(self):
        Answer.objects.create(user=self.admin, question=self.question, text='answer')
        self.client.get(reverse('feed'))  # leaves a page visit to list
        for model in ['answer', 'category', 'bookmark', 'questionrating', 'answerrating', 'pagevisit']:
            with self.subTest(model=model):
                response = self.client.get(reverse(f'admin:qa_app_{model}_changelist'))
                self.assertEqual(response.status_code, 200)

    def test_admin_is_closed_to_ordinary_users(self):
        self.client.force_login(User.objects.create_user('reader', password='pass12345'))
        response = self.client.get(reverse('admin:qa_app_question_changelist'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin:login'), response['Location'])
