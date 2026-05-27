"""
UGo Intelligent Driver Matching Engine
=======================================
Finds the best available driver for a ride request using:
  1. Proximity filtering  — only drivers within SEARCH_RADIUS_KM
  2. Availability filter  — status must be 'available'
  3. Vehicle type filter  — driver's vehicle type must match the request
  4. Subscription check   — driver must have an active, non-exhausted plan
  5. Scoring / ranking    — nearest driver wins (tie-break: average rating)

Usage:
    from rides.matching import match_driver_for_ride
    result = match_driver_for_ride(ride)
    if result.success:
        print(result.driver_profile, result.distance_km)
    else:
        print(result.reason)
"""

from dataclasses import dataclass, field
from typing import Optional

from .utils import haversine

# ── Tuneable constants ────────────────────────────────────────────────────────
SEARCH_RADIUS_KM: float = 5.0          # Preferred radius
FALLBACK_RADIUS_KM: float = 10.0       # Maximum distance to look for a driver (as per user request)
MIN_RADIUS_KM: float = 2.0             # Inner radius
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MatchResult:
    """The outcome of one matching attempt."""
    success: bool
    driver_profile: Optional[object] = None   # rides.models.Driver instance
    distance_km: Optional[float] = None
    reason: str = ""
    candidates_checked: int = 0
    search_radius_km: float = SEARCH_RADIUS_KM


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_driver_for_ride(ride) -> MatchResult:
    """
    Main entry point.  Finds the optimal driver for `ride` and mutually
    updates the ride + driver profile in the database if successful.

    Parameters
    ----------
    ride : rides.models.Ride
        A Ride instance that has already been saved (needs pk, lat/lng,
        vehicle_type).

    Returns
    -------
    MatchResult
    """
    # Lazy import to avoid circular dependency
    from .models import Driver, DriverSubscription
    from django.utils import timezone

    user_lat = ride.pickup_lat
    user_lng = ride.pickup_lng
    requested_vehicle = ride.vehicle_type  # e.g. 'sedan'

    # ── Candidate pool: available drivers with matching vehicle type ───────
    candidates = Driver.objects.filter(
        status='available',
        is_available=True,
        vehicle_type=requested_vehicle,
        user__is_active=True
    ).select_related('user', 'user__subscription', 'user__subscription__plan')

    scored: list[tuple[float, float, object]] = []  # (distance, -rating, driver)

    for driver_profile in candidates:
        # 1. Distance check (use expanded fallback radius)
        distance = haversine(
            user_lat, user_lng,
            driver_profile.latitude, driver_profile.longitude,
        )
        if distance > FALLBACK_RADIUS_KM:
            continue

        # 2. Subscription check
        try:
            sub = driver_profile.user.subscription
            can_accept, _ = sub.can_accept_ride()
            if not can_accept:
                continue
        except DriverSubscription.DoesNotExist:
            # Driver has no subscription → skip
            continue

        # Score: primary = distance (asc), secondary = avg rating (desc)
        scored.append((distance, -driver_profile.average_rating, driver_profile))

    total_checked = len(candidates)

    if not scored:
        return MatchResult(
            success=False,
            reason=(
                f"No available {requested_vehicle.title()} driver found "
                f"within {FALLBACK_RADIUS_KM} km."
            ),
            candidates_checked=total_checked,
        )

    # Sort: nearest first, then highest rated
    scored.sort(key=lambda x: (x[0], x[1]))

    best_distance, _, best_driver = scored[0]
    search_radius = SEARCH_RADIUS_KM if best_distance <= SEARCH_RADIUS_KM else FALLBACK_RADIUS_KM

    # ── Assign the driver ─────────────────────────────────────────────────
    best_driver.set_busy()

    ride.driver = best_driver.user
    ride.status = 'requested'
    ride.matched_distance_km = round(best_distance, 2)
    ride.otp = None  # OTP generated only after driver accepts
    ride.save(update_fields=[
        'driver', 'status', 'matched_distance_km', 'otp'
    ])

    return MatchResult(
        success=True,
        driver_profile=best_driver,
        distance_km=round(best_distance, 2),
        reason="Driver matched successfully.",
        candidates_checked=total_checked,
        search_radius_km=search_radius,
    )


def get_nearby_drivers(pickup_lat: float, pickup_lng: float,
                       vehicle_type: str = None,
                       radius_km: float = SEARCH_RADIUS_KM) -> list[dict]:
    """
    Return a ranked list of nearby available drivers (used by the user UI
    to show available drivers before requesting a ride).
    """
    from .models import Driver, DriverSubscription

    qs = Driver.objects.filter(
        status='available', 
        is_available=True,
        user__is_active=True
    ).select_related('user', 'user__subscription', 'user__subscription__plan')

    if vehicle_type:
        qs = qs.filter(vehicle_type=vehicle_type)

    results = []
    for dp in qs:
        # 1. Distance check
        distance = haversine(
            pickup_lat, pickup_lng, dp.latitude, dp.longitude
        )
        if distance > radius_km:
            continue

        # 2. Subscription check (don't show "ghost" drivers)
        try:
            sub = dp.user.subscription
            can_accept, _ = sub.can_accept_ride()
            if not can_accept:
                continue
        except DriverSubscription.DoesNotExist:
            continue

        results.append({
            'driver_profile': dp,
            'user': dp.user,
            'distance_km': round(distance, 2),
            'vehicle_type': dp.get_vehicle_type_display(),
            'status': dp.get_status_display(),
            'avg_rating': dp.average_rating,
        })

    results.sort(key=lambda x: (x['distance_km'], -x['avg_rating']))
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_otp() -> str:
    import random
    return str(random.randint(1000, 9999))
