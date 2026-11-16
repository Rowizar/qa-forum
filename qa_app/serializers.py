from rest_framework import serializers
from .models import Question, Answer


class QuestionSerializer(serializers.ModelSerializer):
    rating = serializers.SerializerMethodField()

    def get_rating(self, obj):
        return obj.get_rating()

    class Meta:
        model = Question
        fields = ['id', 'author', 'title', 'text', 'image', 'pub_date', 'categories', 'is_closed', 'rating']
        # The author is always the user who makes the request; a question is
        # closed through the separate `close` action.
        read_only_fields = ['author', 'is_closed']


class AnswerSerializer(serializers.ModelSerializer):
    rating = serializers.SerializerMethodField()

    def get_rating(self, obj):
        return obj.get_rating()

    class Meta:
        model = Answer
        fields = ['id', 'user', 'question', 'text', 'pub_date', 'rating']
        read_only_fields = ['user']
