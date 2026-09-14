from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

from .access import get_user_access


@login_required
def dashboard(request):
    access = get_user_access(request.user)
    county_names = ", ".join(c.county_name for c in access.counties) or "(none)"
    return HttpResponse(f"Logged in as {request.user}. Role: {access.role}. Counties: {county_names}")