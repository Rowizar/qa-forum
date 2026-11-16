"""Fill an empty site with demo users, questions, answers and votes.

    python manage.py seed_demo

Safe to run twice: it does nothing if the demo data is already there.
All demo users have the password "demo12345".
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from qa_app.models import Answer, AnswerRating, Category, Question, QuestionRating

DEMO_PASSWORD = 'demo12345'
USERS = ['alice', 'boris', 'chen', 'dasha']

CATEGORIES = {
    'Python': 'The language itself',
    'Django': 'The web framework',
    'Databases': 'SQL, migrations, queries',
    'Frontend': 'HTML, CSS, JavaScript',
    'Tools': 'Git, Docker, editors',
}

# (title, text, categories, answers, closed)
QUESTIONS = [
    ('What is the difference between a list and a tuple?',
     'Both hold several values in order. When should I pick one over the other?',
     ['Python'],
     ['A tuple cannot be changed after it is created, a list can. Use a tuple for a fixed '
      'group of values, such as coordinates, and a list for a collection that grows.',
      'Tuples can also be dictionary keys, lists cannot.'], True),
    ('Как отменить последний коммит в git?',
     'Закоммитил лишний файл. Как убрать коммит, но оставить изменения в рабочей папке?',
     ['Tools'],
     ['git reset --soft HEAD~1 — коммит исчезнет, изменения останутся подготовленными.',
      'Если коммит уже отправлен на сервер, лучше git revert: он создаёт новый коммит-отмену.'], False),
    ('Why does my Django template show nothing for a variable?',
     'I pass a value from the view, but the page shows an empty place and no error.',
     ['Django'],
     ['Django templates stay silent about unknown names. Check the spelling of the key in the '
      'context dictionary: it must match the name used in the template exactly.'], False),
    ('Чем отличается ForeignKey от ManyToManyField?',
     'Не понимаю, когда какую связь выбирать. Например, вопрос и его категории.',
     ['Django', 'Databases'],
     ['ForeignKey — «один ко многим»: у ответа один вопрос, у вопроса много ответов. '
      'ManyToManyField — «многие ко многим»: у вопроса несколько категорий, в категории много вопросов.'],
     False),
    ('How do I centre a block with CSS?',
     'I need a box in the middle of the page, both horizontally and vertically.',
     ['Frontend'],
     ['On the parent: display: grid; place-items: center; and give it a height, for example '
      'min-height: 100vh.', 'Flexbox works too: justify-content and align-items set to center.'], False),
    ('What does "N+1 queries" mean?',
     'A reviewer said my page has an N+1 problem. The page works, so what is wrong?',
     ['Django', 'Databases'],
     ['One query loads the list, then one more query runs for every row: 1 + N in total. '
      'It works, but gets slower with every row. select_related and prefetch_related load '
      'the related rows together with the list.'], False),
    ('Зачем нужно виртуальное окружение?',
     'Почему нельзя просто поставить все библиотеки в систему через pip?',
     ['Python', 'Tools'],
     ['У разных проектов разные версии одних и тех же библиотек. Окружение держит их отдельно, '
      'и проекты не ломают друг друга.'], False),
    ('Should I store uploaded pictures in the database?',
     'Users attach images to their questions. Where is the right place to keep them?',
     ['Databases'],
     ['Keep the files on disk or in object storage and store only the path in the database. '
      'That is what ImageField does.'], False),
    ('How do I run only one test in Django?',
     'The whole suite takes a while. I want to run a single test method.',
     ['Django', 'Tools'],
     ['python manage.py test app.tests.ClassName.test_method'], False),
    ('What is the difference between == and is?',
     'Both seem to compare things, but sometimes give different answers.',
     ['Python'],
     ['== compares values, "is" checks that both names point to the very same object. '
      'Use "is" only with None, True and False.'], False),
    ('Как сделать тёмную тему на сайте?',
     'Хочу, чтобы сайт сам подстраивался под тему системы.',
     ['Frontend'],
     ['Задайте цвета через CSS-переменные и переопределите их внутри '
      '@media (prefers-color-scheme: dark).'], False),
    ('What is a migration?',
     'Django asks me to run makemigrations and migrate. What do they actually do?',
     ['Django', 'Databases'],
     ['A migration is a file describing a change to the database structure. makemigrations '
      'writes the file from your models, migrate applies it to the database.'], False),
    ('Docker says the port is already in use',
     'docker compose up fails with "port is already allocated". Nothing else seems to be running.',
     ['Tools'],
     [], False),
    ('Is it fine to commit the .env file?',
     'It makes setting up the project on another computer much easier.',
     ['Tools'],
     ['No: it holds secrets. Commit a .env.example with empty values instead.'], False),
]


class Command(BaseCommand):
    help = 'Create demo users, categories, questions, answers and votes.'

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(username=USERS[0]).exists():
            self.stdout.write('Demo data is already there, nothing to do.')
            return

        users = [
            User.objects.create_user(name, f'{name}@example.com', DEMO_PASSWORD)
            for name in USERS
        ]
        categories = {
            name: Category.objects.get_or_create(name=name, defaults={'description': description})[0]
            for name, description in CATEGORIES.items()
        }

        now = timezone.now()
        for number, (title, text, category_names, answers, closed) in enumerate(QUESTIONS):
            author = users[number % len(users)]
            question = Question.objects.create(author=author, title=title, text=text, is_closed=closed)
            question.categories.set(categories[name] for name in category_names)
            # pub_date is filled in automatically on creation, so spread the
            # questions over the last days afterwards.
            asked_at = now - timedelta(hours=7 * number + 1)
            Question.objects.filter(pk=question.pk).update(pub_date=asked_at)

            # Different questions get a different mix of votes.
            for voter_number, voter in enumerate(users):
                if voter == author or (number + voter_number) % 4 == 0:
                    continue
                value = -1 if (number * 3 + voter_number) % 5 == 0 else 1
                QuestionRating.objects.create(user=voter, question=question, rating=value)

            for answer_number, answer_text in enumerate(answers):
                answerer = users[(number + answer_number + 1) % len(users)]
                answer = Answer.objects.create(user=answerer, question=question, text=answer_text)
                Answer.objects.filter(pk=answer.pk).update(
                    pub_date=asked_at + timedelta(minutes=20 * (answer_number + 1)))
                for voter in users:
                    if voter != answerer and (voter.pk + answer.pk) % 3:
                        AnswerRating.objects.create(user=voter, answer=answer, rating=1)

        self.stdout.write(self.style.SUCCESS(
            f'Created {len(users)} users, {len(categories)} categories and {len(QUESTIONS)} questions. '
            f'Log in as "{USERS[0]}" with the password "{DEMO_PASSWORD}".'
        ))
