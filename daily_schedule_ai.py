"""
HealthRide AI — Part 2b: Daily Schedule AI
Full-day schedule generation, optimization, conflict detection,
capacity planning, and AI suggestions panel (Unassigned sidebar).
"""

import math
from typing import Optional
from datetime import datetime, timedelta

from models import (
    Trip, Driver, AIRecommendation,
    TripStatus, DriverStatus, VehicleType,
    OptimizationMode, MonitoringTrigger
)
from live_dispatch_ai import GeoUtils, DriverMatcher, DriverScorer


# ─────────────────────────────────────────
# Schedule Entry
# ─────────────────────────────────────────

class ScheduleEntry:
    """Represents one driver-trip assignment block on the dispatch board."""

    def __init__(self, trip: Trip, driver: Driver, route: dict):
        self.trip       = trip
        self.driver     = driver
        self.route      = route             # from SmartRouter
        self.start_time = trip.pickup_time
        self.end_time   = trip.pickup_time + timedelta(minutes=route.get("duration_min", 0))

    def to_dict(self) -> dict:
        return {
            "trip_id":          self.trip.id,
            "driver_id":        self.driver.id,
            "driver_name":      self.driver.name,
            "passenger_name":   self.trip.passenger.name,
            "pickup_address":   self.trip.pickup.address,
            "dropoff_address":  self.trip.dropoff.address,
            "pickup_time":      self.start_time.strftime("%I:%M %p"),
            "dropoff_time":     self.end_time.strftime("%I:%M %p"),
            "appointment_time": self.trip.appointment_time.strftime("%I:%M %p") if self.trip.appointment_time else None,
            "vehicle_type":     self.trip.vehicle_type.value,
            "duration_min":     self.route.get("duration_min", 0),
            "status":           self.trip.status.value,
        }


# ─────────────────────────────────────────
# Schedule Optimizer
# ─────────────────────────────────────────

class ScheduleOptimizer:
    """
    Generates the full day's optimized schedule.
    Two modes: Manual (dispatcher assigns) and AI-Powered.

    Rules enforced:
    - Appointment times are NON-NEGOTIABLE — always met first.
    - Vehicle type must match requirement.
    - No double-booking a driver.
    - Workload distributed by OptimizationMode.
    """

    def __init__(self, matcher: DriverMatcher, mode: OptimizationMode = OptimizationMode.EFFICIENT):
        self.matcher    = matcher
        self.mode       = mode

    def generate(self, trips: list[Trip], drivers: list[Driver]) -> list[ScheduleEntry]:
        """AI-Powered mode — generate full optimized schedule."""
        sorted_trips    = self._sort_by_priority(trips)
        driver_pool     = {d.id: d for d in drivers if d.status != DriverStatus.OFFLINE}
        schedule        = []
        driver_schedule: dict[str, list[ScheduleEntry]] = {d: [] for d in driver_pool}

        for trip in sorted_trips:
            best_driver = self._pick_driver(trip, list(driver_pool.values()), driver_schedule)
            if best_driver:
                route = self._estimate_route(best_driver, trip)
                entry = ScheduleEntry(trip, best_driver, route)
                schedule.append(entry)
                driver_schedule[best_driver.id].append(entry)

                if self.mode == OptimizationMode.EFFICIENT:
                    best_driver.status = DriverStatus.EN_ROUTE
            else:
                # Trip stays unassigned — surfaces in sidebar
                trip.status = TripStatus.UNASSIGNED

        return schedule

    def _sort_by_priority(self, trips: list[Trip]) -> list[Trip]:
        """Appointment-bound trips always first, then by pickup time."""
        return sorted(
            trips,
            key=lambda t: (
                0 if t.appointment_time else 1,
                t.appointment_time or t.pickup_time
            )
        )

    def _pick_driver(
        self,
        trip:            Trip,
        drivers:         list[Driver],
        driver_schedule: dict[str, list[ScheduleEntry]]
    ) -> Optional[Driver]:
        """Pick best driver that is available and has no scheduling conflict."""
        eligible = [
            d for d in drivers
            if d.vehicle_type == trip.vehicle_type
            and d.status == DriverStatus.AVAILABLE
            and not self._has_conflict(d, trip, driver_schedule)
        ]
        if not eligible:
            return None
        return min(eligible, key=lambda d: GeoUtils.distance_km(
            d.location.lat, d.location.lng,
            trip.pickup.lat, trip.pickup.lng
        ))

    def _has_conflict(
        self,
        driver:          Driver,
        trip:            Trip,
        driver_schedule: dict[str, list[ScheduleEntry]]
    ) -> bool:
        """Returns True if driver already has a trip overlapping this time window."""
        for entry in driver_schedule.get(driver.id, []):
            if entry.start_time <= trip.pickup_time <= entry.end_time:
                return True
        return False

    def _estimate_route(self, driver: Driver, trip: Trip) -> dict:
        dist = GeoUtils.distance_km(
            driver.location.lat, driver.location.lng,
            trip.pickup.lat, trip.pickup.lng
        )
        return {
            "distance_km":  round(dist, 2),
            "duration_min": round(GeoUtils.eta_minutes(dist)),
        }


# ─────────────────────────────────────────
# Conflict Detector
# ─────────────────────────────────────────

class ConflictDetector:
    """Flags scheduling conflicts before the day starts."""

    def detect(self, schedule: list[ScheduleEntry]) -> list[dict]:
        driver_entries: dict[str, list[ScheduleEntry]] = {}
        for entry in schedule:
            driver_entries.setdefault(entry.driver.id, []).append(entry)

        conflicts = []
        for driver_id, entries in driver_entries.items():
            entries_sorted = sorted(entries, key=lambda e: e.start_time)
            for i in range(len(entries_sorted) - 1):
                if entries_sorted[i].end_time > entries_sorted[i + 1].start_time:
                    conflicts.append({
                        "driver_id":    driver_id,
                        "trip_a":       entries_sorted[i].trip.id,
                        "trip_b":       entries_sorted[i + 1].trip.id,
                        "overlap_min":  round(
                            (entries_sorted[i].end_time - entries_sorted[i + 1].start_time)
                            .total_seconds() / 60
                        )
                    })
        return conflicts


# ─────────────────────────────────────────
# Capacity Planner
# ─────────────────────────────────────────

class CapacityPlanner:
    """
    Workload overview across the fleet.
    Powers the driver load bar on the dispatch board.
    """

    OVERLOAD_THRESHOLD = 8      # trips per driver per day

    def workload_summary(self, drivers: list[Driver], trips: list[Trip]) -> list[dict]:
        summary = []
        for driver in drivers:
            assigned_trips = [t for t in trips if t.assigned_driver_id == driver.id]
            summary.append({
                "driver_id":    driver.id,
                "driver_name":  driver.name,
                "trip_count":   len(assigned_trips),
                "overloaded":   len(assigned_trips) >= self.OVERLOAD_THRESHOLD,
                "status":       driver.status.value,
                "utilization":  round(len(assigned_trips) / self.OVERLOAD_THRESHOLD * 100),
            })
        return summary

    def flag_overbooking(self, summary: list[dict]) -> list[dict]:
        return [s for s in summary if s["overloaded"]]

    def balance_load(self, summary: list[dict]) -> list[dict]:
        """Returns load-balancing suggestions when workload is uneven."""
        avg = sum(s["trip_count"] for s in summary) / max(len(summary), 1)
        suggestions = []
        overloaded  = [s for s in summary if s["trip_count"] > avg * 1.3]
        underloaded = [s for s in summary if s["trip_count"] < avg * 0.7]
        for over in overloaded:
            for under in underloaded:
                suggestions.append({
                    "move_trip_from":   over["driver_id"],
                    "move_trip_to":     under["driver_id"],
                    "reason":           f"{over['driver_name']} has {over['trip_count']} trips vs {under['driver_name']}'s {under['trip_count']}."
                })
        return suggestions


# ─────────────────────────────────────────
# Unassigned Sidebar AI (Daily Schedule Panel)
# ─────────────────────────────────────────

class UnassignedSidebarAI:
    """
    Powers the 'Unassigned' sidebar panel shown in the Daily Schedule UI.
    For each unassigned trip, returns the AI suggested driver with confidence %.
    Matches the UI: trip card → AI Recommendation → 'Accept AI Recommendation' button.
    """

    def __init__(self, matcher: DriverMatcher):
        self.matcher = matcher

    def get_suggestions(self, unassigned_trips: list[Trip], drivers: list[Driver]) -> list[dict]:
        """Returns AI suggestion card data for every unassigned trip."""
        suggestions = []
        for trip in unassigned_trips:
            result = self.matcher.find_best(trip, drivers)
            suggestions.append({
                "trip_id":              trip.id,
                "passenger_name":       trip.passenger.name,
                "vehicle_type":         trip.vehicle_type.value,
                "pickup_time":          trip.pickup_time.strftime("%I:%M %p"),
                "pickup_address":       trip.pickup.address,
                "dropoff_address":      trip.dropoff.address,
                "ai_suggested_driver":  result["driver"].name if result else None,
                "ai_suggested_driver_id": result["driver"].id if result else None,
                "confidence":           result["confidence"] if result else 0,
                "eta_minutes":          result["eta_minutes"] if result else None,
            })
        return suggestions


# ─────────────────────────────────────────
# Daily Stats Summary
# ─────────────────────────────────────────

class DailyStatsSummary:
    """
    Computes the top stat cards shown on the Daily Schedule page:
    Total Trips | Completed | In Progress | Scheduled | Unassigned
    """

    def compute(self, trips: list[Trip]) -> dict:
        return {
            "total":        len(trips),
            "completed":    sum(1 for t in trips if t.status == TripStatus.COMPLETED),
            "in_progress":  sum(1 for t in trips if t.status == TripStatus.IN_PROGRESS),
            "scheduled":    sum(1 for t in trips if t.status == TripStatus.SCHEDULED),
            "unassigned":   sum(1 for t in trips if t.status == TripStatus.UNASSIGNED),
        }


# ─────────────────────────────────────────
# Factory
# ─────────────────────────────────────────

class DailyScheduleFactory:
    """Single entry point for Daily Schedule AI."""

    @staticmethod
    def create(mode: OptimizationMode = OptimizationMode.EFFICIENT) -> dict:
        scorer  = DriverScorer()
        matcher = DriverMatcher(scorer)
        return {
            "schedule_optimizer":   ScheduleOptimizer(matcher, mode),
            "conflict_detector":    ConflictDetector(),
            "capacity_planner":     CapacityPlanner(),
            "unassigned_sidebar":   UnassignedSidebarAI(matcher),
            "daily_stats":          DailyStatsSummary(),
        }
