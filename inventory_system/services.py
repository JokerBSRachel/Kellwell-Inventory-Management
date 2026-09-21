from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum, F
from .models import Week, CountyItem, Inventory, CountyMeal, DailySale


def round_cents(value):
    """Round a Decimal to 2 decimal places using round-half-up (away from zero),
    matching Excel's rounding convention. Python's own Decimal formatting
    (e.g. f"{value:.2f}") defaults to round-half-to-even ("banker's rounding"),
    which lands a cent off from Excel on values that fall exactly on a .xx5
    boundary — e.g. 44.805 rounds to 44.80 under Python's default, 44.81 in Excel."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def totals_by_code(county, target_week, code_id=None):
    """Sums (price * inventory) across a county's active Inventory rows for a given
    week, grouped by FoodCode. Pass code_id to scope to just one code's total.
    Returns {code_id: {"county_item__category__code__code_number": ..,
                        "county_item__category__code__code_name": .., "total": Decimal}}.
    """
    if not target_week:
        return {}

    qs = Inventory.objects.filter(
        week=target_week,
        county_item__category__county=county,
        county_item__category__is_active=True,
        county_item__is_active=True,
    )
    if code_id is not None:
        qs = qs.filter(county_item__category__code_id=code_id)

    rows = (
        qs.values(
            "county_item__category__code_id",
            "county_item__category__code__code_number",
            "county_item__category__code__code_name",
        )
        .annotate(total=Sum(F("end_price") * F("end_inventory")))
    )
    return {r["county_item__category__code_id"]: r for r in rows}


def ensure_initial_weeks(county):
    """Creates (if needed) the hidden bootstrap week and the true first
    tracking week for a county. Returns (initial_week, first_week)."""
    if not county.tracking_start_date:
        return None, None

    initial_end_date = county.tracking_start_date - timedelta(days=7)
    initial_week, _ = Week.objects.get_or_create(
        county=county, end_date=initial_end_date,
        defaults={"status": 0, "is_initial": True},
    )
    first_week, _ = Week.objects.get_or_create(
        county=county, end_date=county.tracking_start_date,
        defaults={"status": 0, "is_initial": False},
    )
    return initial_week, first_week


def rollover_county_week(county):
    """Rolls a county's current open week forward into a new week.
    Returns the newly created Week."""

    try:
        old_week = Week.objects.get(county=county, status=0, is_initial=False)
    except Week.DoesNotExist:
        raise ValueError(f"No open week found for {county}. Cannot roll over.")
    except Week.MultipleObjectsReturned:
        raise ValueError(f"Multiple open weeks found for {county}. Fix data before rolling over.")

    new_end_date = old_week.end_date + timedelta(days=7)
    new_week = Week.objects.create(county=county, end_date=new_end_date, status=0)

    Week.objects.filter(county=county, status=1).update(status=2)
    old_week.status = 1
    old_week.save()

    county_items = CountyItem.objects.filter(category__county=county, is_active=True)
    for county_item in county_items:
        old_inventory = Inventory.objects.filter(county_item=county_item, week=old_week).first()
        Inventory.objects.create(
            county_item=county_item,
            week=new_week,
            end_price=old_inventory.end_price if old_inventory else 0,
            end_inventory=0,
            end_received_1=0,
            end_received_2=0,
        )

    county_meals = CountyMeal.objects.filter(county=county, is_active=True)
    for county_meal in county_meals:
        for i in range(7):
            sale_date = new_end_date - timedelta(days=6 - i)
            DailySale.objects.create(
                county_meal=county_meal,
                week=new_week,
                sale_date=sale_date,
                sale_count=0,
            )

    return new_week