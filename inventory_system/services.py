from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum, F
from .models import Week, CountyItem, Inventory, CountyMeal, DailySale, Employee, WeeklyPayroll


def round_to(value, decimal_places):
    """Round a Decimal to the given number of places using round-half-up —
    same convention as round_cents, but for non-currency ratios (cents per
    meal, weeks of food on hand) that need more or fewer than 2 decimals."""
    exponent = Decimal("1").scaleb(-decimal_places)
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round a Decimal to 2 decimal places using round-half-up (away from zero),
    matching Excel's rounding convention. Python's own Decimal formatting
    (e.g. f"{value:.2f}") defaults to round-half-to-even ("banker's rounding"),
    which lands a cent off from Excel on values that fall exactly on a .xx5
    boundary — e.g. 44.805 rounds to 44.80 under Python's default, 44.81 in Excel."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_decimal(value):
    """Defensively coerces a DB aggregate result to Decimal. Django's automatic
    output_field inference for computed expressions like Sum(F(a)*F(b)) can, in
    rare cases, resolve to a plain float instead of Decimal — this guards
    against the resulting 'unsupported operand type... Decimal and float'
    crash wherever that value later gets used in Decimal arithmetic."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


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
    result = {}
    for r in rows:
        r["total"] = to_decimal(r["total"])
        result[r["county_item__category__code_id"]] = r
    return result


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


def negative_usage_rows(county, week):
    """Returns the rows in `week` whose usage is negative, as a list of dicts
    ordered the way the inventory tabs are. Usage uses the same formula as the
    inventory sheet: the previous week's ending inventory plus this week's
    received 1 and 2, minus this week's ending inventory. Rows with no
    previous-week row have no defined usage and are skipped, matching the
    sheet. Rows in inactive categories are skipped because they aren't
    visible on any tab."""
    previous_week = Week.objects.filter(
        county=county, end_date__lt=week.end_date
    ).order_by("-end_date").first()
    if previous_week is None:
        return []

    beginning_by_item = {
        row.county_item_id: row.end_inventory
        for row in Inventory.objects.filter(week=previous_week)
    }

    rows = Inventory.objects.filter(
        week=week, county_item__category__is_active=True
    ).select_related(
        "county_item__item", "county_item__unit", "county_item__category__code"
    ).order_by(
        "county_item__category__code__code_number",
        "county_item__category__subcategory_id",
        "county_item__sort_order",
        "county_item_id",
    )

    negatives = []
    for row in rows:
        beginning = beginning_by_item.get(row.county_item_id)
        if beginning is None:
            continue
        usage = (beginning + row.end_received_1 + row.end_received_2) - row.end_inventory
        if usage < 0:
            category = row.county_item.category
            negatives.append({
                "category": f"{category.code.code_number}-{category.subcategory_id}",
                "name": row.county_item.display,
                "unit": row.county_item.unit.unit_name if row.county_item.unit else "",
                "usage": usage,
            })
    return negatives


def rollover_county_week(county):
    """Rolls a county's current open week forward into a new week.
    Returns the newly created Week."""

    try:
        old_week = Week.objects.get(county=county, status=0, is_initial=False)
    except Week.DoesNotExist:
        raise ValueError(f"No open week found for {county}. Cannot roll over.")
    except Week.MultipleObjectsReturned:
        raise ValueError(f"Multiple open weeks found for {county}. Fix data before rolling over.")

    # Block the rollover while any item has negative usage. This must run
    # before the first write below: the function isn't wrapped in a
    # transaction, so raising after Week.objects.create would leave a
    # half-built week behind.
    negatives = negative_usage_rows(county, old_week)
    if negatives:
        shown = [f"{n['name']} ({n['category']})" for n in negatives[:5]]
        extra = len(negatives) - len(shown)
        summary = ", ".join(shown) + (f", and {extra} more" if extra else "")
        raise ValueError(
            f"Cannot roll over: {len(negatives)} item(s) have negative usage. Fix these first: {summary}."
        )

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

    # Carry the active roster forward. From here on, the week's WeeklyPayroll
    # rows (not the Employee table) decide who appears on the WOR payroll report.
    for employee in Employee.objects.filter(county=county, is_active=True):
        WeeklyPayroll.objects.create(employee=employee, week=new_week)

    return new_week