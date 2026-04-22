"""
HealthRide AI — Part 2b: Daily Schedule AI
Full-day schedule generation, all 3 optimization modes,
conflict detection, capacity planning, and unassigned sidebar.
"""

from typing import Optional
from datetime import datetime, timedelta

from models import (
    Trip, Driver,
    TripStatus, DriverStatus, VehicleType, OptimizationMode
)
from live_dispatch_ai import GeoUtils, DriverMatcher, DriverScorer


# ─────────────────────────────────────────
# Optimization Mode Rules
# ─────────────────────────────────────────

class OptimizationModeConfig:
    """Defines per-mode scheduling constraints."""

    from dataclasses import dataclass

    @dataclass
    class ModeRules:
        max_trips_per_driver:   int
        break_interval_trips:   int
        break_duration_min:     int
        buffer_between_trips:   int

    RULES = {
        OptimizationMode.EFFICIENT: ModeRules(
            max_trips_per_driver=10,
            break_interval_trips=10,
            break_duration_min=0,
            buffer_between_trips=5,
        ),
        OptimizationMode.BALANCED: ModeRules(
            max_trips_per_driver=7,
            break_interval_trips=4,
            break_duration_min=20,
            buffer_between_trips=10,
        ),
        OptimizationMode.RELAXED: ModeRules(
            max_trips_per_driver=5,
            break_interval_trips=3,
            break_duration_min=30,
            buffer_between_trips=20,
        ),
    }

    @classmethod
    def get(cls, mode: OptimizationMode):
        return cls.RULES[mode]


# ─────────────────────────────────────────
# Schedule Entry
# ─────────────────────────────────────────

class ScheduleEntry:
    """One driver-trip block on the dispatch board."""

    def __init__(self, trip: Trip, driver: Driver, route: dict):
        self.trip       = trip
        self.driver     = driver
        self.route      = route
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
# Schedule Optimizer (all 3 modes)
# ─────────────────────────────────────────

class ScheduleOptimizer:
    """
    Generates the full optimized day schedule.
    Supports Efficient / Balanced / Relaxed modes.
    Appointment times are always non-negotiable.
    """

    def __init__(self, matcher: DriverMatcher, mode: OptimizationMode = OptimizationMode.EFFICIENT):
        self.matcher = matcher
        self.mode    = mode

    def generate(self, trips: list[Trip], drivers: list[Driver]) -> list[ScheduleEntry]:
        rules           = OptimizationModeConfig.get(self.mode)
        sorted_trips    = self._sort_by_priority(trips)
        driver_pool     = {d.id: d for d in drivers if d.status != DriverStatus.OFFLINE}
        schedule:               list[ScheduleEntry]         = []
        driver_schedule:        dict[str, list[ScheduleEntry]] = {d: [] for d in driver_pool}
        driver_trip_count:      dict[str, int]              = {d: 0 for d in driver_pool}
        driver_next_available:  dict[str, datetime]         = {d: datetime.now() for d in driver_pool}

        for trip in sorted_trips:
            best = self._pick_driver(
                trip, list(driver_pool.values()),
                driver_schedule, driver_trip_count,
                driver_next_available, rules
            )
            if best:
                route = self._estimate_route(best, trip)
                entry = ScheduleEntry(trip, best, route)
                schedule.append(entry)
                driver_schedule[best.id].append(entry)
                driver_trip_count[best.id] += 1

                free_at = entry.end_time + timedelta(minutes=rules.buffer_between_trips)
                if rules.break_duration_min > 0 and driver_trip_count[best.id] % rules.break_interval_trips == 0:
                    free_at += timedelta(minutes=rules.break_duration_min)
                driver_next_available[best.id] = free_at
            else:
                trip.status = TripStatus.UNASSIGNED

        return schedule

    def _sort_by_priority(self, trips: list[Trip]) -> list[Trip]:
        return sorted(trips, key=lambda t: (
            0 if t.appointment_time else 1,
            t.appointment_time or t.pickup_time
        ))

    def _pick_driver(
        self,
        trip:                   Trip,
        drivers:                list[Driver],
        driver_schedule:        dict[str, list[ScheduleEntry]],
        driver_trip_count:      dict[str, int],
        driver_next_available:  dict[str, datetime],
        rules
    ) -> Optional[Driver]:
        eligible = [
            d for d in drivers
            if d.vehicle_type == trip.vehicle_type
            and d.status == DriverStatus.AVAILABLE
            and driver_trip_count.get(d.id, 0) < rules.max_trips_per_driver
            and driver_next_available.get(d.id, datetime.now()) <= trip.pickup_time
            and not self._has_conflict(d, trip, driver_schedule)
        ]
        if not eligible:
            return None
        return min(eligible, key=lambda d: GeoUtils.distance_km(
            d.location.lat, d.location.lng,
            trip.pickup.lat, trip.pickup.lng
        ))

    def _has_conflict(self, driver: Driver, trip: Trip, driver_schedule: dict) -> bool:
        for entry in driver_schedule.get(driver.id, []):
            if entry.start_time <= trip.pickup_time <= entry.end_time:
                return True
        return False

    def _estimate_route(self, driver: Driver, trip: Trip) -> dict:
        dist = GeoUtils.distance_km(
            driver.location.lat, driver.location.lng,
            trip.pickup.lat, trip.pickup.lng
        )
        return {"distance_km": round(dist, 2), "duration_min": round(GeoUtils.eta_minutes(dist))}


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
            entries = sorted(entries, key=lambda e: e.start_time)
            for i in range(len(entries) - 1):
                if entries[i].end_time > entries[i + 1].start_time:
                    conflicts.append({
                        "driver_id": driver_id,
                        "trip_a":    entries[i].trip.id,
                        "trip_b":    entries[i + 1].trip.id,
                        "overlap_min": round(
                            (entries[i].end_time - entries[i + 1].start_time).total_seconds() / 60
                        )
                    })
        return conflicts


# ─────────────────────────────────────────
# Capacity Planner
# ─────────────────────────────────────────

class CapacityPlanner:
    """Workload overview, overbooking alerts, and load balancing suggestions."""

    OVERLOAD_THRESHOLD = 8

    def workload_summary(self, drivers: list[Driver], trips: list[Trip]) -> list[dict]:
        summary = []
        for driver in drivers:
            assigned = [t for t in trips if t.assigned_driver_id == driver.id]
            summary.append({
                "driver_id":   driver.id,
                "driver_name": driver.name,
                "trip_count":  len(assigned),
                "overloaded":  len(assigned) >= self.OVERLOAD_THRESHOLD,
                "status":      driver.status.value,
                "utilization": round(len(assigned) / self.OVERLOAD_THRESHOLD * 100),
            })
        return summary

    def flag_overbooking(self, summary: list[dict]) -> list[dict]:
        return [s for s in summary if s["overloaded"]]

    def balance_load(self, summary: list[dict]) -> list[dict]:
        avg         = sum(s["trip_count"] for s in summary) / max(len(summary), 1)
        overloaded  = [s for s in summary if s["trip_count"] > avg * 1.3]
        underloaded = [s for s in summary if s["trip_count"] < avg * 0.7]
        suggestions = []
        for over in overloaded:
            for under in underloaded:
                suggestions.append({
                    "move_trip_from": over["driver_id"],
                    "move_trip_to":   under["driver_id"],
                    "reason": f"{over['driver_name']} has {over['trip_count']} trips vs {under['driver_name']}'s {under['trip_count']}."
                })
        return suggestions


# ─────────────────────────────────────────
# Unassigned Sidebar AI
# ─────────────────────────────────────────

class UnassignedSidebarAI:
    """
    Powers the Unassigned sidebar panel on Daily Schedule.
    Returns AI suggestion cards for each unassigned trip.
    """

    def __init__(self, matcher: DriverMatcher):
        self.matcher = matcher

    def get_suggestions(self, unassigned_trips: list[Trip], drivers: list[Driver]) -> list[dict]:
        suggestions = []
        for trip in unassigned_trips:
            result = self.matcher.find_best(trip, drivers)
            suggestions.append({
                "trip_id":                  trip.id,
                "passenger_name":           trip.passenger.name,
                "vehicle_type":             trip.vehicle_type.value,
                "pickup_time":              trip.pickup_time.strftime("%I:%M %p"),
                "pickup_address":           trip.pickup.address,
                "dropoff_address":          trip.dropoff.address,
                "ai_suggested_driver":      result["driver"].name if result else None,
                "ai_suggested_driver_id":   result["driver"].id if result else None,
                "confidence":               result["confidence"] if result else 0,
                "eta_minutes":              result["eta_minutes"] if result else None,
            })
        return suggestions


# ─────────────────────────────────────────
# Daily Stats Summary
# ─────────────────────────────────────────

class DailyStatsSummary:
    """Stat cards: Total / Completed / In Progress / Scheduled / Unassigned."""

    def compute(self, trips: list[Trip]) -> dict:
        return {
            "total":       len(trips),
            "completed":   sum(1 for t in trips if t.status == TripStatus.COMPLETED),
            "in_progress": sum(1 for t in trips if t.status == TripStatus.IN_PROGRESS),
            "scheduled":   sum(1 for t in trips if t.status == TripStatus.SCHEDULED),
            "unassigned":  sum(1 for t in trips if t.status == TripStatus.UNASSIGNED),
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
            "schedule_optimizer": ScheduleOptimizer(matcher, mode),
            "conflict_detector":  ConflictDetector(),
            "capacity_planner":   CapacityPlanner(),
            "unassigned_sidebar": UnassignedSidebarAI(matcher),
            "daily_stats":        DailyStatsSummary(),
        }