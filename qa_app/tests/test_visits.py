import json
from unittest import mock

import redis
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from qa_app.models import PageVisit
from qa_app.services import parse_user_agent, save_visits

CHROME_ON_WINDOWS = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


class VisitLogTests(TestCase):
    def test_visit_is_recorded_with_os_and_browser(self):
        self.client.get(reverse('feed') + '?page=2', HTTP_USER_AGENT=CHROME_ON_WINDOWS)
        visit = PageVisit.objects.get()
        self.assertEqual(visit.url, 'http://testserver/qa_app/?page=2')
        self.assertEqual(visit.method, 'GET')
        self.assertIsNone(visit.user)
        self.assertEqual(visit.os, 'Windows')
        self.assertEqual(visit.browser, 'Chrome')

    def test_logged_in_user_is_recorded(self):
        user = User.objects.create_user('reader', password='pass12345')
        self.client.force_login(user)
        self.client.get(reverse('feed'))
        self.assertEqual(PageVisit.objects.get().user, user)

    def test_admin_static_and_media_are_not_recorded(self):
        for path in ['/admin/', '/admin/login/', '/static/css/style.css', '/media/images/x.png']:
            self.client.get(path)
        self.assertEqual(PageVisit.objects.count(), 0)

    def test_long_values_are_cut_to_fit_the_database(self):
        self.client.get(reverse('feed'), {'q': 'x' * 3000}, HTTP_USER_AGENT='y' * 1000)
        visit = PageVisit.objects.get()
        self.assertEqual(len(visit.url), 2048)
        self.assertEqual(len(visit.user_agent), 256)

    def test_user_agent_parsing(self):
        cases = {
            CHROME_ON_WINDOWS: ('Windows', 'Chrome'),
            CHROME_ON_WINDOWS + ' Edg/126.0.0.0': ('Windows', 'Edge'),
            'Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0': ('Linux', 'Firefox'),
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) '
            'Version/17.5 Safari/605.1.15': ('macOS', 'Safari'),
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 '
            '(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1': ('iOS', 'Safari'),
            'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/126.0.0.0 Mobile Safari/537.36': ('Android', 'Chrome'),
            'curl/8.5.0': ('', ''),
            '': ('', ''),
        }
        for user_agent, expected in cases.items():
            with self.subTest(user_agent=user_agent):
                self.assertEqual(parse_user_agent(user_agent), expected)

    @override_settings(REDIS_URL='redis://redis.invalid:6379')
    def test_redis_failure_does_not_break_the_page(self):
        with mock.patch('qa_app.services._redis') as get_client, self.assertLogs('qa_app', 'ERROR'):
            get_client.return_value.lpush.side_effect = redis.ConnectionError('down')
            response = self.client.get(reverse('feed'))
        self.assertEqual(response.status_code, 200)

    @override_settings(REDIS_URL='redis://redis.invalid:6379')
    def test_queued_visits_are_saved_to_the_database(self):
        deleted_user_id = 9999
        queue = []
        with mock.patch('qa_app.services._redis') as get_client:
            get_client.return_value.lpush.side_effect = lambda name, value: queue.insert(0, value)
            get_client.return_value.rpop.side_effect = lambda name: queue.pop() if queue else None
            self.client.get(reverse('feed'), HTTP_USER_AGENT=CHROME_ON_WINDOWS)
            self.client.get(reverse('popular'))
            self.assertEqual(PageVisit.objects.count(), 0)
            queue.insert(0, json.dumps({
                'user': deleted_user_id, 'url': 'http://testserver/x/', 'query_params': '{}',
                'method': 'GET', 'user_agent': '',
            }))
            save_visits()
        self.assertEqual(queue, [])
        visits = list(PageVisit.objects.order_by('id'))
        self.assertEqual([v.url for v in visits], [
            'http://testserver/qa_app/', 'http://testserver/qa_app/popular/', 'http://testserver/x/',
        ])
        self.assertEqual(visits[0].browser, 'Chrome')
        self.assertIsNone(visits[2].user)
