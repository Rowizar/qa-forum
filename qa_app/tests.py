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
