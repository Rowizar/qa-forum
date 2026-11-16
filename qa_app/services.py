import json
import logging
import re
from functools import lru_cache

import redis
from django.conf import settings
from django.contrib.auth.models import User

from .models import PageVisit

logger = logging.getLogger(__name__)

VISITS_QUEUE = 'page_visits'

# Requests to these sections are not recorded.
EXCLUDED_PATH_PREFIXES = ('/admin/', '/static/', '/media/')

# Order matters: the first match wins. Edge and Opera also say "Chrome",
# and Chrome also says "Safari", so the more specific names go first.
BROWSERS = (
    ('Edge', r'Edg(e|A|iOS)?/'),
    ('Opera', r'OPR/|Opera'),
    ('Yandex Browser', r'YaBrowser/'),
    ('Firefox', r'Firefox/|FxiOS/'),
    ('Chrome', r'Chrome/|CriOS/'),
    ('Safari', r'Safari/'),
    ('Internet Explorer', r'MSIE |Trident/'),
)
# Android also says "Linux", and iOS also says "Mac OS X".
OPERATING_SYSTEMS = (
    ('Windows', r'Windows'),
    ('Android', r'Android'),
    ('iOS', r'iPhone|iPad|iPod'),
    ('macOS', r'Mac OS X|Macintosh'),
    ('Linux', r'Linux|X11'),
)


@lru_cache(maxsize=1)
def _redis():
    # Short timeouts: an unreachable Redis must not make every page hang.
    return redis.Redis.from_url(
        f'{settings.REDIS_URL}/0', socket_connect_timeout=1, socket_timeout=1,
    )


def _first_match(patterns, user_agent):
    for name, pattern in patterns:
        if re.search(pattern, user_agent):
            return name
    return ''


def parse_user_agent(user_agent):
    """Return (os, browser) guessed from a User-Agent header; '' when unknown."""
    return _first_match(OPERATING_SYSTEMS, user_agent), _first_match(BROWSERS, user_agent)


def log_visit(request):
    """Record a page visit.

    With Redis configured the visit is pushed to a queue and saved later in
    one batch by a Celery task. Without Redis it goes straight to the database.

    Visit statistics are secondary: a failure here is logged and never breaks
    the request itself.
    """
    if request.path.startswith(EXCLUDED_PATH_PREFIXES):
        return

    user_agent = request.headers.get('User-Agent', '')
    os_name, browser = parse_user_agent(user_agent)
    visit_data = {
        'user': request.user.pk,
        'url': request.build_absolute_uri()[:PageVisit._meta.get_field('url').max_length],
        'query_params': json.dumps(request.GET),
        'method': request.method,
        'user_agent': user_agent[:PageVisit._meta.get_field('user_agent').max_length],
        'os': os_name,
        'browser': browser,
    }

    try:
        if settings.REDIS_URL:
            _redis().lpush(VISITS_QUEUE, json.dumps(visit_data))
        else:
            _create_visit(visit_data)
    except Exception:
        logger.exception('Could not record a visit to %s', request.path)


def save_visits():
    """Move queued visits from Redis to the database."""
    if not settings.REDIS_URL:
        return

    client = _redis()
    while (raw_visit := client.rpop(VISITS_QUEUE)) is not None:
        try:
            _create_visit(json.loads(raw_visit))
        except Exception:
            logger.exception('Could not save a queued visit: %r', raw_visit)


def notify_question_created(question):
    """E-mail the author that their question is posted (if they have an address).

    The e-mail is sent by a Celery task. If the task cannot be queued, for
    example the broker is down, the question stays created and the problem
    is only logged.
    """
    if not question.author.email:
        return

    # Imported here because tasks.py imports this module.
    from .tasks import send_question_created_email
    try:
        send_question_created_email.delay(question.author.email, question.title)
    except Exception:
        logger.exception('Could not queue the e-mail about question %s', question.pk)


def _create_visit(visit_data):
    user_id = visit_data.get('user')
    # The user may have been deleted while the visit was waiting in the queue.
    if user_id and not User.objects.filter(pk=user_id).exists():
        user_id = None

    PageVisit.objects.create(
        user_id=user_id,
        url=visit_data['url'],
        query_params=visit_data['query_params'],
        method=visit_data['method'],
        user_agent=visit_data['user_agent'],
        os=visit_data.get('os', ''),
        browser=visit_data.get('browser', ''),
    )
