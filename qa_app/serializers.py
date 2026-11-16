from rest_framework import serializers

from .models import Answer, Question


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

    def validate_question(self, question):
        # An existing answer keeps its question; only new answers (or answers
        # moved to another question) are checked.
        moved = self.instance is None or self.instance.question_id != question.id
        if moved and question.is_closed:
            raise serializers.ValidationError('This question is closed and does not accept new answers.')
        return question

    class Meta:
        model = Answer
        fields = ['id', 'user', 'question', 'text', 'pub_date', 'rating']
        read_only_fields = ['user']
