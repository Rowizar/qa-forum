from rest_framework import permissions


class IsOwnerOrReadOnly(permissions.BasePermission):
    """Anyone may read; only the owner of an object (or staff) may change it.

    The view names the model field that holds the owner in `owner_field`.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_staff or getattr(obj, view.owner_field) == request.user
