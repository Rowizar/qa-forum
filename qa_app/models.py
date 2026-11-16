from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models import OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords


def _rating_total(rating_model, target_field):
    """Sum of votes for each row of the outer query, 0 when there are none.

    A subquery rather than a join, so the sum stays correct however the outer
    query is filtered or joined.
    """
    totals = (
        rating_model.objects
        .filter(**{target_field: OuterRef('pk')})
        .values(target_field)
        .annotate(total=Sum('rating'))
        .values('total')
    )
    return Coalesce(Subquery(totals), 0, output_field=models.IntegerField())


class QuestionQuerySet(models.QuerySet):
    def with_rating(self):
        """Load ratings together with the questions, in the same query."""
        return self.annotate(rating_total=_rating_total(QuestionRating, 'question'))


class AnswerQuerySet(models.QuerySet):
    def with_rating(self):
        """Load ratings together with the answers, in the same query."""
        return self.annotate(rating_total=_rating_total(AnswerRating, 'answer'))


class RatedMixin:
    """`get_rating()` for models whose queryset has `with_rating()`."""

    def get_rating(self):
        # Use the value loaded by with_rating() when there is one; otherwise
        # ask the database (fine for one object, slow for a list).
        if hasattr(self, 'rating_total'):
            return self.rating_total
        return self.ratings.aggregate(total=Sum('rating'))['total'] or 0


class Category(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField()

    def __str__(self):
        return self.name


class Question(RatedMixin, models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, default=None)
    title = models.CharField(max_length=200, default=None)
    text = models.TextField()
    image = models.ImageField(upload_to='images/', null=True, blank=True)
    pub_date = models.DateTimeField(auto_now_add=True)
    categories = models.ManyToManyField(Category, blank=True)
    history = HistoricalRecords()
    is_closed = models.BooleanField(default=False)

    objects = QuestionQuerySet.as_manager()

    def __str__(self):
        return self.title

    @property
    def ratings(self):
        return self.questionrating_set


class Answer(RatedMixin, models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    text = models.TextField()
    pub_date = models.DateTimeField(auto_now_add=True)

    objects = AnswerQuerySet.as_manager()

    def __str__(self):
        return self.text

    @property
    def ratings(self):
        return self.answerrating_set


class QuestionRating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    rating = models.IntegerField()  # +1 or -1

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'question'], name='one_vote_per_user_per_question'),
            models.CheckConstraint(
                condition=Q(rating__in=[-1, 1]), name='question_vote_is_plus_or_minus_one'),
        ]

    def __str__(self):
        return str(self.rating)


class AnswerRating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    answer = models.ForeignKey(Answer, on_delete=models.CASCADE)
    rating = models.IntegerField()  # +1 or -1

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'answer'], name='one_vote_per_user_per_answer'),
            models.CheckConstraint(
                condition=Q(rating__in=[-1, 1]), name='answer_vote_is_plus_or_minus_one'),
        ]

    def __str__(self):
        return str(self.rating)


class UserCategoryPreference(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    preference_level = models.IntegerField()

    def __str__(self):
        return str(self.user) + str(self.category)


class Bookmark(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (
            'user',
            'question')  # чтобы предотвратить повторные закладки одного и того же вопроса одним пользователем

    def __str__(self):
        return f'{self.user.username} bookmarked {self.question.title}'


class PageVisit(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_('user'))
    date = models.DateTimeField(auto_now_add=True, verbose_name=_('visit date'))
    url = models.CharField(max_length=2048, verbose_name='URL')
    query_params = models.TextField(verbose_name=_('GET parameters'))
    method = models.CharField(max_length=10, verbose_name=_('HTTP method'))
    user_agent = models.CharField(max_length=256, verbose_name='User Agent')
    # null=True is historical: old rows hold NULL, new ones an empty string.
    os = models.CharField(  # noqa: DJ001
        max_length=100, verbose_name=_('operating system'), blank=True, null=True)
    browser = models.CharField(  # noqa: DJ001
        max_length=100, verbose_name=_('browser'), blank=True, null=True)

    class Meta:
        verbose_name = _('page visit')
        verbose_name_plural = _('page visits')

    def __str__(self):
        return f'{self.method} {self.url}'
