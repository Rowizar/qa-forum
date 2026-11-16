from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Category, Question


class QuestionTests(TestCase):
    fixtures = ['initial_data.json']

    def test_question_list(self):
        response = self.client.get(reverse('feed'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sample Question")

    def test_question_detail(self):
        question = Question.objects.get(pk=42)
        response = self.client.get(reverse('question_detail', args=[question.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This is a sample question text.")


class CategoryPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        author = User.objects.create_user('author', password='pass12345')
        cls.category = Category.objects.create(name='Python', description='')
        other = Category.objects.create(name='Other', description='')
        inside = Question.objects.create(author=author, title='In category', text='text')
        inside.categories.add(cls.category)
        outside = Question.objects.create(author=author, title='Elsewhere', text='text')
        outside.categories.add(other)

    def test_shows_only_questions_of_the_category(self):
        response = self.client.get(reverse('question_list', args=[self.category.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'In category')
        self.assertNotContains(response, 'Elsewhere')

    def test_unknown_category_is_404(self):
        response = self.client.get(reverse('question_list', args=[9999]))
        self.assertEqual(response.status_code, 404)


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
