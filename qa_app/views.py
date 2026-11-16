from datetime import datetime
from functools import wraps

from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timezone import make_aware
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


class QuestionSearchViewSet(viewsets.ViewSet):
    def list(self, request):
        queryset = Question.objects.all()
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
    queryset = Question.objects.all()
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
        queryset = Question.objects.order_by('-pub_date')
        start_date = self.request.query_params.get('start_date', None)
        if start_date:
            try:
                start_date = make_aware(datetime.strptime(start_date, '%Y-%m-%d'))
            except ValueError:
                raise ValidationError({'start_date': 'Expected a date in the YYYY-MM-DD format.'})
            queryset = queryset.filter(pub_date__gte=start_date)
        return queryset


class AnswerViewSet(viewsets.ModelViewSet):
    """Answers: anyone can read, only the author can change or delete."""
    queryset = Answer.objects.order_by('pub_date')
    serializer_class = AnswerSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    owner_field = 'user'

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


def base(request):
    categories = Category.objects.all()
    if request.method == 'POST' and request.user.is_authenticated:
        form = QuestionForm(request.POST, request.FILES)
        if form.is_valid():
            question = form.save(commit=False)
            question.author = request.user
            question.save()
            notify_question_created(question)
            return redirect('question_detail', question.id)
    else:
        form = QuestionForm()
    return render(request, 'base.html', {'categories': categories, 'form': form})


def question_list(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    questions = Question.objects.filter(categories=category).order_by('-pub_date')
    return render(request, 'feed.html', {'questions': questions})


def feed(request):
    questions = Question.objects.all().order_by('-pub_date')
    return render(request, 'feed.html', {'questions': questions})


def popular(request):
    questions = Question.objects.annotate(num_ratings=Count('questionrating')).order_by('-num_ratings')
    return render(request, 'popular.html', {'questions': questions})


def recent(request):
    questions = Question.objects.all().order_by('-pub_date')
    return render(request, 'recent.html', {'questions': questions})


def search(request):
    query = request.GET.get('query', '')
    results = Question.objects.filter(title__icontains=query)
    return render(request, 'search_results.html', {'results': results})


def register(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()  # the form saves the e-mail too
            login(request, user)
            return redirect('base')
    else:
        form = SignUpForm()
    return render(request, 'register.html', {'form': form})


def question_detail(request, id):
    question = get_object_or_404(Question, id=id)
    answers = Answer.objects.filter(question=question)

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
            return redirect('question_detail', question.id)  # Обновить страницу с новым ответом
    else:
        form = AnswerForm()

    return render(request, 'question_detail.html',
                  {'question': question, 'answers': answers, 'form': form, 'bookmark': bookmark})


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


def login_view(request):
    next_url = request.POST.get('next') or request.GET.get('next', '')
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('base')
        return render(request, 'login.html', {'error': 'Invalid username or password', 'next': next_url})
    return render(request, 'login.html', {'next': next_url})


@user_action
def bookmark(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    Bookmark.objects.get_or_create(user=request.user, question=question)
    return redirect(_back_url(request))


@user_action
def delete_bookmark(request, bookmark_id):
    bookmark = get_object_or_404(Bookmark, id=bookmark_id, user=request.user)
    bookmark.delete()
    return redirect(_back_url(request, fallback='bookmarks'))


@login_required
def bookmarks(request):
    bookmarks = Bookmark.objects.filter(user=request.user)
    return render(request, 'bookmarks.html', {'bookmarks': bookmarks})


def _vote(request, rating_model, value, **target):
    """Set the current user's vote for a question or an answer to +1 or -1."""
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
