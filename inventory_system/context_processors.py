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
    weeks = []
    viewed_week_id = None
    if county:
        week = Week.objects.filter(county=county).order_by("-end_date").first()
        categories = CountyCategory.objects.filter(county=county, is_active=True)
        weeks = Week.objects.filter(county=county, is_initial=False).order_by("-end_date")

        url_week_id = None
        if request.resolver_match:
            url_week_id = request.resolver_match.kwargs.get("week_id")
        viewed_week_id = int(url_week_id) if url_week_id else (week.pk if week else None)


    return {
        "nav_county": county,
        "nav_counties": access.counties,
        "nav_role": access.role,
        "nav_week": week,
        "nav_categories": categories,
        "nav_weeks": weeks,
        "nav_viewed_week_id": viewed_week_id,
    }