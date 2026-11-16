from django.db import migrations


def clean_up_votes(apps, schema_editor):
    """Prepare existing votes for the constraints added in the next migration.

    A vote must be +1 or -1, and a user may have only one vote per question
    or answer. Other values are reduced to their sign, zero votes are deleted,
    and of several votes by the same user only the latest one is kept.
    """
    for model_name, target in (('QuestionRating', 'question_id'), ('AnswerRating', 'answer_id')):
        rating_model = apps.get_model('qa_app', model_name)

        rating_model.objects.filter(rating=0).delete()
        rating_model.objects.filter(rating__gt=1).update(rating=1)
        rating_model.objects.filter(rating__lt=-1).update(rating=-1)

        seen = set()
        duplicates = []
        for vote_id, user_id, target_id in (
            rating_model.objects.order_by('-id').values_list('id', 'user_id', target)
        ):
            if (user_id, target_id) in seen:
                duplicates.append(vote_id)
            seen.add((user_id, target_id))
        rating_model.objects.filter(id__in=duplicates).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('qa_app', '0008_alter_pagevisit_browser_alter_pagevisit_os_and_more'),
    ]

    operations = [
        # Deleted votes cannot be restored, so going backwards does nothing.
        migrations.RunPython(clean_up_votes, migrations.RunPython.noop),
    ]
