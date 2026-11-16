
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


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
