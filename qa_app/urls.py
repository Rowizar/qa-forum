from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter

from . import views
from .views import AnswerViewSet, QuestionSearchViewSet, QuestionViewSet

router = DefaultRouter()
router.register(r'questions', QuestionViewSet)
router.register(r'answers', AnswerViewSet)

urlpatterns = [
    path('', views.feed, name='feed'),
    # Old address of the feed, kept so that existing links keep working.
    path('feed/', RedirectView.as_view(pattern_name='feed', query_string=True)),
    # 'Recent' showed exactly the same list as the feed.
    path('recent/', RedirectView.as_view(pattern_name='feed', query_string=True)),
    path('ask/', views.ask_question, name='ask_question'),
    path('category/<int:category_id>/', views.question_list, name='question_list'),
    path('popular/', views.popular, name='popular'),
    path('search/', views.search, name='search'),
    path('register/', views.register, name='register'),
    path('question/<int:id>/', views.question_detail, name='question_detail'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('login/', views.login_view, name='login'),
    path('bookmark/<int:question_id>/', views.bookmark, name='add_bookmark'),
    path('delete_bookmark/<int:bookmark_id>/', views.delete_bookmark, name='delete_bookmark'),
    path('bookmarks/', views.bookmarks, name='bookmarks'),
    path('question/<int:question_id>/close/', views.close_question, name='close_question'),
    path('question/<int:question_id>/upvote/', views.upvote_question, name='upvote_question'),
    path('question/<int:question_id>/downvote/', views.downvote_question, name='downvote_question'),
    path('answer/<int:answer_id>/upvote/', views.upvote_answer, name='upvote_answer'),
    path('answer/<int:answer_id>/downvote/', views.downvote_answer, name='downvote_answer'),
    # Must stay above the router: otherwise 'questions/<pk>/' takes "search" for an id.
    path('questions/search/', QuestionSearchViewSet.as_view({'get': 'list'}), name='question-search'),
    path('', include(router.urls)),

]
