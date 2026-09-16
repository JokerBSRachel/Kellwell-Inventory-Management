from datetime import timedelta
from .models import Week, CountyItem, Inventory, CountyMeal, DailySale

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
        old_week = Week.objects.get(county=county, status=0)
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
            end_inventory=old_inventory.end_inventory if old_inventory else 0,
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