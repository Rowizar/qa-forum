from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Answer, Bookmark, Category, Question, QuestionRating


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
        self.assertRedirects(response, reverse('base'), fetch_redirect_response=False)

    def test_wrong_password(self):
        response = self.client.post(reverse('login'), {'username': 'reader', 'password': 'nope'})
        self.assertContains(response, 'Invalid username or password')


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
