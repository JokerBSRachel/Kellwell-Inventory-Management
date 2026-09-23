from .access import get_user_access
from .models import Week, CountyCategory, CountyRecipe


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
    recipe_codes = []
    viewed_recipe_code_id = None
    viewing_recipes = False

    if county:
        week = Week.objects.filter(county=county).order_by("-end_date").first()
        categories = CountyCategory.objects.filter(county=county, is_active=True)
        weeks = Week.objects.filter(county=county, is_initial=False).order_by("-end_date")

        url_week_id = None
        url_code_id = None
        url_name = None
        if request.resolver_match:
            url_week_id = request.resolver_match.kwargs.get("week_id")
            url_code_id = request.resolver_match.kwargs.get("code_id")
            url_name = request.resolver_match.url_name
        viewed_week_id = int(url_week_id) if url_week_id else (week.pk if week else None)
        viewed_recipe_code_id = int(url_code_id) if url_code_id else None
        # Broader than viewed_recipe_code_id (which is only set once a specific
        # code is being browsed) — this also covers the recipes landing page,
        # which has no code_id in its URL but should still expand the toggle.
        viewing_recipes = url_name in ("recipes", "recipes_code", "recipe_detail")
        

        # Group this county's recipes by code, in code order, each list ordered
        # by recipe_number — mirrors nav_weeks/nav_categories but nested, since
        # (unlike categories) each code's recipe list is different per code.
        county_recipes = CountyRecipe.objects.filter(county=county).select_related(
            "recipe__recipe_code"
        ).order_by("recipe__recipe_code__recipe_code", "recipe_number")

        codes_by_id = {}
        for cr in county_recipes:
            code = cr.recipe.recipe_code
            entry = codes_by_id.get(code.pk)
            if entry is None:
                entry = {"code": code, "recipes": []}
                codes_by_id[code.pk] = entry
                recipe_codes.append(entry)
            entry["recipes"].append(cr)

    return {
        "nav_county": county,
        "nav_counties": access.counties,
        "nav_role": access.role,
        "nav_week": week,
        "nav_categories": categories,
        "nav_weeks": weeks,
        "nav_viewed_week_id": viewed_week_id,
        "nav_recipe_codes": recipe_codes,
        "nav_viewed_recipe_code_id": viewed_recipe_code_id,
        "nav_viewing_recipes": viewing_recipes,
    }