from .models import Category


def categories(request):
    """Categories for the sidebar, available in every template as `all_categories`."""
    # A queryset is lazy: the database is asked only if a template uses it.
    return {'all_categories': Category.objects.order_by('name')}
