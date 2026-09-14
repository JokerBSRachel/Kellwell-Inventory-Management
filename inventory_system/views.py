from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, get_object_or_404, redirect

from .access import get_user_access, resolve_county, resolve_week
from .models import CountyCategory, CountyItem, Inventory, Week


@login_required
def dashboard(request):
    access = get_user_access(request.user)
    county_id = request.GET.get("county_id")

    county = resolve_county(request, county_id)
    if county:
        request.session["selected_county_id"] = county.pk

    return render(request, "inventory_system/dashboard.html", {
        "county": county,
        "counties": access.counties,
        "show_picker": access.counties.count() > 1,
    })


@login_required
def weekly_inventory(request, category_id=None, week_id=None):
    access = get_user_access(request.user)
    county = resolve_county(request)
    week = resolve_week(county, week_id)

    if category_id:
        category = get_object_or_404(CountyCategory, pk=category_id, county=county)
    else:
        category = CountyCategory.objects.filter(county=county, is_active=True).first()

    can_edit_previous = access.role in ("manager", "developer")
    is_editable = (week.status == 0) or (week.status == 1 and can_edit_previous)

    previous_week = Week.objects.filter(
        county=county, end_date__lt=week.end_date
    ).order_by("-end_date").first()

    previous_by_item = {}
    if previous_week:
        previous_rows = Inventory.objects.filter(
            week=previous_week, county_item__category=category
        )
        previous_by_item = {r.county_item_id: r for r in previous_rows}

    if request.method == "POST":
        if not is_editable:
            raise PermissionDenied("This week is no longer editable.")

        posted_rows = Inventory.objects.filter(
            week=week, county_item__category=category
        ).select_related("county_item__item")

        for inv in posted_rows:
            prev = previous_by_item.get(inv.county_item_id)
            starting_price = prev.end_price if prev else Decimal("0.00")
            starting_inventory = prev.end_inventory if prev else Decimal("0.00")

            def parse_field(field_name, fallback, allow_negative=False):
                raw = request.POST.get(f"{field_name}_{inv.pk}")
                if raw is None:
                    return None
                try:
                    value = Decimal(raw)
                    if not allow_negative and value < 0:
                        raise InvalidOperation
                    return value
                except (InvalidOperation, TypeError):
                    messages.error(
                        request,
                        f"Invalid {field_name.replace('_', ' ')} for {inv.county_item.item.item_name} — reverted."
                    )
                    return fallback

            price_value = parse_field("price", starting_price)
            received_1_value = parse_field("received_1", Decimal("0.00"))
            received_2_value = parse_field("received_2", Decimal("0.00"))
            inventory_value = parse_field("inventory", starting_inventory)
            deep_dive_value = request.POST.get(f"deep_dive_{inv.pk}", "")

            if price_value is None:
                continue  # this row wasn't submitted at all

            inv.end_price = price_value
            inv.end_received_1 = received_1_value
            inv.end_received_2 = received_2_value
            inv.end_inventory = inventory_value
            inv.deep_dive = deep_dive_value
            inv.save()

        if week.status == 0:
            return redirect("weekly_inventory_category", category_id=category.pk)
        else:
            return redirect("weekly_inventory_week", week_id=week.pk, category_id=category.pk)

    current_rows = Inventory.objects.filter(
        week=week,
        county_item__category=category,
        county_item__is_active=True,
    ).select_related("county_item__item")

    table_rows = []
    for row in current_rows:
        prev = previous_by_item.get(row.county_item_id)
        beginning_inventory = prev.end_inventory if prev else None
        total_usage = (beginning_inventory + row.end_received_1 + row.end_received_2) - row.end_inventory

        table_rows.append({
            "inventory_id": row.pk,
            "item_name": row.county_item.item.item_name,
            "unit": row.county_item.item_unit,
            "beginning_price": prev.end_price if prev else None,
            "beginning_received_1": prev.end_received_1 if prev else None,
            "beginning_received_2": prev.end_received_2 if prev else None,
            "beginning_inventory": beginning_inventory,
            "beginning_total": (prev.end_price * prev.end_inventory) if prev else None,
            "ending_price": row.end_price,
            "ending_received_1": row.end_received_1,
            "ending_received_2": row.end_received_2,
            "ending_inventory": row.end_inventory,
            "ending_total": row.end_price * row.end_inventory,
            "total_usage": total_usage,
            "deep_dive": row.deep_dive,
        })

    return render(request, "inventory_system/weekly_inventory.html", {
        "county": county,
        "week": week,
        "category": category,
        "table_rows": table_rows,
        "is_editable": is_editable,
    })