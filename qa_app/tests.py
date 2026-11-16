import json
from datetime import timedelta
from unittest import mock

import redis
from django.contrib.auth.models import User
from django.core import mail
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Answer, AnswerRating, Bookmark, Category, PageVisit, Question, QuestionRating
from .services import parse_user_agent, save_visits
from .tasks import send_daily_email


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


class CreateQuestionTests(TestCase):
    """The 'ask a question' page."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('asker', 'asker@example.com', 'pass12345')
        cls.python = Category.objects.create(name='Python', description='')
        cls.django = Category.objects.create(name='Django', description='')
        cls.url = reverse('ask_question')

    def test_every_page_links_to_the_form(self):
        for url in [reverse('feed'), reverse('popular'), reverse('search')]:
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), 'href="%s"' % self.url)

    def test_form_offers_categories(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertContains(response, 'Python')
        self.assertContains(response, 'Django')

    def test_logged_in_user_creates_a_question_with_categories(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.url, {'title': 'How?', 'text': 'Like this', 'categories': [self.python.id]})
        question = Question.objects.get(title='How?')
        self.assertRedirects(response, reverse('question_detail', args=[question.id]))
        self.assertEqual(question.author, self.user)
        self.assertEqual(list(question.categories.all()), [self.python])

    def test_errors_are_shown_and_input_is_kept(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {'title': '', 'text': 'My long text'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Question.objects.count(), 0)
        self.assertContains(response, 'This field is required.')
        self.assertContains(response, 'My long text')

    def test_anonymous_is_sent_to_login_and_back(self):
        login_url = reverse('login') + '?next=' + self.url
        self.assertRedirects(self.client.get(self.url), login_url)
        self.assertRedirects(self.client.post(self.url, {'title': 'How?', 'text': 'Like this'}), login_url)
        self.assertEqual(Question.objects.count(), 0)

    def test_old_feed_address_redirects_to_the_home_page(self):
        response = self.client.get('/qa_app/feed/?page=2')
        self.assertRedirects(response, reverse('feed') + '?page=2')


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

    def test_category_is_named_and_linked_from_every_page(self):
        url = reverse('question_list', args=[self.category.id])
        self.assertContains(self.client.get(url), 'Category: Python')
        for page in [reverse('feed'), reverse('popular'), reverse('search')]:
            with self.subTest(page=page):
                self.assertContains(self.client.get(page), 'href="%s"' % url)


class CloseQuestionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user('author', password='pass12345')
        cls.stranger = User.objects.create_user('stranger', password='pass12345')
        cls.staff = User.objects.create_user('moderator', password='pass12345', is_staff=True)
        cls.question = Question.objects.create(author=cls.author, title='Mine', text='text')
        cls.page = reverse('question_detail', args=[cls.question.id])
        cls.url = reverse('close_question', args=[cls.question.id])

    def is_closed(self):
        self.question.refresh_from_db()
        return self.question.is_closed

    def test_author_sees_the_button_and_can_close(self):
        self.client.force_login(self.author)
        self.assertContains(self.client.get(self.page), 'Close question')
        self.assertRedirects(self.client.post(self.url), self.page)
        self.assertTrue(self.is_closed())
        self.assertNotContains(self.client.get(self.page), 'Close question')
        # The change is recorded in the question's history.
        self.assertEqual(self.question.history.count(), 2)

    def test_staff_can_close(self):
        self.client.force_login(self.staff)
        self.client.post(self.url)
        self.assertTrue(self.is_closed())

    def test_other_users_cannot_close(self):
        self.assertNotContains(self.client.get(self.page), 'Close question')
        self.assertEqual(self.client.post(self.url).status_code, 302)  # to the login page
        self.client.force_login(self.stranger)
        self.assertNotContains(self.client.get(self.page), 'Close question')
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertFalse(self.is_closed())

    def test_plain_link_does_not_close(self):
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertFalse(self.is_closed())


class QuestionListTests(TestCase):
    """Feed, popular and search share one template with pagination."""

    @classmethod
    def setUpTestData(cls):
        author = User.objects.create_user('author', password='pass12345')
        # 25 questions: three pages of 10, 10 and 5.
        for number in range(1, 26):
            Question.objects.create(author=author, title=f'Question {number:02}', text='about pagination')
        Question.objects.filter(title='Question 07').update(text='mentions a zebra')

    def titles(self, response):
        return [question.title for question in response.context['questions']]

    def test_feed_shows_newest_first_ten_per_page(self):
        response = self.client.get(reverse('feed'))
        self.assertEqual(self.titles(response), [f'Question {n:02}' for n in range(25, 15, -1)])
        self.assertContains(response, 'Page 1 of 3')
        self.assertContains(response, 'href="?page=2"')

    def test_last_page_and_out_of_range_pages(self):
        last = [f'Question {n:02}' for n in range(5, 0, -1)]
        self.assertEqual(self.titles(self.client.get(reverse('feed') + '?page=3')), last)
        # A page number that does not exist shows the nearest page instead of an error.
        self.assertEqual(self.titles(self.client.get(reverse('feed') + '?page=99')), last)
        self.assertEqual(len(self.titles(self.client.get(reverse('popular') + '?page=abc'))), 10)

    def test_search_looks_in_titles_and_texts(self):
        self.assertEqual(self.titles(self.client.get(reverse('search') + '?query=zebra')), ['Question 07'])
        self.assertEqual(self.titles(self.client.get(reverse('search') + '?query=question+13')), ['Question 13'])

    def test_search_pages_keep_the_query(self):
        response = self.client.get(reverse('search') + '?query=pagination')
        self.assertContains(response, 'Page 1 of 3')
        self.assertContains(response, 'href="?query=pagination&amp;page=2"')
        self.assertContains(response, 'value="pagination"')
        second = self.client.get(reverse('search') + '?query=pagination&page=2')
        self.assertEqual(len(self.titles(second)), 10)

    def test_search_without_results_or_query(self):
        self.assertContains(self.client.get(reverse('search') + '?query=unicorn'), 'Nothing found')
        response = self.client.get(reverse('search'))
        self.assertEqual(self.titles(response), [])
        self.assertContains(response, 'Type something')

    def test_recent_redirects_to_the_feed(self):
        self.assertRedirects(self.client.get('/qa_app/recent/'), reverse('feed'))


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


class UserActionTests(TestCase):
    """Voting and bookmarks: POST only, logged-in users only."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('reader', password='pass12345')
        cls.question = Question.objects.create(author=cls.user, title='Votable', text='text')
        cls.answer = Answer.objects.create(user=cls.user, question=cls.question, text='answer')

    def action_urls(self):
        bookmark = Bookmark.objects.create(user=self.user, question=self.question)
        return [
            reverse('upvote_question', args=[self.question.id]),
            reverse('downvote_question', args=[self.question.id]),
            reverse('upvote_answer', args=[self.answer.id]),
            reverse('downvote_answer', args=[self.answer.id]),
            reverse('add_bookmark', args=[self.question.id]),
            reverse('delete_bookmark', args=[bookmark.id]),
        ]

    def test_get_is_not_allowed(self):
        self.client.force_login(self.user)
        for url in self.action_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(QuestionRating.objects.count(), 0)
        self.assertEqual(Bookmark.objects.count(), 1)

    def test_anonymous_is_sent_to_login_and_back_to_the_page(self):
        page = reverse('question_detail', args=[self.question.id])
        for url in self.action_urls():
            with self.subTest(url=url):
                response = self.client.post(url, HTTP_REFERER='http://testserver' + page)
                self.assertRedirects(
                    response, reverse('login') + '?next=http%3A//testserver' + page,
                    fetch_redirect_response=False,
                )
        self.assertEqual(QuestionRating.objects.count(), 0)

    def test_csrf_token_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse('upvote_question', args=[self.question.id]))
        self.assertEqual(response.status_code, 403)

    def test_vote_can_be_changed_but_counts_once(self):
        self.client.force_login(self.user)
        self.client.post(reverse('upvote_question', args=[self.question.id]))
        self.client.post(reverse('upvote_question', args=[self.question.id]))
        self.assertEqual(self.question.get_rating(), 1)
        self.client.post(reverse('downvote_question', args=[self.question.id]))
        self.assertEqual(self.question.get_rating(), -1)

        self.client.post(reverse('upvote_answer', args=[self.answer.id]))
        self.assertEqual(self.answer.get_rating(), 1)

    def test_redirects_back_only_to_own_pages(self):
        self.client.force_login(self.user)
        url = reverse('upvote_question', args=[self.question.id])
        page = 'http://testserver' + reverse('popular')
        self.assertRedirects(self.client.post(url, HTTP_REFERER=page), page, fetch_redirect_response=False)
        response = self.client.post(url, HTTP_REFERER='https://evil.example/')
        self.assertRedirects(response, reverse('feed'), fetch_redirect_response=False)

    def test_bookmarking_twice_does_not_fail(self):
        self.client.force_login(self.user)
        url = reverse('add_bookmark', args=[self.question.id])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(Bookmark.objects.filter(user=self.user).count(), 1)

    def test_cannot_delete_someone_elses_bookmark(self):
        bookmark = Bookmark.objects.create(user=self.user, question=self.question)
        self.client.force_login(User.objects.create_user('stranger', password='pass12345'))
        response = self.client.post(reverse('delete_bookmark', args=[bookmark.id]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Bookmark.objects.filter(id=bookmark.id).exists())

    def test_bookmarks_page_requires_login(self):
        url = reverse('bookmarks')
        self.assertRedirects(self.client.get(url), reverse('login') + '?next=' + url)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 200)


class RatingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = [User.objects.create_user(f'voter{i}', password='pass12345') for i in range(3)]
        author = cls.users[0]
        # "Loved" has two votes up; "Disputed" has more votes, but they cancel out.
        cls.loved = Question.objects.create(author=author, title='Loved', text='text')
        cls.disputed = Question.objects.create(author=author, title='Disputed', text='text')
        cls.ignored = Question.objects.create(author=author, title='Ignored', text='text')
        for user in cls.users[:2]:
            QuestionRating.objects.create(user=user, question=cls.loved, rating=1)
        for user, value in zip(cls.users, (1, -1, -1)):
            QuestionRating.objects.create(user=user, question=cls.disputed, rating=value)
        cls.answer = Answer.objects.create(user=author, question=cls.loved, text='answer')
        AnswerRating.objects.create(user=author, answer=cls.answer, rating=-1)

    def test_rating_is_the_sum_of_votes(self):
        ratings = {q.title: q.get_rating() for q in Question.objects.with_rating()}
        self.assertEqual(ratings, {'Loved': 2, 'Disputed': -1, 'Ignored': 0})
        # Without with_rating() the value is the same, just loaded separately.
        self.assertEqual(Question.objects.get(pk=self.loved.pk).get_rating(), 2)
        self.assertEqual(Question.objects.get(pk=self.ignored.pk).get_rating(), 0)
        self.assertEqual(Answer.objects.with_rating().get().get_rating(), -1)
        self.assertEqual(Answer.objects.get().get_rating(), -1)

    def test_rating_is_not_distorted_by_other_joins(self):
        category = Category.objects.create(name='Python', description='')
        self.loved.categories.add(category, Category.objects.create(name='Django', description=''))
        questions = Question.objects.with_rating().filter(categories__name__contains='o')
        self.assertEqual({q.get_rating() for q in questions}, {2})

    def test_popular_is_sorted_by_rating_not_by_number_of_votes(self):
        response = self.client.get(reverse('popular'))
        titles = [q.title for q in response.context['questions']]
        self.assertEqual(titles, ['Loved', 'Ignored', 'Disputed'])

    def test_number_of_queries_does_not_grow_with_the_list(self):
        def count_queries(url):
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.client.get(url).status_code, 200)
            return len(queries)

        urls = [reverse('feed'), reverse('popular'), reverse('question-list'),
                reverse('question_detail', args=[self.loved.id])]
        before = [count_queries(url) for url in urls]
        for i in range(5):
            question = Question.objects.create(author=self.users[0], title=f'More {i}', text='text')
            QuestionRating.objects.create(user=self.users[1], question=question, rating=1)
            answer = Answer.objects.create(user=self.users[1], question=self.loved, text=f'more {i}')
            AnswerRating.objects.create(user=self.users[2], answer=answer, rating=1)
        self.assertEqual([count_queries(url) for url in urls], before)

    def test_database_rejects_a_second_vote_and_odd_values(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            QuestionRating.objects.create(user=self.users[0], question=self.loved, rating=-1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            QuestionRating.objects.create(user=self.users[2], question=self.loved, rating=100)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnswerRating.objects.create(user=self.users[0], answer=self.answer, rating=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnswerRating.objects.create(user=self.users[1], answer=self.answer, rating=0)


class RegistrationTests(TestCase):
    def test_new_user_is_saved_with_email_and_logged_in(self):
        response = self.client.post(reverse('register'), {
            'username': 'newcomer', 'email': 'newcomer@example.com',
            'password1': 'a-long-passphrase-42', 'password2': 'a-long-passphrase-42',
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='newcomer')
        self.assertEqual(user.email, 'newcomer@example.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.id)

    def test_mismatched_passwords_show_an_error(self):
        response = self.client.post(reverse('register'), {
            'username': 'newcomer', 'email': 'newcomer@example.com',
            'password1': 'a-long-passphrase-42', 'password2': 'something-else-43',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newcomer').exists())


class LoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user('reader', password='pass12345')

    def login(self, next_url):
        return self.client.post(reverse('login'), {
            'username': 'reader', 'password': 'pass12345', 'next': next_url,
        })

    def test_returns_to_the_requested_page(self):
        url = reverse('bookmarks')
        self.assertRedirects(self.login(url), url)

    def test_ignores_foreign_next_address(self):
        response = self.login('https://evil.example/')
        self.assertRedirects(response, reverse('feed'), fetch_redirect_response=False)

    def test_wrong_password(self):
        response = self.client.post(reverse('login'), {'username': 'reader', 'password': 'nope'})
        self.assertContains(response, 'Please enter a correct username and password')


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


class AnswerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('helper', password='pass12345')
        cls.open = Question.objects.create(author=cls.user, title='Open', text='text')
        cls.closed = Question.objects.create(author=cls.user, title='Closed', text='text', is_closed=True)

    def test_answer_to_an_open_question(self):
        self.client.force_login(self.user)
        url = reverse('question_detail', args=[self.open.id])
        self.assertContains(self.client.get(url), 'Your answer')
        self.assertRedirects(self.client.post(url, {'text': 'My answer'}), url)
        self.assertEqual(self.open.answer_set.get().user, self.user)

    def test_anonymous_cannot_answer(self):
        url = reverse('question_detail', args=[self.open.id])
        response = self.client.get(url)
        self.assertNotContains(response, 'Your answer')
        self.assertContains(response, reverse('login') + '?next=' + url)
        self.client.post(url, {'text': 'My answer'})
        self.assertEqual(Answer.objects.count(), 0)

    def test_closed_question_does_not_accept_answers(self):
        self.client.force_login(self.user)
        url = reverse('question_detail', args=[self.closed.id])
        response = self.client.get(url)
        self.assertContains(response, 'This question is closed')
        self.assertNotContains(response, 'Your answer')
        self.assertEqual(self.client.post(url, {'text': 'My answer'}).status_code, 403)
        self.assertEqual(Answer.objects.count(), 0)

    def test_closed_question_does_not_accept_answers_through_the_api(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse('answer-list')
        response = client.post(url, {'question': self.closed.id, 'text': 'My answer'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Answer.objects.count(), 0)

        # An answer given before the question was closed can still be corrected,
        # but not moved to a closed question.
        old_answer = Answer.objects.create(user=self.user, question=self.closed, text='Old')
        answer_url = reverse('answer-detail', args=[old_answer.id])
        self.assertEqual(client.patch(answer_url, {'text': 'Fixed'}, format='json').status_code, 200)
        other = Answer.objects.create(user=self.user, question=self.open, text='Other')
        response = client.patch(
            reverse('answer-detail', args=[other.id]), {'question': self.closed.id}, format='json')
        self.assertEqual(response.status_code, 400)


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
