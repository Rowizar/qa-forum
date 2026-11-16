
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from qa_app.models import Answer, Category, Question


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
                self.assertContains(self.client.get(url), f'href="{self.url}"')

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
                self.assertContains(self.client.get(page), f'href="{url}"')


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
