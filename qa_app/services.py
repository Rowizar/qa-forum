import json
import logging
from functools import lru_cache

import redis
from django.conf import settings
from django.contrib.auth.models import User

from .models import PageVisit

logger = logging.getLogger(__name__)

VISITS_QUEUE = 'page_visits'


@lru_cache(maxsize=1)
def _redis():
    return redis.Redis.from_url(f'{settings.REDIS_URL}/0')


def log_visit(request):
    """Record a page visit.

    With Redis configured the visit is pushed to a queue and saved later in
    one batch by a Celery task. Without Redis it goes straight to the database.
    """
    if request.path in ['/admin', '/auth', '/login']:
        return

    visit_data = {
        'user': request.user.pk,
        'url': request.build_absolute_uri(),
        'query_params': json.dumps(request.GET),
        'method': request.method,
        'user_agent': request.headers.get('User-Agent', ''),
    }

    if settings.REDIS_URL:
        _redis().lpush(VISITS_QUEUE, json.dumps(visit_data))
    else:
        _create_visit(visit_data)


def save_visits():
    """Move queued visits from Redis to the database."""
    if not settings.REDIS_URL:
        return

    client = _redis()
    while client.llen(VISITS_QUEUE) > 0:
        _create_visit(json.loads(client.rpop(VISITS_QUEUE)))


def _create_visit(visit_data):
    user_id = visit_data.get('user')

    user = None
    if user_id:
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            logger.warning('User with id %s not found.', user_id)
            return

    PageVisit.objects.create(
        user=user,
        url=visit_data['url'],
        query_params=visit_data['query_params'],
        method=visit_data['method'],
        user_agent=visit_data['user_agent'],
        os=visit_data.get('os', ''),
        browser=visit_data.get('browser', ''),
    )
