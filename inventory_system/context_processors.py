from .access import get_user_access
from .models import Week, CountyCategory


def sidebar_context(request):
    if not request.user.is_authenticated:
        return {}

    access = get_user_access(request.user)
    county_id = request.session.get("selected_county_id")
    county = access.counties.filter(pk=county_id).first() if county_id else None

    week = None
    categories = []
    if county:
        week = Week.objects.filter(county=county).order_by("-end_date").first()
        categories = CountyCategory.objects.filter(county=county, is_active=True)

    previous_week = None
    if county and week:
        previous_week = Week.objects.filter(
            county=county, end_date__lt=week.end_date
        ).order_by("-end_date").first()

    return {
        "nav_county": county,
        "nav_counties": access.counties,
        "nav_role": access.role,
        "nav_week": week,
        "nav_categories": categories,
        "nav_previous_week": previous_week,
    }