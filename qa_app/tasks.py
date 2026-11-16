from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail, send_mass_mail
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from .models import Question
from .services import save_visits


@shared_task
def send_daily_email():
    yesterday = timezone.now() - timedelta(days=1)
    recent_questions = Question.objects.filter(pub_date__gte=yesterday)

    if not recent_questions.exists():
        return "No questions were added in the last 24 hours."

    questions_info = "\n\n".join(
        f"Title: {question.title}\nText: {question.text}\n" for question in recent_questions
    )

    recipients = User.objects.filter(is_active=True).exclude(email='').values_list('email', flat=True)

    if not recipients:
        return "No users to send updates."

    subject = 'Your daily update from the QA'
    body = 'Here are the latest questions added to the QA in the last 24 hours:\n\n' + questions_info
    # One message per recipient, so users do not see each other's addresses.
    # Sender None means DEFAULT_FROM_EMAIL.
    send_mass_mail(
        [(subject, body, None, [email]) for email in recipients],
        fail_silently=False,
    )
    return "Emails sent successfully with the latest questions."


@shared_task
def send_question_created_email(user_email, question_title, language=None):
    # `language` is the interface language the author used when asking.
    with translation.override(language or settings.LANGUAGE_CODE):
        subject = _('Your question has been posted')
        body = _('Thank you for your question: "%(title)s"') % {'title': question_title}
    send_mail(
        subject,
        body,
        None,  # sender: DEFAULT_FROM_EMAIL
        [user_email],
        fail_silently=False,
    )


@shared_task
def task_save_visits():
    save_visits()
