from dataclasses import dataclass
from django.db.models import QuerySet
from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import County, Week


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


def resolve_county(request, county_id=None):
    """Given a request and an optional county_id from the URL, return the County
    the user should be viewing, or None if they need to pick one (e.g. a manager
    with multiple counties and none specified yet)."""

    access = get_user_access(request.user)

    if county_id is not None:
        county = access.counties.filter(pk=county_id).first()
        if county is None:
            raise PermissionDenied("You do not have access to this county.")
        return county

    session_county_id = request.session.get("selected_county_id")
    if session_county_id is not None:
        county = access.counties.filter(pk=session_county_id).first()
        if county is not None:
            return county

    if access.counties.count() == 1:
        return access.counties.first()

    return None


def resolve_week(county, week_id=None):
    """Given a county and an optional week_id from the URL, return the Week to display.
    Defaults to the most recent (current) week for that county."""

    if week_id is not None:
        week = Week.objects.filter(pk=week_id, county=county).first()
        if week is None:
            raise Http404("Week not found for this county.")
        return week

    week = Week.objects.filter(county=county).order_by("-end_date").first()
    if week is None:
        raise Http404("No weeks exist yet for this county.")
    return week