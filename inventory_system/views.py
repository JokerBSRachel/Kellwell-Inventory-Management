from datetime import timedelta
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.http import JsonResponse, Http404

from .access import get_user_access, resolve_county, resolve_week, is_week_editable
from .models import CountyCategory, CountyItem, Inventory, Item, Week, Unit, CountyMeal, DailySale, \
                    WeeklySignoff, FoodCode, Invoice, InvoiceLineItem, Vendor, Employee, WeeklyPayroll, \
                    CountyRecipe
from .services import rollover_county_week, totals_by_code, round_cents, round_to, to_decimal

FOOD_CODE_CEILING = 200  # code_numbers below this are "Food"; at/above are "Non-food"


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
        # A brand-new item (no previous-week row yet) is treated like the true
        # first-tracking-week bootstrap case for THIS row only — matches the
        # same rule weekly_inventory's display logic uses.
        row_is_new = inv.is_new_item
        row_allow_beginning_edit = allow_beginning_edit or (is_editable and row_is_new)
        row_allow_name_edit = row_allow_beginning_edit or allow_name_edit

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

        if row_allow_name_edit:
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

        if row_allow_beginning_edit:
            def parse_begin(field_name, fallback):
                raw = request.POST.get(f"{field_name}_{inv.pk}")
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

            if prev is None:
                # Brand-new item: there's no previous-week row to update, so
                # create one from the entered Beginning values — same as the
                # true first-week bootstrap flow does.
                Inventory.objects.create(
                    county_item=inv.county_item,
                    week=previous_week,
                    end_price=parse_begin("begin_price", Decimal("0.00")),
                    end_received_1=parse_begin("begin_received_1", Decimal("0.00")),
                    end_received_2=parse_begin("begin_received_2", Decimal("0.00")),
                    end_inventory=parse_begin("begin_inventory", Decimal("0.00")),
                )
            else:
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
    ).select_related("county_item__item", "county_item__unit").order_by("county_item__sort_order", "county_item_id")

    table_rows = []
    page_beginning_total = Decimal("0.00")
    page_ending_total = Decimal("0.00")
    for row in current_rows:
        prev = previous_by_item.get(row.county_item_id)
        beginning_inventory = prev.end_inventory if prev else None
        if beginning_inventory is not None:
            total_usage = (beginning_inventory + row.end_received_1 + row.end_received_2) - row.end_inventory
        else:
            total_usage = None

        # A brand-new item (no previous-week row yet) is treated like the
        # true first-tracking-week bootstrap case for THIS row only — anyone
        # editing the sheet can set its name/unit/beginning values, since
        # there's no carried-forward data yet for a manager to own.
        row_is_new = row.is_new_item
        row_allow_beginning_edit = allow_beginning_edit or (is_editable and row_is_new)
        row_allow_name_edit = row_allow_beginning_edit or allow_name_edit

        # Keep the exact (unrounded) products for the page-total accumulator,
        # and only round once, at display time — matches how Excel's SUM()
        # works (sums the underlying exact cell values, not what's displayed)
        # and avoids the "round each row, then sum the rounded rows" penny drift.
        beginning_total_exact = (prev.end_price * prev.end_inventory) if prev else Decimal("0.00")
        ending_total_exact = row.end_price * row.end_inventory
        page_beginning_total += beginning_total_exact
        page_ending_total += ending_total_exact

        table_rows.append({
            "inventory_id": row.pk,
            "county_item_id": row.county_item_id,
            "item_name": row.county_item.display, 
            "unit": row.county_item.unit.unit_name if row.county_item.unit else "",         
            "allow_beginning_edit": row_allow_beginning_edit,
            "allow_name_edit": row_allow_name_edit,
            "beginning_price": prev.end_price if prev else None,
            "beginning_received_1": prev.end_received_1 if prev else None,
            "beginning_received_2": prev.end_received_2 if prev else None,
            "beginning_inventory": beginning_inventory,
            "beginning_total": str(round_cents(beginning_total_exact)),
            "beginning_total_tenthousandths": int(beginning_total_exact * 10000),
            "ending_price": row.end_price,
            "ending_received_1": row.end_received_1,
            "ending_received_2": row.end_received_2,
            "ending_inventory": row.end_inventory,
            "ending_total": str(round_cents(ending_total_exact)),
            "ending_total_tenthousandths": int(ending_total_exact * 10000),
            "total_usage": f"{total_usage:.2f}" if total_usage is not None else "0.00",
            "deep_dive": row.deep_dive,
        })
    # If this is the LAST active subcategory under its FoodCode (e.g. 101-6 when a
    # county's 101 code runs 101-1 through 101-6), also show that code's total
    # across every subcategory beneath it — a checkpoint before moving to the next code.
    sibling_subcategory_ids = list(CountyCategory.objects.filter(
        county=county, code=category.code, is_active=True
    ).values_list("subcategory_id", flat=True))
    show_parent_total = category.subcategory_id == max(sibling_subcategory_ids, default=category.subcategory_id)

    parent_beginning_excl_current = Decimal("0.00")
    parent_ending_excl_current = Decimal("0.00")
    if show_parent_total:
        beginning_by_code = totals_by_code(county, previous_week, code_id=category.code_id)
        ending_by_code = totals_by_code(county, week, code_id=category.code_id)
        parent_beginning_total = beginning_by_code.get(category.code_id, {}).get("total") or Decimal("0.00")
        parent_ending_total = ending_by_code.get(category.code_id, {}).get("total") or Decimal("0.00")
        # Store as an offset (everything except this page's own rows) so the
        # template's JS can add the live-edited current-page total on top of it.
        parent_beginning_excl_current = parent_beginning_total - page_beginning_total
        parent_ending_excl_current = parent_ending_total - page_ending_total

    unit_options = Unit.objects.filter(is_active=True)
    item_options = Item.objects.filter(is_active=True)

    week_end_date = week.end_date.strftime("%m/%d/%y")
    week_start_date = (week.end_date - timedelta(days=7)).strftime("%m/%d/%y")

    return render(request, "inventory_system/weekly_inventory.html", {
        "county": county,
        "week_start_date": week_start_date,
        "week_end_date": week_end_date,
        "week": week,
        "category": category,
        "table_rows": table_rows,
        "page_beginning_total": str(round_cents(page_beginning_total)),
        "page_ending_total": str(round_cents(page_ending_total)),
        "show_parent_total": show_parent_total,
        "parent_code_number": category.code.code_number,
        "parent_beginning_excl_current_tenthousandths": int(parent_beginning_excl_current * 10000),
        "parent_ending_excl_current_tenthousandths": int(parent_ending_excl_current * 10000),
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
    is_editable = is_week_editable(week, access)

    if not is_editable:
        raise PermissionDenied("This week is no longer editable.")

    save_sheet_fields(request, week, inv.county_item.category, access)

    county_item = inv.county_item
    county_item.is_active = False
    county_item.save()

    def snapshot(row):
        return {
            "week_id": row.week_id,
            "end_price": str(row.end_price),
            "end_received_1": str(row.end_received_1),
            "end_received_2": str(row.end_received_2),
            "end_inventory": str(row.end_inventory),
            "deep_dive": row.deep_dive,
        }

    deleted_snapshots = [snapshot(inv)]
    inv.delete()

    # If deleting from the previous (admin-editable) week, also remove the
    # matching row from the current week — otherwise the current week's row
    # would be left with no prior week to derive its Beginning values from.
    if week.status == 1:
        current_week = Week.objects.filter(
            county=county, status=0, is_initial=False
        ).order_by("-end_date").first()
        if current_week:
            current_inv = Inventory.objects.filter(
                county_item=county_item, week=current_week
            ).first()
            if current_inv:
                deleted_snapshots.append(snapshot(current_inv))
                current_inv.delete()

    messages.success(request, f"{county_item.item.item_name} removed from this sheet.", extra_tags="undoable")

    request.session["last_action"] = {
        "type": "delete_item",
        "county_item_id": county_item.pk,
        "deleted_inventory": deleted_snapshots,
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
    week = resolve_week(county, request.POST.get("week_id"))

    access = get_user_access(request.user)
    is_editable = is_week_editable(week, access)
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

    if previous_week:
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
                  "end_received_2": Decimal("0.00"), "end_inventory": entered_inventory, "is_new_item": True},
    )
    if not created:
        inv.end_price = entered_price
        inv.end_received_1 = Decimal("0.00")
        inv.end_received_2 = Decimal("0.00")
        inv.end_inventory = entered_inventory
        inv.is_new_item = True
        inv.save()

    # If adding to the previous (admin-editable) week, also create the matching
    # row in the current week — same carry-forward values rollover would have
    # used, so it doesn't just silently stay missing from the current sheet.
    if week.status == 1:
        current_week = Week.objects.filter(
            county=county, status=0, is_initial=False
        ).order_by("-end_date").first()
        if current_week:
            Inventory.objects.get_or_create(
                county_item=county_item,
                week=current_week,
                defaults={"end_price": entered_price, "end_received_1": Decimal("0.00"),
                          "end_received_2": Decimal("0.00"), "end_inventory": Decimal("0.00"), "is_new_item": True},
            )

    request.session["last_action"] = {
        "type": "create_county_item",
        "county_item_id": county_item.pk,
        "week_id": week.pk,
    }

    if week.status == 0:
        return redirect("weekly_inventory_category", category_id=category.pk)
    else:
        return redirect("weekly_inventory_week", week_id=week.pk, category_id=category.pk)


@login_required
@require_POST
def undo_last_action(request):
    action = request.session.pop("last_action", None)
    if not action:
        messages.error(request, "Nothing to undo.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))

    if action["type"] == "delete_item":
        county_item = get_object_or_404(CountyItem, pk=action["county_item_id"])
        county_item.is_active = True
        county_item.save()

        for snap in action["deleted_inventory"]:
            Inventory.objects.get_or_create(
                county_item=county_item,
                week_id=snap["week_id"],
                defaults={
                    "end_price": Decimal(snap["end_price"]),
                    "end_received_1": Decimal(snap["end_received_1"]),
                    "end_received_2": Decimal(snap["end_received_2"]),
                    "end_inventory": Decimal(snap["end_inventory"]),
                    "deep_dive": snap["deep_dive"],
                },
            )
        messages.success(request, "Item restored.")

    return redirect(request.META.get("HTTP_REFERER", "dashboard"))


@login_required
@require_POST
def reorder_items(request):
    county = resolve_county(request)
    category = get_object_or_404(CountyCategory, pk=request.POST.get("category_id"), county=county)
    week = resolve_week(county, request.POST.get("week_id"))

    access = get_user_access(request.user)
    is_editable = is_week_editable(week, access)
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

    return redirect(request.META.get("HTTP_REFERER", "daily_sales"))


@login_required
def totals(request, week_id=None):
    county = resolve_county(request)
    week = resolve_week(county, week_id)

    previous_week = Week.objects.filter(
        county=county, end_date__lt=week.end_date
    ).order_by("-end_date").first()

    beginning_by_code = totals_by_code(county, previous_week)
    ending_by_code = totals_by_code(county, week)
    code_ids = set(beginning_by_code) | set(ending_by_code)

    county_codes = FoodCode.objects.filter(
        pk__in=CountyCategory.objects.filter(county=county, is_active=True).values_list("code_id", flat=True)
    ).distinct()


    columns = []
    for code in county_codes:
        beginning = beginning_by_code.get(code.pk, {}).get("total") or Decimal("0.00")
        ending = ending_by_code.get(code.pk, {}).get("total") or Decimal("0.00")
        columns.append({
            "code_number": code.code_number,
            "code_name": code.code_name,
            "beginning": beginning,
            "ending": ending,
        })
    columns.sort(key=lambda c: c["code_number"])

    food_columns = [c for c in columns if c["code_number"] < FOOD_CODE_CEILING]
    nonfood_columns = [c for c in columns if c["code_number"] >= FOOD_CODE_CEILING]

    food_total_beginning = sum((c["beginning"] for c in food_columns), Decimal("0.00"))
    food_total_ending = sum((c["ending"] for c in food_columns), Decimal("0.00"))
    grand_total_beginning = sum((c["beginning"] for c in columns), Decimal("0.00"))
    grand_total_ending = sum((c["ending"] for c in columns), Decimal("0.00"))

    signoff = WeeklySignoff.objects.filter(week=week).select_related("manager").first()
    can_sign = hasattr(request.user, "manager_profile")

    return render(request, "inventory_system/totals.html", {
        "county": county,
        "week": week,
        "food_columns": food_columns,
        "nonfood_columns": nonfood_columns,
        "food_total_beginning": food_total_beginning,
        "food_total_ending": food_total_ending,
        "grand_total_beginning": grand_total_beginning,
        "grand_total_ending": grand_total_ending,
        "signoff": signoff,
        "can_sign": can_sign,
        "active_report_tab": "totals",
    })


def save_invoice_fields(request, week, access, county_codes, invoices):
    is_editable = is_week_editable(week, access)
    if not is_editable:
        return

    def parse_amount(field_name, allow_negative=False):
        raw = request.POST.get(field_name, "").strip()
        if raw == "":
            return Decimal("0.00")
        try:
            value = Decimal(raw)
            if not allow_negative and value < 0:
                return Decimal("0.00")
            return value
        except InvalidOperation:
            return Decimal("0.00")

    for invoice in invoices:
        vendor_name = request.POST.get(f"vendor_{invoice.pk}", "").strip()
        if vendor_name:
            vendor = Vendor.get_or_create_matching(vendor_name)
            if vendor != invoice.vendor:
                invoice.vendor = vendor

        invoice.invoice_number = request.POST.get(f"invoice_number_{invoice.pk}", "").strip()
        invoice.tax = parse_amount(f"tax_{invoice.pk}")
        invoice.save()

        # Line item amounts CAN be negative (credit memos from a vendor).
        for code in county_codes:
            amount = parse_amount(f"amount_{code.pk}_{invoice.pk}", allow_negative=True)
            InvoiceLineItem.objects.filter(invoice=invoice, code=code).update(amount=amount)


@login_required
def invoices_recap(request, week_id=None):
    access = get_user_access(request.user)
    county = resolve_county(request)
    week = resolve_week(county, week_id)
    is_editable = is_week_editable(week, access)

    county_codes = list(FoodCode.objects.filter(
        pk__in=CountyCategory.objects.filter(county=county, is_active=True).values_list("code_id", flat=True)
    ).distinct().order_by("code_number"))
    food_codes = [c for c in county_codes if c.code_number < FOOD_CODE_CEILING]
    nonfood_codes = [c for c in county_codes if c.code_number >= FOOD_CODE_CEILING]

    invoices = list(Invoice.objects.filter(week=week).select_related("vendor").order_by("pk"))

    # Self-heal: make sure every invoice has a line item for every active code,
    # in case a category was added to the county after this invoice was created.
    for invoice in invoices:
        for code in county_codes:
            InvoiceLineItem.objects.get_or_create(invoice=invoice, code=code, defaults={"amount": Decimal("0.00")})

    if request.method == "POST":
        if not is_editable:
            raise PermissionDenied("This week is no longer editable.")

        save_invoice_fields(request, week, access, county_codes, invoices)

        if week.status == 0:
            return redirect("invoices_recap")
        else:
            return redirect("invoices_recap_week", week_id=week.pk)

    line_items_by_invoice = {}
    for li in InvoiceLineItem.objects.filter(invoice__in=invoices):
        line_items_by_invoice.setdefault(li.invoice_id, {})[li.code_id] = li.amount

    sheet_totals = {code.pk: Decimal("0.00") for code in county_codes}
    sheet_tax_total = Decimal("0.00")

    grid_rows = []
    for invoice in invoices:
        amounts = line_items_by_invoice.get(invoice.pk, {})

        food_cells = []
        row_food_total = Decimal("0.00")
        for code in food_codes:
            amt = amounts.get(code.pk, Decimal("0.00"))
            food_cells.append({"code_id": code.pk, "amount": amt})
            row_food_total += amt
            sheet_totals[code.pk] += amt

        nonfood_cells = []
        row_nonfood_total = Decimal("0.00")
        for code in nonfood_codes:
            amt = amounts.get(code.pk, Decimal("0.00"))
            nonfood_cells.append({"code_id": code.pk, "amount": amt})
            row_nonfood_total += amt
            sheet_totals[code.pk] += amt
        row_nonfood_total += invoice.tax
        sheet_tax_total += invoice.tax

        row_all_total = row_food_total + row_nonfood_total

        grid_rows.append({
            "invoice_id": invoice.pk,
            "vendor_name": invoice.vendor.vendor_name if invoice.vendor else "",
            "invoice_number": invoice.invoice_number,
            "food_cells": food_cells,
            "nonfood_cells": nonfood_cells,
            "tax": invoice.tax,
            "food_total": str(round_cents(row_food_total)),
            "nonfood_total": str(round_cents(row_nonfood_total)),
            "all_total": str(round_cents(row_all_total)),
        })

    sheet_food_total = sum((sheet_totals[c.pk] for c in food_codes), Decimal("0.00"))
    sheet_nonfood_total = sum((sheet_totals[c.pk] for c in nonfood_codes), Decimal("0.00")) + sheet_tax_total
    sheet_all_total = sheet_food_total + sheet_nonfood_total

    previous_week = Week.objects.filter(
        county=county, end_date__lt=week.end_date
    ).order_by("-end_date").first()
    beginning_by_code = totals_by_code(county, previous_week)
    ending_by_code = totals_by_code(county, week)

    beginning_food_total = sum((beginning_by_code.get(c.pk, {}).get("total") or Decimal("0.00") for c in food_codes), Decimal("0.00"))
    beginning_nonfood_total = sum((beginning_by_code.get(c.pk, {}).get("total") or Decimal("0.00") for c in nonfood_codes), Decimal("0.00"))
    beginning_all_total = beginning_food_total + beginning_nonfood_total

    ending_food_total = sum((ending_by_code.get(c.pk, {}).get("total") or Decimal("0.00") for c in food_codes), Decimal("0.00"))
    ending_nonfood_total = sum((ending_by_code.get(c.pk, {}).get("total") or Decimal("0.00") for c in nonfood_codes), Decimal("0.00"))
    ending_all_total = ending_food_total + ending_nonfood_total

    # Tax has no beginning/ending inventory concept — it only ever gets summed
    # once, in the Sheet Total row itself. These two derived rows use the
    # category-only nonfood sum (sheet_totals), NOT sheet_nonfood_total, which
    # deliberately includes tax for the Sheet Total row's own display.
    sheet_nonfood_excl_tax = sum((sheet_totals[c.pk] for c in nonfood_codes), Decimal("0.00"))

    total_sheet_and_beginning_food = sheet_food_total + beginning_food_total
    total_sheet_and_beginning_nonfood = sheet_nonfood_excl_tax + beginning_nonfood_total
    total_sheet_and_beginning_all = total_sheet_and_beginning_food + total_sheet_and_beginning_nonfood

    cost_for_week_food = sheet_food_total + beginning_food_total - ending_food_total
    cost_for_week_nonfood = sheet_nonfood_excl_tax + beginning_nonfood_total - ending_nonfood_total
    cost_for_week_all = cost_for_week_food + cost_for_week_nonfood

    # Annotate each FoodCode with its sheet/beginning/ending/cost figures directly —
    # avoids Django templates' lack of variable-key dict lookup, and food_codes/
    # nonfood_codes already reference these same objects, so this covers both.
    for code in county_codes:
        sheet_total = sheet_totals[code.pk]
        beginning = beginning_by_code.get(code.pk, {}).get("total") or Decimal("0.00")
        ending = ending_by_code.get(code.pk, {}).get("total") or Decimal("0.00")
        code.sheet_total = str(round_cents(sheet_total))
        code.beginning = str(round_cents(beginning))
        code.ending = str(round_cents(ending))
        code.total_sheet_and_beginning = str(round_cents(sheet_total + beginning))
        code.cost_for_week = str(round_cents(sheet_total + beginning - ending))
        # Exact (unrounded) values for the JS live-recalc to key off of.
        code.beginning_exact = str(beginning)
        code.ending_exact = str(ending)

    signoff = WeeklySignoff.objects.filter(week=week).select_related("manager").first()
    can_sign = hasattr(request.user, "manager_profile")
    vendor_options = Vendor.objects.filter(is_active=True)

    return render(request, "inventory_system/invoices_recap.html", {
        "county": county,
        "week": week,
        "food_codes": food_codes,
        "nonfood_codes": nonfood_codes,
        "grid_rows": grid_rows,
        "sheet_tax_total": str(round_cents(sheet_tax_total)),
        "sheet_food_total": str(round_cents(sheet_food_total)),
        "sheet_nonfood_total": str(round_cents(sheet_nonfood_total)),
        "sheet_all_total": str(round_cents(sheet_all_total)),
        "beginning_food_total": str(round_cents(beginning_food_total)),
        "beginning_nonfood_total": str(round_cents(beginning_nonfood_total)),
        "beginning_all_total": str(round_cents(beginning_all_total)),
        "beginning_food_total_exact": str(beginning_food_total),
        "beginning_nonfood_total_exact": str(beginning_nonfood_total),
        "ending_food_total": str(round_cents(ending_food_total)),
        "ending_nonfood_total": str(round_cents(ending_nonfood_total)),
        "ending_all_total": str(round_cents(ending_all_total)),
        "ending_food_total_exact": str(ending_food_total),
        "ending_nonfood_total_exact": str(ending_nonfood_total),
        "total_sheet_and_beginning_food": str(round_cents(total_sheet_and_beginning_food)),
        "total_sheet_and_beginning_nonfood": str(round_cents(total_sheet_and_beginning_nonfood)),
        "total_sheet_and_beginning_all": str(round_cents(total_sheet_and_beginning_all)),
        "cost_for_week_food": str(round_cents(cost_for_week_food)),
        "cost_for_week_nonfood": str(round_cents(cost_for_week_nonfood)),
        "cost_for_week_all": str(round_cents(cost_for_week_all)),
        "is_editable": is_editable,
        "vendor_options": vendor_options,
        "signoff": signoff,
        "can_sign": can_sign,
        "active_report_tab": "invoices_recap",
    })


@login_required
@require_POST
def add_invoice(request):
    county = resolve_county(request)
    week = resolve_week(county, request.POST.get("week_id"))

    access = get_user_access(request.user)
    is_editable = is_week_editable(week, access)
    if not is_editable:
        raise PermissionDenied("This week is no longer editable.")

    county_codes = list(FoodCode.objects.filter(
        pk__in=CountyCategory.objects.filter(county=county, is_active=True).values_list("code_id", flat=True)
    ).distinct())

    existing_invoices = list(Invoice.objects.filter(week=week).select_related("vendor"))
    save_invoice_fields(request, week, access, county_codes, existing_invoices)

    vendor_name = request.POST.get("vendor_name", "").strip()
    if not vendor_name:
        messages.error(request, "Vendor name is required.")
    else:
        vendor = Vendor.get_or_create_matching(vendor_name)
        invoice_number = request.POST.get("invoice_number", "").strip()

        invoice = Invoice.objects.create(
            week=week, vendor=vendor, invoice_number=invoice_number, tax=Decimal("0.00")
        )

        for code in county_codes:
            InvoiceLineItem.objects.get_or_create(invoice=invoice, code=code, defaults={"amount": Decimal("0.00")})

    if week.status == 0:
        return redirect("invoices_recap")
    else:
        return redirect("invoices_recap_week", week_id=week.pk)


@login_required
@require_POST
def delete_invoice(request, invoice_id):
    county = resolve_county(request)
    invoice = get_object_or_404(Invoice, pk=invoice_id, week__county=county)
    week = invoice.week

    access = get_user_access(request.user)
    is_editable = is_week_editable(week, access)
    if not is_editable:
        raise PermissionDenied("This week is no longer editable.")

    county_codes = list(FoodCode.objects.filter(
        pk__in=CountyCategory.objects.filter(county=county, is_active=True).values_list("code_id", flat=True)
    ).distinct())
    other_invoices = list(Invoice.objects.filter(week=week).exclude(pk=invoice.pk).select_related("vendor"))
    save_invoice_fields(request, week, access, county_codes, other_invoices)

    InvoiceLineItem.objects.filter(invoice=invoice).delete()
    invoice.delete()

    if week.status == 0:
        return redirect("invoices_recap")
    else:
        return redirect("invoices_recap_week", week_id=week.pk)


@login_required
def wor(request, week_id=None):
    access = get_user_access(request.user)
    county = resolve_county(request)
    week = resolve_week(county, week_id)

    payroll_editable = access.role in ("manager", "developer") and is_week_editable(week, access)

    # --- Cost summary (same formulas as Weekly Invoices Recap's bottom section) ---
    previous_week = Week.objects.filter(
        county=county, end_date__lt=week.end_date
    ).order_by("-end_date").first()
    beginning_by_code = totals_by_code(county, previous_week)
    ending_by_code = totals_by_code(county, week)

    county_codes = list(FoodCode.objects.filter(
        pk__in=CountyCategory.objects.filter(county=county, is_active=True).values_list("code_id", flat=True)
    ).distinct().order_by("code_number"))
    food_codes = [c for c in county_codes if c.code_number < FOOD_CODE_CEILING]
    nonfood_codes = [c for c in county_codes if c.code_number >= FOOD_CODE_CEILING]

    sheet_by_code = {
        row["code_id"]: to_decimal(row["total"])
        for row in InvoiceLineItem.objects.filter(invoice__week=week).values("code_id").annotate(total=Sum("amount"))
    }
    sheet_tax_total = to_decimal(Invoice.objects.filter(week=week).aggregate(total=Sum("tax"))["total"]) or Decimal("0.00")

    cost_for_week_exact_by_code = {}
    for code in county_codes:
        sheet_total = sheet_by_code.get(code.pk) or Decimal("0.00")
        beginning = beginning_by_code.get(code.pk, {}).get("total") or Decimal("0.00")
        ending = ending_by_code.get(code.pk, {}).get("total") or Decimal("0.00")
        cost_for_week = sheet_total + beginning - ending
        cost_for_week_exact_by_code[code.pk] = cost_for_week
        code.sheet_total = str(round_cents(sheet_total))
        code.beginning = str(round_cents(beginning))
        code.ending = str(round_cents(ending))
        code.cost_for_week = str(round_cents(cost_for_week))

    sheet_food_total = sum((sheet_by_code.get(c.pk) or Decimal("0.00") for c in food_codes), Decimal("0.00"))
    sheet_nonfood_total = sum((sheet_by_code.get(c.pk) or Decimal("0.00") for c in nonfood_codes), Decimal("0.00"))
    beginning_food_total = sum((beginning_by_code.get(c.pk, {}).get("total") or Decimal("0.00") for c in food_codes), Decimal("0.00"))
    beginning_nonfood_total = sum((beginning_by_code.get(c.pk, {}).get("total") or Decimal("0.00") for c in nonfood_codes), Decimal("0.00"))
    ending_food_total = sum((ending_by_code.get(c.pk, {}).get("total") or Decimal("0.00") for c in food_codes), Decimal("0.00"))
    ending_nonfood_total = sum((ending_by_code.get(c.pk, {}).get("total") or Decimal("0.00") for c in nonfood_codes), Decimal("0.00"))

    cost_for_week_food = sheet_food_total + beginning_food_total - ending_food_total
    cost_for_week_nonfood = sheet_nonfood_total + beginning_nonfood_total - ending_nonfood_total
    cost_for_week_all = cost_for_week_food + cost_for_week_nonfood

    # --- Daily Sales (read-only reference — editing happens on the Daily Sales page itself) ---
    county_meals = list(
        CountyMeal.objects.filter(county=county, is_active=True).select_related("meal").order_by("pk")
    )
    dates = [week.end_date - timedelta(days=6 - i) for i in range(7)]
    sales = DailySale.objects.filter(week=week, county_meal__in=county_meals)
    sales_by_date_meal = {(s.sale_date, s.county_meal_id): s for s in sales}

    meal_totals = [0] * len(county_meals)
    daily_rows = []
    grand_total_meals = 0
    for sale_date in dates:
        cells = []
        row_total = 0
        for idx, cm in enumerate(county_meals):
            sale = sales_by_date_meal.get((sale_date, cm.pk))
            count = sale.sale_count if sale else 0
            cells.append(count)
            row_total += count
            meal_totals[idx] += count
        grand_total_meals += row_total
        daily_rows.append({"date": sale_date, "cells": cells, "row_total": row_total})

    meal_totals_display = [
        {"meal_name": cm.meal.meal_name, "total": total} for cm, total in zip(county_meals, meal_totals)
    ]

    # --- Cents per category / Food Cost for the Week / Weeks of Food on Hand ---
    def safe_div(numerator, denominator):
        if not denominator:
            return Decimal("0.00")
        return numerator / denominator

    for code in county_codes:
        code.cents_per_category = str(round_to(safe_div(cost_for_week_exact_by_code[code.pk], grand_total_meals), 3))

    food_cost_for_week = round_to(safe_div(cost_for_week_food, grand_total_meals), 3)
    tax_cost_for_week_cents = round_to(safe_div(sheet_tax_total, grand_total_meals), 3)
    nonfood_cost_for_week_cents = round_to(safe_div(cost_for_week_nonfood, grand_total_meals), 3)
    all_cost_for_week_cents = round_to(safe_div(cost_for_week_all, grand_total_meals), 3)
    weeks_of_food_on_hand = round_to(safe_div(ending_food_total, cost_for_week_food), 2)

    # --- Weekly Payroll (manager-editable only) ---
    employees = list(Employee.objects.filter(county=county, is_active=True))
    payroll_by_employee = {}
    for employee in employees:
        payroll, _ = WeeklyPayroll.objects.get_or_create(employee=employee, week=week)
        payroll_by_employee[employee.pk] = payroll

    if request.method == "POST":
        if not payroll_editable:
            raise PermissionDenied("Payroll can only be edited by a manager, and only while the week is editable.")

        def parse_hours(field_name):
            raw = request.POST.get(field_name, "").strip()
            if raw == "":
                return Decimal("0.00")
            try:
                value = Decimal(raw)
                return value if value >= 0 else Decimal("0.00")
            except InvalidOperation:
                return Decimal("0.00")

        for employee in employees:
            payroll = payroll_by_employee[employee.pk]
            payroll.regular_hours = parse_hours(f"regular_hours_{payroll.pk}")
            payroll.overtime_hours = parse_hours(f"overtime_hours_{payroll.pk}")
            payroll.overtime_explanation = request.POST.get(f"overtime_explanation_{payroll.pk}", "").strip()
            payroll.save()

        if week.status == 0:
            return redirect("wor")
        else:
            return redirect("wor_week", week_id=week.pk)

    payroll_rows = []
    total_regular_hours = Decimal("0.00")
    total_overtime_hours = Decimal("0.00")
    for employee in employees:
        payroll = payroll_by_employee[employee.pk]
        total_regular_hours += payroll.regular_hours
        total_overtime_hours += payroll.overtime_hours
        payroll_rows.append({
            "payroll_id": payroll.pk,
            "employee_name": employee.employee_name,
            "regular_hours": payroll.regular_hours,
            "overtime_hours": payroll.overtime_hours,
            "total_hours": payroll.regular_hours + payroll.overtime_hours,
            "overtime_explanation": payroll.overtime_explanation,
        })
    total_hours_all = total_regular_hours + total_overtime_hours

    signoff = WeeklySignoff.objects.filter(week=week).select_related("manager").first()
    can_sign = hasattr(request.user, "manager_profile")

    return render(request, "inventory_system/wor.html", {
        "county": county,
        "week": week,
        "food_codes": food_codes,
        "nonfood_codes": nonfood_codes,
        "sheet_food_total": str(round_cents(sheet_food_total)),
        "sheet_nonfood_total": str(round_cents(sheet_nonfood_total)),
        "sheet_tax_total": str(round_cents(sheet_tax_total)),
        "sheet_all_total": str(round_cents(sheet_food_total + sheet_nonfood_total + sheet_tax_total)),
        "beginning_food_total": str(round_cents(beginning_food_total)),
        "beginning_nonfood_total": str(round_cents(beginning_nonfood_total)),
        "beginning_all_total": str(round_cents(beginning_food_total + beginning_nonfood_total)),
        "ending_food_total": str(round_cents(ending_food_total)),
        "ending_nonfood_total": str(round_cents(ending_nonfood_total)),
        "ending_all_total": str(round_cents(ending_food_total + ending_nonfood_total)),
        "cost_for_week_food": str(round_cents(cost_for_week_food)),
        "cost_for_week_nonfood": str(round_cents(cost_for_week_nonfood)),
        "cost_for_week_all": str(round_cents(cost_for_week_all)),
        "food_cost_for_week": str(food_cost_for_week),
        "tax_cost_for_week_cents": str(tax_cost_for_week_cents),
        "nonfood_cost_for_week_cents": str(nonfood_cost_for_week_cents),
        "all_cost_for_week_cents": str(all_cost_for_week_cents),
        "weeks_of_food_on_hand": str(weeks_of_food_on_hand),
        "county_meals": county_meals,
        "daily_rows": daily_rows,
        "meal_totals_display": meal_totals_display,
        "grand_total_meals": grand_total_meals,
        "payroll_rows": payroll_rows,
        "total_regular_hours": str(total_regular_hours),
        "total_overtime_hours": str(total_overtime_hours),
        "total_hours_all": str(total_hours_all),
        "payroll_editable": payroll_editable,
        "signoff": signoff,
        "can_sign": can_sign,
        "active_report_tab": "wor",
    })


@login_required
def inventory_landing(request):
    """Lists all weeks for the county; each links to that week's first category
    page (nav_weeks/nav_categories are already available via sidebar_context)."""
    return render(request, "inventory_system/inventory_landing.html")


@login_required
def recipes_landing(request):
    """Lists all recipe codes that have at least one recipe for this county
    (nav_recipe_codes is already available via sidebar_context)."""
    return render(request, "inventory_system/recipes_landing.html")


@login_required
def recipe_code(request, code_id):
    """Redirects to the first recipe (by recipe_number) within this code, for this county."""
    access = get_user_access(request.user)
    county = resolve_county(request)
    first = CountyRecipe.objects.filter(
        county=county, recipe__recipe_code_id=code_id
    ).order_by("recipe_number").first()
    if not first:
        raise Http404("No recipes found for this code.")
    return redirect("recipe_detail", code_id=code_id, county_recipe_id=first.pk)


@login_required
def recipe_detail(request, code_id, county_recipe_id):
    # Stub for now — the live-scaling ingredient/instructions "spreadsheet" view
    # (portions-to-prepare input, ingredient math) is the next step, not built yet.
    access = get_user_access(request.user)
    county = resolve_county(request)
    county_recipe = get_object_or_404(
        CountyRecipe, pk=county_recipe_id, county=county, recipe__recipe_code_id=code_id
    )
    return render(request, "inventory_system/recipe_detail.html", {
        "county_recipe": county_recipe,
    })