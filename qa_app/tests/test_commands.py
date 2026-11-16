import csv
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from qa_app.models import Answer, Category, Question, QuestionRating


class ExportRecentQuestionsTests(TestCase):
    def test_exports_only_questions_of_the_last_month(self):
        author = User.objects.create_user('author', password='pass12345')
        Question.objects.create(author=author, title='Fresh', text='text')
        old = Question.objects.create(author=author, title='Old', text='text')
        Question.objects.filter(pk=old.pk).update(pub_date=timezone.now() - timedelta(days=45))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'questions.csv'
            output = StringIO()
            call_command('export_recent_questions', str(path), stdout=output)
            with path.open(encoding='utf-8', newline='') as file:
                rows = list(csv.reader(file))

        self.assertEqual(rows[0], ['ID', 'Title', 'Author', 'Publication Date'])
        self.assertEqual([row[1:3] for row in rows[1:]], [['Fresh', 'author']])
        self.assertIn('exported 1 questions', output.getvalue())


class SeedDemoTests(TestCase):
    def test_creates_content_once(self):
        output = StringIO()
        call_command('seed_demo', stdout=output)
        self.assertIn('alice', output.getvalue())
        counts = (User.objects.count(), Category.objects.count(), Question.objects.count(),
                  Answer.objects.count(), QuestionRating.objects.count())
        self.assertGreaterEqual(Question.objects.count(), 11, 'enough questions to show pagination')
        self.assertTrue(all(counts))

        # Running it again changes nothing.
        call_command('seed_demo', stdout=output)
        self.assertEqual(counts, (
            User.objects.count(), Category.objects.count(), Question.objects.count(),
            Answer.objects.count(), QuestionRating.objects.count()))

    def test_demo_site_works(self):
        call_command('seed_demo', stdout=StringIO())
        self.assertTrue(self.client.login(username='alice', password='demo12345'))
        question = Question.objects.filter(answer__isnull=False).first()
        pages = [reverse('feed'), reverse('feed') + '?page=2', reverse('popular'), reverse('bookmarks'),
                 reverse('search') + '?query=git', reverse('question_detail', args=[question.id]),
                 reverse('question_list', args=[Category.objects.first().id])]
        for page in pages:
            with self.subTest(page=page):
                self.assertEqual(self.client.get(page).status_code, 200)
