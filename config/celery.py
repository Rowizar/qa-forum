"""Celery application for the QA forum project."""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
# Broker and result backend come from the CELERY_* values in Django settings.
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'send-daily-email-every-morning': {
        'task': 'qa_app.tasks.send_daily_email',
        'schedule': crontab(hour=8, minute=0),
    },
    "test-every-minute": {
        "task": "qa_app.tasks.test_task",
        "schedule": crontab(minute="*/1"),
    },
    'send-minute-email-every-minute': {
        'task': 'qa_app.tasks.send_minute_email',
        'schedule': crontab(minute='*/1'),
    },
    'save_visits_every-minute': {
        'task': 'qa_app.tasks.task_save_visits',
        'schedule': crontab(minute='*/1'),
    },
}
