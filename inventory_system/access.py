from dataclasses import dataclass
from django.db.models import QuerySet

from .models import County


@dataclass
class UserAccess:
    role: str          # "developer", "manager", "employee", or None
    counties: QuerySet  # active counties this user can access


def get_user_access(user) -> UserAccess:
    """Resolve a logged-in User to their role and the counties they can access."""

    if user.is_superuser or user.is_staff:
        return UserAccess(role="developer", counties=County.objects.filter(is_active=True))

    employee = getattr(user, "employee_profile", None)
    if employee is not None:
        return UserAccess(
            role="employee",
            counties=County.objects.filter(pk=employee.county_id, is_active=True),
        )

    manager = getattr(user, "manager_profile", None)
    if manager is not None:
        return UserAccess(
            role="manager",
            counties=manager.county_set.filter(is_active=True),
        )

    return UserAccess(role=None, counties=County.objects.none())