"""
URL configuration for kellwell_app project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from inventory_system import views as inventory_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='inventory_system/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('dashboard/', inventory_views.dashboard, name='dashboard'),
    path('inventory/weeks/', inventory_views.inventory_landing, name='inventory_landing'),
    path('inventory/', inventory_views.weekly_inventory, name='weekly_inventory'),
    path('inventory/<int:category_id>/', inventory_views.weekly_inventory, name='weekly_inventory_category'),
    path('inventory/week/<int:week_id>/<int:category_id>/', inventory_views.weekly_inventory, name='weekly_inventory_week'),
    path('inventory/delete-item/<int:inventory_id>/', inventory_views.delete_item, name='delete_item'),
    path('inventory/undo/', inventory_views.undo_last_action, name='undo_last_action'),
    path('inventory/add-item/', inventory_views.add_item, name='add_item'),
    path('inventory/roll/', inventory_views.roll_to_next_week, name='roll_to_next_week'),
    path('inventory/reorder/', inventory_views.reorder_items, name='reorder_items'),
    path('daily-sales/', inventory_views.daily_sales, name='daily_sales'),
    path('daily-sales/week/<int:week_id>/', inventory_views.daily_sales, name='daily_sales_week'),
    path('daily-sales/sign-off/<int:week_id>/', inventory_views.sign_off_week, name='sign_off_week'),
    path('totals/', inventory_views.totals, name='totals'),
    path('totals/week/<int:week_id>/', inventory_views.totals, name='totals_week'),
    path('invoices-recap/', inventory_views.invoices_recap, name='invoices_recap'),
    path('invoices-recap/week/<int:week_id>/', inventory_views.invoices_recap, name='invoices_recap_week'),
    path('invoices-recap/add/', inventory_views.add_invoice, name='add_invoice'),
    path('invoices-recap/delete/<int:invoice_id>/', inventory_views.delete_invoice, name='delete_invoice'),
    path('wor/', inventory_views.wor, name='wor'),
    path('wor/week/<int:week_id>/', inventory_views.wor, name='wor_week'),
    path('recipes/', inventory_views.recipes_landing, name='recipes'),
    path('recipes/code/<int:code_id>/', inventory_views.recipe_code, name='recipes_code'),
    path('recipes/code/<int:code_id>/recipe/<int:county_recipe_id>/', inventory_views.recipe_detail, name='recipe_detail'),
    path('recipes/recipe/<int:county_recipe_id>/save-servings/', inventory_views.save_recipe_servings, name='save_recipe_servings'),
]