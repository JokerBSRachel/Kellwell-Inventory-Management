from datetime import timedelta
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from .access import get_user_access, resolve_county, resolve_week, is_week_editable
from .models import CountyCategory, CountyItem, Inventory, Item, Week, Unit, CountyMeal, DailySale, WeeklySignoff
from .services import rollover_county_week


def save_sheet_fields(request, week, category, access):
    can_edit_previous = access.role in ("manager", "developer")
    is_editable = (week.status == 0) or (week.status == 1 and can_edit_previous)
    if not is_editable:
        return

    previous_week = Week.objects.filter(
        county=week.county, end_date__lt=week.end_date
    ).order_by("-end_date").first()

    allow_beginning_edit = is_editable and previous_week is not None and previous_week.is_initial
    allow_name_edit = allow_beginning_edit or (is_editable and can_edit_previous)

    previous_by_item = {}
    if previous_week:
        previous_rows = Inventory.objects.filter(
            week=previous_week, county_item__category=category
        )
        previous_by_item = {r.county_item_id: r for r in previous_rows}

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
            raw = raw.strip()
            if raw == "":
                return Decimal("0.00")
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
            continue

        inv.end_price = price_value
        inv.end_received_1 = received_1_value
        inv.end_received_2 = received_2_value
        inv.end_inventory = inventory_value
        inv.deep_dive = deep_dive_value
        inv.save()

        if allow_name_edit:
            new_display_name = request.POST.get(f"item_name_{inv.pk}", "").strip()
            if new_display_name != inv.county_item.display_name:
                inv.county_item.display_name = new_display_name

            new_unit_name = request.POST.get(f"item_unit_{inv.pk}", "").strip()
            if new_unit_name:
                new_unit = Unit.get_or_create_matching(new_unit_name)
                if new_unit != inv.county_item.unit:
                    inv.county_item.unit = new_unit
            else:
                inv.county_item.unit = None

            inv.county_item.save()

        if allow_beginning_edit and prev:
            def parse_begin(field_name, fallback):
                raw = request.POST.get(f"{field_name}_{prev.pk}")
                if raw is None:
                    return fallback
                raw = raw.strip()
                if raw == "":
                    return Decimal("0.00")
                try:
                    value = Decimal(raw)
                    if value < 0:
                        raise InvalidOperation
                    return value
                except (InvalidOperation, TypeError):
                    return fallback

            prev.end_price = parse_begin("begin_price", prev.end_price)
            prev.end_received_1 = parse_begin("begin_received_1", Decimal("0.00"))
            prev.end_received_2 = parse_begin("begin_received_2", Decimal("0.00"))
            prev.end_inventory = parse_begin("begin_inventory", prev.end_inventory)
            prev.save()


@login_required
def dashboard(request):
    access = get_user_access(request.user)
    county_id = request.GET.get("county_id")
    force_picker = "switch" in request.GET

    if county_id:
        county = resolve_county(request, county_id)
        if county:
            request.session["selected_county_id"] = county.pk
            return redirect("weekly_inventory")
    elif not force_picker:
        county = resolve_county(request)
        if county:
            request.session["selected_county_id"] = county.pk
            return redirect("weekly_inventory")

    return render(request, "inventory_system/dashboard.html", {
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

    allow_beginning_edit = is_editable and previous_week is not None and previous_week.is_initial
    allow_name_edit = allow_beginning_edit or (is_editable and can_edit_previous)

    previous_by_item = {}
    if previous_week:
        previous_rows = Inventory.objects.filter(
            week=previous_week, county_item__category=category
        )
        previous_by_item = {r.county_item_id: r for r in previous_rows}

    if request.method == "POST":
        if not is_editable:
            raise PermissionDenied("This week is no longer editable.")

        save_sheet_fields(request, week, category, access)

        if week.status == 0:
            return redirect("weekly_inventory_category", category_id=category.pk)
        else:
            return redirect("weekly_inventory_week", week_id=week.pk, category_id=category.pk)

    current_rows = Inventory.objects.filter(
        week=week,
        county_item__category=category,
        county_item__is_active=True,
    ).select_related("county_item__item", "county_item__unit").order_by("county_item__sort_order", "county_item_id")

    table_rows = []
    for row in current_rows:
        prev = previous_by_item.get(row.county_item_id)
        beginning_inventory = prev.end_inventory if prev else None
        if beginning_inventory is not None:
            total_usage = (beginning_inventory + row.end_received_1 + row.end_received_2) - row.end_inventory
        else:
            total_usage = None

        table_rows.append({
            "beginning_inventory_id": prev.pk if prev else None,
            "inventory_id": row.pk,
            "county_item_id": row.county_item_id,
            "item_name": row.county_item.display, 
            "unit": row.county_item.unit.unit_name if row.county_item.unit else "",         
            "beginning_price": prev.end_price if prev else None,
            "beginning_received_1": prev.end_received_1 if prev else None,
            "beginning_received_2": prev.end_received_2 if prev else None,
            "beginning_inventory": beginning_inventory,
            "beginning_total": f"{(prev.end_price * prev.end_inventory):.2f}" if prev else "0.00",
            "ending_price": row.end_price,
            "ending_received_1": row.end_received_1,
            "ending_received_2": row.end_received_2,
            "ending_inventory": row.end_inventory,
            "ending_total": f"{(row.end_price * row.end_inventory):.2f}",
            "total_usage": f"{total_usage:.2f}" if total_usage is not None else "0.00",
            "deep_dive": row.deep_dive,
        })

    unit_options = Unit.objects.filter(is_active=True)
    item_options = Item.objects.filter(is_active=True)

    return render(request, "inventory_system/weekly_inventory.html", {
        "county": county,
        "week": week,
        "category": category,
        "table_rows": table_rows,
        "is_editable": is_editable,
        "allow_beginning_edit": allow_beginning_edit, 
        "allow_name_edit": allow_name_edit,
        "unit_options": unit_options,
        "item_options": item_options,
    })


@login_required
@require_POST
def delete_item(request, inventory_id):
    county = resolve_county(request)
    inv = get_object_or_404(Inventory, pk=inventory_id, week__county=county)
    week = inv.week
    category_id = inv.county_item.category_id

    access = get_user_access(request.user)
    can_edit_previous = access.role in ("manager", "developer")
    is_editable = (week.status == 0) or (week.status == 1 and can_edit_previous)

    if not is_editable:
        raise PermissionDenied("This week is no longer editable.")

    save_sheet_fields(request, week, inv.county_item.category, access)

    county_item = inv.county_item
    county_item.is_active = False
    county_item.save()

    messages.success(request, f"{county_item.item.item_name} removed from this sheet.", extra_tags="undoable")

    request.session["last_action"] = {
        "type": "deactivate_county_item",
        "county_item_id": county_item.pk,
    }

    if week.status == 0:
        return redirect("weekly_inventory_category", category_id=category_id)
    else:
        return redirect("weekly_inventory_week", week_id=week.pk, category_id=category_id)


@login_required
@require_POST
def add_item(request):
    county = resolve_county(request)
    category = get_object_or_404(CountyCategory, pk=request.POST.get("category_id"), county=county)
    week = resolve_week(county)

    access = get_user_access(request.user)
    can_edit_previous = access.role in ("manager", "developer")
    is_editable = (week.status == 0) or (week.status == 1 and can_edit_previous)
    if not is_editable:
        raise PermissionDenied("This week is no longer editable.")

    save_sheet_fields(request, week, category, access)

    item_name = request.POST.get("item_name", "").strip()
    unit_name = request.POST.get("item_unit", "").strip()

    if not item_name:
        messages.error(request, "Item name is required.")
        return redirect("weekly_inventory_category", category_id=category.pk)

    item = Item.get_or_create_matching(item_name)
    unit = Unit.get_or_create_matching(unit_name) if unit_name else None

    county_item = CountyItem.objects.filter(item=item, category=category, unit=unit).first()
    max_order = CountyItem.objects.filter(category=category).order_by("-sort_order").values_list("sort_order", flat=True).first() or 0

    if county_item is None:
        county_item = CountyItem.objects.create(
            item=item, category=category, unit=unit, is_active=True, sort_order=max_order + 1
        )
    else:
        county_item.is_active = True
        county_item.sort_order = max_order + 1
        county_item.save()

    def parse_starting(field_name):
        try:
            value = Decimal(request.POST.get(field_name, "0"))
            return value if value >= 0 else Decimal("0.00")
        except (InvalidOperation, TypeError):
            return Decimal("0.00")

    entered_price = parse_starting("starting_price")
    entered_inventory = parse_starting("starting_inventory")
    entered_received_1 = parse_starting("starting_received_1")
    entered_received_2 = parse_starting("starting_received_2")

    previous_week = Week.objects.filter(
        county=county, end_date__lt=week.end_date
    ).order_by("-end_date").first()

    if previous_week and previous_week.is_initial:
        Inventory.objects.get_or_create(
            county_item=county_item,
            week=previous_week,
            defaults={"end_price": entered_price,
                      "end_received_1": entered_received_1, "end_received_2": entered_received_2,
                      "end_inventory": entered_inventory},
        )

    inv, created = Inventory.objects.get_or_create(
        county_item=county_item,
        week=week,
        defaults={"end_price": entered_price, "end_received_1": Decimal("0.00"),
                  "end_received_2": Decimal("0.00"), "end_inventory": entered_inventory},
    )
    if not created:
        inv.end_price = entered_price
        inv.end_received_1 = Decimal("0.00")
        inv.end_received_2 = Decimal("0.00")
        inv.end_inventory = entered_inventory
        inv.save()

    request.session["last_action"] = {
        "type": "create_county_item",
        "county_item_id": county_item.pk,
        "week_id": week.pk,
    }

    return redirect("weekly_inventory_category", category_id=category.pk)


@login_required
@require_POST
def undo_last_action(request):
    action = request.session.pop("last_action", None)
    if not action:
        messages.error(request, "Nothing to undo.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    if action["type"] == "deactivate_county_item":
        county_item = get_object_or_404(CountyItem, pk=action["county_item_id"])
        county_item.is_active = True
        county_item.save()
        messages.success(request, "Item restored.")

    return redirect(request.META.get("HTTP_REFERER", "dashboard"))


@login_required
@require_POST
def reorder_items(request):
    county = resolve_county(request)
    category = get_object_or_404(CountyCategory, pk=request.POST.get("category_id"), county=county)
    week = resolve_week(county)

    access = get_user_access(request.user)
    can_edit_previous = access.role in ("manager", "developer")
    is_editable = (week.status == 0) or (week.status == 1 and can_edit_previous)
    if not is_editable:
        raise PermissionDenied("This week is no longer editable.")

    ordered_ids = request.POST.getlist("county_item_id")
    for index, county_item_id in enumerate(ordered_ids):
        CountyItem.objects.filter(pk=county_item_id, category=category).update(sort_order=index)

    return JsonResponse({"status": "ok"})


@login_required
def roll_to_next_week(request):
    county = resolve_county(request)

    if county.is_template:
        raise PermissionDenied("This county is a template and cannot be rolled over.")

    if request.method == "POST":
        try:
            rollover_county_week(county)
            messages.success(request, "Week rolled over successfully.")
        except ValueError as e:
            messages.error(request, str(e))
        return redirect("weekly_inventory")

    return render(request, "inventory_system/roll_confirm.html", {"county": county})


@login_required
def daily_sales(request, week_id=None):
    access = get_user_access(request.user)
    county = resolve_county(request)
    week = resolve_week(county, week_id)
    is_editable = is_week_editable(week, access)

    county_meals = list(
        CountyMeal.objects.filter(county=county, is_active=True).select_related("meal").order_by("pk")
    )
    dates = [week.end_date - timedelta(days=6 - i) for i in range(7)]

    # Self-heal: make sure a DailySale row exists for every (meal, date) in this
    # week, in case rollover hasn't run yet (e.g. a county's very first week).
    for county_meal in county_meals:
        for sale_date in dates:
            DailySale.objects.get_or_create(
                county_meal=county_meal, week=week, sale_date=sale_date,
                defaults={"sale_count": 0},
            )

    if request.method == "POST":
        if not is_editable:
            raise PermissionDenied("This week is no longer editable.")

        sales = DailySale.objects.filter(week=week, county_meal__in=county_meals)
        for sale in sales:
            raw = request.POST.get(f"sale_{sale.pk}", "").strip()
            if raw == "":
                sale.sale_count = 0
            else:
                try:
                    value = int(raw)
                    if value < 0:
                        raise ValueError
                    sale.sale_count = value
                except ValueError:
                    messages.error(
                        request,
                        f"Invalid count for {sale.county_meal.meal} on {sale.sale_date} — reverted."
                    )
                    continue
            sale.save()

        if week.status == 0:
            return redirect("daily_sales")
        else:
            return redirect("daily_sales_week", week_id=week.pk)

    sales = DailySale.objects.filter(week=week, county_meal__in=county_meals)
    sales_by_date_meal = {(s.sale_date, s.county_meal_id): s for s in sales}

    meal_totals = [0] * len(county_meals)
    grid_rows = []
    grand_total = 0

    for sale_date in dates:
        row_cells = []
        row_total = 0
        for idx, cm in enumerate(county_meals):
            sale = sales_by_date_meal.get((sale_date, cm.pk))
            count = sale.sale_count if sale else 0
            row_cells.append({"daily_sale_id": sale.pk if sale else None, "count": count})
            row_total += count
            meal_totals[idx] += count
        grand_total += row_total
        grid_rows.append({"date": sale_date, "cells": row_cells, "row_total": row_total})

    meal_totals_display = [
        {"meal_name": cm.meal.meal_name, "total": total}
        for cm, total in zip(county_meals, meal_totals)
    ]

    signoff = WeeklySignoff.objects.filter(week=week).select_related("manager").first()
    can_sign = hasattr(request.user, "manager_profile")

    return render(request, "inventory_system/daily_sales.html", {
        "county": county,
        "week": week,
        "county_meals": county_meals,
        "grid_rows": grid_rows,
        "meal_totals_display": meal_totals_display,
        "grand_total": grand_total,
        "is_editable": is_editable,
        "signoff": signoff,
        "can_sign": can_sign,
        "active_report_tab": "daily_sales",
    })


@login_required
@require_POST
def sign_off_week(request, week_id):
    county = resolve_county(request)
    week = get_object_or_404(Week, pk=week_id, county=county)

    manager = getattr(request.user, "manager_profile", None)
    if manager is None:
        raise PermissionDenied("Only a manager can sign off a week.")

    WeeklySignoff.objects.get_or_create(week=week, defaults={"manager": manager})

    if week.status == 0:
        return redirect("daily_sales")
    else:
        return redirect("daily_sales_week", week_id=week.pk)