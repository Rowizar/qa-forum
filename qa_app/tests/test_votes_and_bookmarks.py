
from django.contrib.auth.models import User
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from qa_app.models import Answer, AnswerRating, Bookmark, Category, Question, QuestionRating


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
        for user, value in zip(cls.users, (1, -1, -1), strict=True):
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
