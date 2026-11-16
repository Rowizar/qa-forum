from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from qa_app.models import Question
from qa_app.tasks import send_daily_email


class EmailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('asker', 'asker@example.com', 'pass12345')
        User.objects.create_user('second', 'second@example.com', 'pass12345')
        User.objects.create_user('no_email', password='pass12345')
        User.objects.create_user('inactive', 'inactive@example.com', 'pass12345', is_active=False)

    def test_author_gets_an_email_about_a_new_question(self):
        self.client.force_login(self.user)
        self.client.post(reverse('ask_question'), {'title': 'How?', 'text': 'Like this'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['asker@example.com'])
        self.assertIn('How?', mail.outbox[0].body)

    def test_author_gets_an_email_about_a_question_created_through_the_api(self):
        client = APIClient()
        client.force_authenticate(self.user)
        client.post(reverse('question-list'), {'title': 'From API', 'text': 'text'}, format='json')
        self.assertEqual([m.to for m in mail.outbox], [['asker@example.com']])

    def test_no_email_without_an_address(self):
        self.client.force_login(User.objects.get(username='no_email'))
        self.client.post(reverse('ask_question'), {'title': 'How?', 'text': 'Like this'})
        self.assertEqual(mail.outbox, [])

    def test_question_is_created_even_if_the_email_cannot_be_queued(self):
        self.client.force_login(self.user)
        with mock.patch('qa_app.tasks.send_question_created_email.delay', side_effect=OSError('broker down')), \
                self.assertLogs('qa_app', 'ERROR'):
            response = self.client.post(reverse('ask_question'), {'title': 'How?', 'text': 'Like this'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Question.objects.filter(title='How?').exists())

    def test_daily_email_goes_to_each_active_user_separately(self):
        Question.objects.create(author=self.user, title='Fresh question', text='text')
        old = Question.objects.create(author=self.user, title='Old question', text='text')
        Question.objects.filter(pk=old.pk).update(pub_date=timezone.now() - timedelta(days=3))

        send_daily_email()

        self.assertEqual(sorted(m.to for m in mail.outbox), [['asker@example.com'], ['second@example.com']])
        self.assertIn('Fresh question', mail.outbox[0].body)
        self.assertNotIn('Old question', mail.outbox[0].body)

    def test_daily_email_is_not_sent_without_new_questions(self):
        send_daily_email()
        self.assertEqual(mail.outbox, [])

    def test_schedule_refers_to_existing_tasks(self):
        from config.celery import app
        for entry in app.conf.beat_schedule.values():
            with self.subTest(task=entry['task']):
                self.assertIn(entry['task'], app.tasks)
