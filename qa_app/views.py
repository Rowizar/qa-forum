from datetime import datetime
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timezone import make_aware
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from .forms import AnswerForm, QuestionForm, SignUpForm
from .models import Answer, AnswerRating, Bookmark, Category, Question, QuestionRating
from .permissions import IsOwnerOrReadOnly
from .serializers import AnswerSerializer, QuestionSerializer
from .services import notify_question_created

QUESTIONS_PER_PAGE = 10


# --- REST API -----------------------------------------------------------------

class QuestionSearchViewSet(viewsets.ViewSet):
    def list(self, request):
        queryset = Question.objects.with_rating().prefetch_related('categories').order_by('-pub_date')
        search = request.query_params.get('search', None)
        category = request.query_params.get('category', None)

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(text__icontains=search)
            )

        if category:
            queryset = queryset.filter(categories__name__icontains=category)

        serializer = QuestionSerializer(queryset, many=True)
        return Response(serializer.data)


class QuestionViewSet(viewsets.ModelViewSet):
    """Questions: anyone can read, only the author can change, delete or close."""
    queryset = Question.objects.with_rating()
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    owner_field = 'author'

    def perform_create(self, serializer):
        question = serializer.save(author=self.request.user)
        notify_question_created(question)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        question = self.get_object()
        question.is_closed = True
        question.save()
        return Response({'status': 'question closed'})

    def get_queryset(self):
        queryset = Question.objects.with_rating().prefetch_related('categories').order_by('-pub_date')
        start_date = self.request.query_params.get('start_date', None)
        if start_date:
            try:
                start_date = make_aware(datetime.strptime(start_date, '%Y-%m-%d'))
            except ValueError:
                raise ValidationError({'start_date': 'Expected a date in the YYYY-MM-DD format.'}) from None
            queryset = queryset.filter(pub_date__gte=start_date)
        return queryset


class AnswerViewSet(viewsets.ModelViewSet):
    """Answers: anyone can read, only the author can change or delete."""
    queryset = Answer.objects.with_rating().order_by('pub_date')
    serializer_class = AnswerSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    owner_field = 'user'

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


# --- Lists of questions -------------------------------------------------------

def _question_list_page(request, questions, heading, empty_message=None):
    """Render one page of a list of questions. All question lists go through here."""
    questions = (
        questions.with_rating().with_user_vote(request.user)
        .select_related('author').prefetch_related('categories')
    )
    # Questions equal in the main sort order (same rating, same second) must
    # still come in a fixed order, or they would jump between pages.
    questions = questions.order_by(*questions.query.order_by, '-id')
    # get_page() never fails: a wrong or missing page number gives the nearest valid page.
    page = Paginator(questions, QUESTIONS_PER_PAGE).get_page(request.GET.get('page'))
    return render(request, 'question_list.html', {
        'heading': heading,
        'questions': page,
        'empty_message': empty_message or _('There are no questions here yet.'),
    })


def feed(request):
    return _question_list_page(
        request, Question.objects.order_by('-pub_date'), _('Feed'),
        empty_message=_('No questions yet. Be the first to ask!'),
    )


def popular(request):
    # with_rating() is applied here as well, because the list is sorted by it.
    questions = Question.objects.with_rating().order_by('-rating_total', '-pub_date')
    return _question_list_page(request, questions, _('Popular'))


def question_list(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    questions = Question.objects.filter(categories=category).order_by('-pub_date')
    return _question_list_page(
        request, questions, _('Category: %(name)s') % {'name': category.name},
        empty_message=_('There are no questions in this category yet.'),
    )


def search(request):
    query = request.GET.get('query', '').strip()
    if query:
        questions = Question.objects.filter(
            Q(title__icontains=query) | Q(text__icontains=query)
        ).order_by('-pub_date')
        empty_message = _('Nothing found for your query.')
    else:
        questions = Question.objects.none()
        empty_message = _('Type something into the search field.')
    return _question_list_page(request, questions, _('Search results'), empty_message)


@login_required
def bookmarks(request):
    bookmarks = Bookmark.objects.filter(user=request.user).select_related('question').order_by('-created_at')
    return render(request, 'bookmarks.html', {'bookmarks': bookmarks})


# --- Asking and answering -----------------------------------------------------

@login_required
def ask_question(request):
    if request.method == 'POST':
        form = QuestionForm(request.POST, request.FILES)
        if form.is_valid():
            question = form.save(commit=False)
            question.author = request.user
            question.save()
            form.save_m2m()  # categories can be saved only after the question itself
            notify_question_created(question)
            messages.success(request, _('Your question is posted.'))
            return redirect('question_detail', question.id)
    else:
        form = QuestionForm()
    return render(request, 'ask_question.html', {'form': form})


def _can_close(user, question):
    return user.is_authenticated and (user == question.author or user.is_staff)


def question_detail(request, question_id):
    question = get_object_or_404(
        Question.objects.with_rating().with_user_vote(request.user).select_related('author'),
        id=question_id,
    )
    answers = (
        Answer.objects.with_rating().with_user_vote(request.user)
        .filter(question=question).select_related('user').order_by('pub_date')
    )

    bookmark = None
    if request.user.is_authenticated:
        bookmark = Bookmark.objects.filter(user=request.user, question=question).first()

    if request.method == 'POST' and question.is_closed:
        return HttpResponseForbidden('This question is closed and does not accept new answers.')

    if request.method == 'POST' and request.user.is_authenticated:
        form = AnswerForm(request.POST, request.FILES)
        if form.is_valid():
            answer = form.save(commit=False)
            answer.user = request.user
            answer.question = question
            answer.save()
            messages.success(request, _('Your answer is posted.'))
            return redirect('question_detail', question.id)
    else:
        form = AnswerForm()

    return render(request, 'question_detail.html', {
        'question': question,
        'answers': answers,
        'form': form,
        'bookmark': bookmark,
        'can_close': _can_close(request.user, question) and not question.is_closed,
    })


def register(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()  # the form saves the e-mail too
            login(request, user)
            messages.success(request, _('Welcome, %(name)s!') % {'name': user.username})
            return redirect('feed')
    else:
        form = SignUpForm()
    return render(request, 'register.html', {'form': form})


# --- Actions: votes, bookmarks, closing ---------------------------------------

def _back_url(request, fallback='feed'):
    """Address of the page the request came from, if it is a page of this site."""
    referer = request.META.get('HTTP_REFERER', '')
    if url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return referer
    return reverse(fallback)


def user_action(view):
    """For views that change something on behalf of the user (vote, bookmark).

    They accept only POST, so they are covered by CSRF protection and cannot
    be triggered by a plain link. An anonymous user is sent to the login page
    and afterwards returns to the page they came from, not to the action URL.
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(_back_url(request))
        return view(request, *args, **kwargs)
    return require_POST(wrapper)


@user_action
def bookmark(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    Bookmark.objects.get_or_create(user=request.user, question=question)
    messages.success(request, _('Added to bookmarks.'))
    return redirect(_back_url(request))


@user_action
def delete_bookmark(request, bookmark_id):
    bookmark = get_object_or_404(Bookmark, id=bookmark_id, user=request.user)
    bookmark.delete()
    messages.success(request, _('Removed from bookmarks.'))
    return redirect(_back_url(request, fallback='bookmarks'))


@user_action
def close_question(request, question_id):
    """Stop accepting answers. Only the author (or staff) may do it; there is no reopening."""
    question = get_object_or_404(Question, id=question_id)
    if not _can_close(request.user, question):
        return HttpResponseForbidden('Only the author can close this question.')
    if not question.is_closed:
        question.is_closed = True
        question.save()
        messages.success(request, _('The question is closed.'))
    return redirect('question_detail', question.id)


def _vote(request, rating_model, value, **target):
    """Set the current user's vote for a question or an answer to +1 or -1.

    Pressing the arrow that is already chosen takes the vote back.
    """
    same_vote = rating_model.objects.filter(user=request.user, **target, rating=value)
    if not same_vote.delete()[0]:
        rating_model.objects.update_or_create(
            user=request.user, **target, defaults={'rating': value},
        )
    return redirect(_back_url(request))


@user_action
def upvote_question(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    return _vote(request, QuestionRating, 1, question=question)


@user_action
def downvote_question(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    return _vote(request, QuestionRating, -1, question=question)


@user_action
def upvote_answer(request, answer_id):
    answer = get_object_or_404(Answer, id=answer_id)
    return _vote(request, AnswerRating, 1, answer=answer)


@user_action
def downvote_answer(request, answer_id):
    answer = get_object_or_404(Answer, id=answer_id)
    return _vote(request, AnswerRating, -1, answer=answer)
