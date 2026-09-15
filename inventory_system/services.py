from .models import Week
from datetime import timedelta

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