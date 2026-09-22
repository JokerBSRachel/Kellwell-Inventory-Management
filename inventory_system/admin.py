from django.contrib import admin
from django import forms

from inventory_system.services import ensure_initial_weeks
from .models import (
    State, Region, Manager, County, Employee, Week,
    WeeklyPayroll, WeeklySignoff, Item, FoodCode,
    CountyCategory, CountyItem, Inventory, Invoice,
    InvoiceLineItem, Meal, CountyMeal, DailySale, Unit, Vendor,
    RecipeCode, Recipe, RecipeIngredient, CountyRecipe,
)
from datetime import date, timedelta

def generate_week_choices():
    today = date.today()
    days_since_saturday = (today.weekday() - 5) % 7
    start_of_current_week = today - timedelta(days=days_since_saturday)
    end_of_current_week = start_of_current_week + timedelta(days=6)
    default_end = end_of_current_week + timedelta(days=7)

    choices = []
    for i in range(52):
        end = default_end - timedelta(days=7 * i)
        start = end - timedelta(days=6)
        label = f"{start.strftime('%m/%d/%y')} - {end.strftime('%m/%d/%y')}"
        choices.append((end.isoformat(), label))
    return choices


class NoDeleteAdmin(admin.ModelAdmin):
    """Base admin class: disables hard deletion, adds a 'Deactivate selected' action instead,
    and hides deactivated items from the list view by default."""
    actions = ["deactivate_selected"]

    def has_delete_permission(self, request, obj=None):
        return False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if field and hasattr(field.queryset.model, "is_active"):
            field.queryset = field.queryset.filter(is_active=True)
        return field

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="Deactivate selected items")
    def deactivate_selected(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} item(s) deactivated.")


# Transactional/record-keeping models: disable delete, but no deactivate action (no is_active field)
class NoDeleteOnlyAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if field and hasattr(field.queryset.model, "is_active"):
            field.queryset = field.queryset.filter(is_active=True)
        return field


class ActiveStatusFilter(admin.SimpleListFilter):
    title = "status"
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return (
            ("active", "Active only"),
            ("inactive", "Inactive only"),
            ("all", "All"),
        )

    def queryset(self, request, queryset):
        if self.value() == "inactive":
            return queryset.filter(is_active=False)
        if self.value() == "all":
            return queryset
        return queryset.filter(is_active=True)  # default: active only

    def choices(self, changelist):
        # Skip Django's automatic "All" link; only show our own three explicit options
        for lookup, title in self.lookup_choices:
            yield {
                "selected": self.value() == lookup or (self.value() is None and lookup == "active"),
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": title,
            }


class CountyAdminForm(forms.ModelForm):
    starting_week = forms.ChoiceField(
        choices=[],
        required=False,
        label="Select starting week",
        help_text="Select the first week of recorded inventory for the new county.",
    )
    template_county = forms.ModelChoiceField(
        queryset=County.objects.filter(is_active=True),
        required=False,
        label="Use county template?",
        help_text="Optionally copy categories, meals, and items from an existing county. If you select a template, click \"Save and continue editing\" to see the copied categories and meals.",
    )

    class Meta:
        model = County
        exclude = ["tracking_start_date"]  # replaced by the starting_week dropdown

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["starting_week"].choices = generate_week_choices()


class CountyItemInlineForm(forms.ModelForm):
    # starting_price = forms.DecimalField(max_digits=6, decimal_places=2, required=False, initial=0)
    # starting_received_1 = forms.DecimalField(max_digits=6, decimal_places=2, required=False, initial=0)
    # starting_received_2 = forms.DecimalField(max_digits=6, decimal_places=2, required=False, initial=0)
    # starting_inventory = forms.DecimalField(max_digits=6, decimal_places=2, required=False, initial=0)

    class Meta:
        model = CountyItem
        fields = ["item", "unit","is_active"]


class EmployeeInline(admin.TabularInline):
    model = Employee
    extra = 1
    fields = ["employee_name", "is_active"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if field and hasattr(field.queryset.model, "is_active"):
            field.queryset = field.queryset.filter(is_active=True)
        return field


class CountyCategoryInline(admin.TabularInline):
    model = CountyCategory
    extra = 1  # shows 1 blank row for adding a new one

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if field and hasattr(field.queryset.model, "is_active"):
            field.queryset = field.queryset.filter(is_active=True)
        return field


class CountyMealInline(admin.TabularInline):
    model = CountyMeal
    extra = 1

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if field and hasattr(field.queryset.model, "is_active"):
            field.queryset = field.queryset.filter(is_active=True)
        return field


class CountyItemInline(admin.TabularInline):
    model = CountyItem
    form = CountyItemInlineForm
    extra = 1

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if field and hasattr(field.queryset.model, "is_active"):
            field.queryset = field.queryset.filter(is_active=True)
        return field


@admin.register(County)
class CountyAdmin(NoDeleteAdmin):
    form = CountyAdminForm
    list_display = ("county_name", "state", "region", "manager", "is_active")
    list_filter = ("state", "region", ActiveStatusFilter)
    search_fields = ("county_name",)

    @admin.action(description="Deactivate selected items")
    def deactivate_selected(self, request, queryset):
        updated = queryset.update(is_active=False, login_user=None)
        self.message_user(request, f"{updated} item(s) deactivated.")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "login_user":
            taken_ids = list(Manager.objects.exclude(user__isnull=True).values_list("user_id", flat=True))
            taken_ids += list(County.objects.exclude(pk=request.resolver_match.kwargs.get("object_id")).exclude(login_user__isnull=True).values_list("login_user_id", flat=True))
            field.queryset = field.queryset.exclude(pk__in=taken_ids)
        return field

    inlines = [EmployeeInline, CountyCategoryInline, CountyMealInline]

    def get_fields(self, request, obj=None):
        fields = ["county_name", "state", "region", "manager", "login_user", "is_template", "is_active"]
        if obj is None:
            fields += ["starting_week", "template_county"]
        return fields
    
    def save_model(self, request, obj, form, change):
        if change and not obj.is_active:
            obj.login_user = None
        if not change:  # only applies when creating a new county
            starting_week_str = form.cleaned_data.get("starting_week")
            if starting_week_str:
                obj.tracking_start_date = date.fromisoformat(starting_week_str)

        super().save_model(request, obj, form, change)

        if not change:
            template = form.cleaned_data.get("template_county")
            if template:
                self.copy_from_template(obj, template)

    def copy_from_template(self, new_county, template_county):
        category_map = {}
        for old_category in CountyCategory.objects.filter(county=template_county):
            new_category = CountyCategory.objects.create(
                county=new_county,
                code=old_category.code,
                subcategory_id=old_category.subcategory_id,
                is_active=old_category.is_active,
            )
            category_map[old_category.id] = new_category

        for old_meal in CountyMeal.objects.filter(county=template_county):
            CountyMeal.objects.create(
                county=new_county,
                meal=old_meal.meal,
                is_active=old_meal.is_active,
            )

        initial_week, first_week = ensure_initial_weeks(new_county)

        for old_item in CountyItem.objects.filter(category__county=template_county).order_by("pk"):
            new_category = category_map.get(old_item.category_id)
            if not new_category:
                continue
            new_item = CountyItem.objects.create(
                item=old_item.item, category=new_category,
                display_name=old_item.display_name, unit=old_item.unit, is_active=old_item.is_active,
            )

            if initial_week:
                old_initial = Inventory.objects.filter(
                    county_item=old_item, week__is_initial=True
                ).first()
                Inventory.objects.create(
                    county_item=new_item, week=initial_week,
                    end_price=old_initial.end_price if old_initial else 0,
                    end_received_1=0, end_received_2=0, end_inventory=0,
                )
                Inventory.objects.create(
                    county_item=new_item, week=first_week,
                    end_price=0, end_received_1=0, end_received_2=0, end_inventory=0,
                )


@admin.register(CountyCategory)
class CountyCategoryAdmin(NoDeleteAdmin):
    list_display = ("county", "code", "subcategory_id", "is_active")
    list_filter = ("county", "code", ActiveStatusFilter)
    inlines = [CountyItemInline]

    def save_formset(self, request, form, formset, change):
        if formset.model == CountyItem:
            formset.new_objects = []
            formset.changed_objects = []
            formset.deleted_objects = []

            for inline_form in formset.deleted_forms:
                if inline_form.instance.pk:
                    formset.deleted_objects.append(inline_form.instance)
                    inline_form.instance.delete()

            for inline_form in formset.forms:
                if inline_form in formset.deleted_forms:
                    continue
                if not inline_form.has_changed() and inline_form.instance.pk is None:
                    continue
                is_new = inline_form.instance.pk is None
                instance = inline_form.save()
                self.create_initial_inventory(instance)
                if is_new:
                    formset.new_objects.append(instance)
                else:
                    formset.changed_objects.append((instance, inline_form.changed_data))
        else:
            formset.save()

    def create_initial_inventory(self, county_item):
        county = county_item.category.county
        initial_week, first_week = ensure_initial_weeks(county)
        if not initial_week:
            return

        for week in (initial_week, first_week):
            if not Inventory.objects.filter(county_item=county_item, week=week).exists():
                Inventory.objects.create(
                    county_item=county_item, week=week,
                    end_price=0, end_received_1=0, end_received_2=0, end_inventory=0,
                )
    

@admin.register(State)
class StateAdmin(NoDeleteAdmin):
    list_display = ("state_name", "is_active")
    search_fields = ("state_name",)


@admin.register(Region)
class RegionAdmin(NoDeleteAdmin):
    list_display = ("region_name", "is_active")


@admin.register(Manager)
class ManagerAdmin(NoDeleteAdmin):
    list_display = ("manager_name", "manager_title", "is_active")
    search_fields = ("manager_name",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "user":
            taken_ids = list(Manager.objects.exclude(pk=request.resolver_match.kwargs.get("object_id")).exclude(user__isnull=True).values_list("user_id", flat=True))
            taken_ids += list(County.objects.exclude(login_user__isnull=True).values_list("login_user_id", flat=True))
            field.queryset = field.queryset.exclude(pk__in=taken_ids)
        return field


@admin.register(Employee)
class EmployeeAdmin(NoDeleteAdmin):
    list_display = ("employee_name", "county", "is_active")
    list_filter = ("county", ActiveStatusFilter)
    search_fields = ("employee_name",)


@admin.register(Item)
class ItemAdmin(NoDeleteAdmin):
    list_display = ("item_name", "is_active")
    search_fields = ("item_name",)


@admin.register(FoodCode)
class FoodCodeAdmin(NoDeleteAdmin):
    list_display = ("code_number", "code_name", "is_active")
    search_fields = ("code_name",)


@admin.register(Unit)
class UnitAdmin(NoDeleteAdmin):
    list_display = ("unit_name", "is_active")
    search_fields = ("unit_name",)


@admin.register(Vendor)
class VendorAdmin(NoDeleteAdmin):
    list_display = ("vendor_name", "is_active")
    search_fields = ("vendor_name",)


@admin.register(Meal)
class MealAdmin(NoDeleteAdmin):
    list_display = ("meal_name", "is_active")


@admin.register(CountyMeal)
class CountyMealAdmin(NoDeleteAdmin):
    list_display = ("county", "meal", "is_active")
    list_filter = ("county", ActiveStatusFilter)


@admin.register(CountyItem)
class CountyItemAdmin(NoDeleteAdmin):
    list_display = ("item", "display_name", "unit", "category", "is_active")
    list_filter = ("category__county", ActiveStatusFilter)
    search_fields = ("item__item_name", "display_name")


@admin.register(Week)
class WeekAdmin(NoDeleteOnlyAdmin):
    list_display = ("county", "end_date", "status")
    list_filter = ("county", "status")


@admin.register(Inventory)
class InventoryAdmin(NoDeleteOnlyAdmin):
    list_display = ("county_item", "week", "end_price", "end_inventory")
    list_filter = ("week",)


@admin.register(Invoice)
class InvoiceAdmin(NoDeleteOnlyAdmin):
    list_display = ("vendor", "week", "invoice_number", "tax")


@admin.register(InvoiceLineItem)
class InvoiceLineItemAdmin(NoDeleteOnlyAdmin):
    list_display = ("invoice", "code", "amount")


@admin.register(WeeklyPayroll)
class WeeklyPayrollAdmin(NoDeleteOnlyAdmin):
    list_display = ("employee", "week", "regular_hours", "overtime_hours")


@admin.register(WeeklySignoff)
class WeeklySignoffAdmin(NoDeleteOnlyAdmin):
    list_display = ("week", "manager", "signed_at")


@admin.register(DailySale)
class DailySaleAdmin(NoDeleteOnlyAdmin):
    list_display = ("county_meal", "week", "sale_date", "sale_count")
    list_filter = ("week",)


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1


@admin.register(RecipeCode)
class RecipeCodeAdmin(admin.ModelAdmin):
    list_display = ("recipe_code", "recipe_code_name")
    search_fields = ("recipe_code", "recipe_code_name")


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("recipe_name", "recipe_code", "recipe_size")
    list_filter = ("recipe_code",)
    search_fields = ("recipe_name",)
    inlines = [RecipeIngredientInline]


@admin.register(RecipeIngredient)
class RecipeIngredientAdmin(admin.ModelAdmin):
    list_display = ("ingredient_name", "recipe", "ingredient_amt", "ingredient_unit")
    list_filter = ("recipe__recipe_code",)
    search_fields = ("ingredient_name",)


@admin.register(CountyRecipe)
class CountyRecipeAdmin(admin.ModelAdmin):
    list_display = ("county", "display", "recipe_number")
    list_filter = ("county", "recipe__recipe_code")
    search_fields = ("recipe__recipe_name", "display_name")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "county":
            field.queryset = field.queryset.filter(is_active=True)
        return field