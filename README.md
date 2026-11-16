# QA Forum

Форум вопросов и ответов на Django: вопросы с категориями и картинками, ответы,
голосование, закладки, поиск, REST API и фоновые задачи.

> Проект в процессе переработки. Подробное описание появится позже.

## Стек

Python 3.12, Django 5.2, Django REST Framework, Celery, Redis, SQLite.

## Запуск локально

Redis и Docker для этого не нужны.

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env          # Linux/macOS: cp .env.example .env
# впишите SECRET_KEY в .env (команда для генерации есть внутри файла)

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Сайт откроется на http://127.0.0.1:8000/.

Без `REDIS_URL` кеш хранится в памяти, задачи Celery выполняются сразу в том же
процессе, а письма печатаются в консоль.

Чтобы сайт не был пустым, можно заполнить его демо-данными (пользователи, вопросы,
ответы, голоса):

```bash
python manage.py seed_demo
```

Все демо-пользователи (`alice`, `boris`, `chen`, `dasha`) входят с паролем `demo12345`.

## Языки и тема

Интерфейс есть на русском и английском. По умолчанию сайт выбирает язык браузера;
переключатель RU/EN в шапке запоминает выбор. Тёмная или светлая тема берётся из
настроек системы и тоже переключается кнопкой в шапке.

Тексты в коде написаны на английском, русский перевод лежит в
`locale/ru/LC_MESSAGES/django.po`. После изменения текстов перевод нужно обновить
и скомпилировать. Для этого нужен gettext; он уже есть в Docker-образе:

```bash
docker compose run --rm --no-deps web python manage.py makemessages -l ru -i .venv
# дописать переводы в django.po, затем:
docker compose run --rm --no-deps web python manage.py compilemessages -l ru -i .venv
```

## Запуск в Docker

Поднимает сайт, Celery (worker и beat), Redis, MailHog и Flower.

```bash
copy .env.example .env          # и впишите SECRET_KEY
docker compose up --build
```

| Адрес | Что там |
| --- | --- |
| http://localhost:8000/ | сайт |
| http://localhost:8000/admin/ | админка |
| http://localhost:8000/swagger/ | документация API |
| http://localhost:8025/ | MailHog: перехваченные письма |
| http://localhost:5555/ | Flower: мониторинг Celery |

Суперпользователь в Docker: `docker compose exec web python manage.py createsuperuser`.

## Тесты

```bash
python manage.py test
```

## Настройки

Все настройки окружения читаются из переменных окружения или файла `.env`.
Полный список с пояснениями — в [.env.example](.env.example).
