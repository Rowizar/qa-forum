import re
from functools import lru_cache

from django.apps import AppConfig
from django.db.backends.signals import connection_created


@lru_cache(maxsize=256)
def _like_pattern(pattern, escape):
    """Turn an SQL LIKE pattern into a regular expression that ignores case."""
    parts = []
    characters = iter(pattern)
    for character in characters:
        if escape and character == escape:
            parts.append(re.escape(next(characters, '')))
        elif character == '%':
            parts.append('.*')
        elif character == '_':
            parts.append('.')
        else:
            parts.append(re.escape(character))
    return re.compile(''.join(parts), re.IGNORECASE | re.DOTALL)


def _unicode_like(pattern, value, escape=None):
    if pattern is None or value is None:
        return None
    return _like_pattern(str(pattern), escape).fullmatch(str(value)) is not None


def _teach_sqlite_unicode_like(sender, connection, **kwargs):
    """Make search ignore the case of non-English letters on SQLite.

    SQLite's own LIKE folds case only for a-z, so a search for "Вопрос" would
    not find "вопрос". Other databases do not need this.
    """
    if connection.vendor == 'sqlite':
        connection.connection.create_function('like', 2, _unicode_like, deterministic=True)
        connection.connection.create_function('like', 3, _unicode_like, deterministic=True)


class QaAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'qa_app'

    def ready(self):
        connection_created.connect(_teach_sqlite_unicode_like)
