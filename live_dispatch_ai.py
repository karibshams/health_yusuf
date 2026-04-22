"""
HealthRide AI — Part 2a: Live Map & Real-Time Dispatch
Driver scoring, matching, auto-assign, smart routing,
live monitoring, ETA polling, and manual override sync.
"""

import math
import threading
from typing import Optional, Callable
from datetime import datetime

from config import Config
from models import (
    Trip, Driver, AIRecommendation,
    TripStatus, DriverStatus, VehicleType,
    AutomationLevel, OptimizationMode, MonitoringTrigger
)


# ─────────────────────────────────────────
# Geo Utility
# ─────────────────────────────────────────

class GeoUtils:
    """Haversine distance and ETA estimation."""

    EARTH_RADIUS_KM = 6371.0

    @staticmethod
    def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        r    = GeoUtils.EARTH_RADIUS_KM
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a    = (math.sin(dlat / 2) ** 2
                + math.cos(math.radians(lat1))
                * math.cos(math.radians(lat2))
                * math.sin(dlng / 2) ** 2)
        return r * 2 * math.asin(math.sqrt(a))

    @staticmethod
    def eta_minutes(distance_km: float, avg_speed_kmh: float = 40.0) -> float:
        return (distance_km / avg_speed_kmh) * 60


# ─────────────────────────────────────────
# Driver Scorer
# ─────────────────────────────────────────

class DriverScorer:
    """
    Scores a driver against a trip (0.0 – 1.0).

    Weights:
      Proximity     40%
      Availability  25%
      Vehicle match 20%
      Performance   15%
    """

    WEIGHTS = {"proximity": 0.40, "availability": 0.25, "vehicle": 0.20, "performance": 0.15}
    MAX_DISTANCE_KM = 50.0

    AVAILABILITY_SCORES = {
        DriverStatus.AVAILABLE:         1.0,
        DriverStatus.EN_ROUTE:          0.4,
        DriverStatus.WITH_PASSENGER:    0.1,
        DriverStatus.ON_BREAK:          0.2,
        DriverStatus.OFFLINE:           0.0,
    }

    VEHICLE_UPGRADES = {
        VehicleType.SEDAN:      [VehicleType.WHEELCHAIR_VAN, VehicleType.STRETCHER],
        VehicleType.AMBULATORY: [VehicleType.WHEELCHAIR_VAN],
    }

    def score(self, driver: Driver, trip: Trip) -> float:
        return (
            self._proximity(driver, trip)   * self.WEIGHTS["proximity"]
            + self._availability(driver)    * self.WEIGHTS["availability"]
            + self._vehicle(driver, trip)   * self.WEIGHTS["vehicle"]
            + self._performance(driver)     * self.WEIGHTS["performance"]
        )

    def _proximity(self, driver: Driver, trip: Trip) -> float:
        dist = GeoUtils.distance_km(
            driver.location.lat, driver.location.lng,
            trip.pickup.lat, trip.pickup.lng
        )
        return max(0.0, 1.0 - dist / self.MAX_DISTANCE_KM)

    def _availability(self, driver: Driver) -> float:
        return self.AVAILABILITY_SCORES.get(driver.status, 0.0)

    def _vehicle(self, driver: Driver, trip: Trip) -> float:
        if driver.vehicle_type == trip.vehicle_type:
            return 1.0
        if trip.vehicle_type in self.VEHICLE_UPGRADES.get(driver.vehicle_type, []):
            return 0.7
        return 0.0

    def _performance(self, driver: Driver) -> float:
        return driver.performance_rating / 5.0


# ─────────────────────────────────────────
# Driver Matcher
# ─────────────────────────────────────────

class DriverMatcher:
    """Finds and ranks drivers for a trip. Powers the 88% Match UI card."""

    def __init__(self, scorer: DriverScorer):
        self.scorer = scorer

    def find_best(self, trip: Trip, drivers: list[Driver]) -> Optional[dict]:
        eligible = [d for d in drivers if d.status != DriverStatus.OFFLINE]
        if not eligible:
            return None
        best = max(eligible, key=lambda d: self.scorer.score(d, trip))
        dist = GeoUtils.distance_km(
            best.location.lat, best.location.lng,
            trip.pickup.lat,   trip.pickup.lng
        )
        return {
            "driver":       best,
            "confidence":   round(self.scorer.score(best, trip) * 100),
            "distance_km":  round(dist, 2),
            "eta_minutes":  round(GeoUtils.eta_minutes(dist)),
        }

    def rank_all(self, trip: Trip, drivers: list[Driver]) -> list[dict]:
        eligible = [d for d in drivers if d.status != DriverStatus.OFFLINE]
        return sorted(
            [{"driver": d, "confidence": round(self.scorer.score(d, trip) * 100)} for d in eligible],
            key=lambda x: x["confidence"], reverse=True
        )


# ─────────────────────────────────────────
# Auto Assigner
# ─────────────────────────────────────────

class AutoAssigner:
    """Single and bulk AI trip assignment."""

    def __init__(self, matcher: DriverMatcher):
        self.matcher = matcher

    def assign_single(self, trip: Trip, drivers: list[Driver]) -> Optional[dict]:
        """Powers the 'Accept AI Recommendation' button — single trip."""
        result = self.matcher.find_best(trip, drivers)
        if not result:
            return None
        return {
            "trip_id":                  trip.id,
            "recommended_driver_id":    result["driver"].id,
            "recommended_driver_name":  result["driver"].name,
            "confidence":               result["confidence"],
            "eta_minutes":              result["eta_minutes"],
            "distance_km":              result["distance_km"],
        }

    def bulk_assign(self, trips: list[Trip], drivers: list[Driver]) -> list[dict]:
        """Powers the 'AI Auto-Assign' button — all unassigned trips at once."""
        unassigned = sorted(
            [t for t in trips if t.status == TripStatus.UNASSIGNED],
            key=lambda t: t.appointment_time or t.pickup_time
        )
        driver_pool = list(drivers)
        assignments = []
        for trip in unassigned:
            result = self.matcher.find_best(trip, driver_pool)
            if result:
                assignments.append({
                    "trip_id":      trip.id,
                    "driver_id":    result["driver"].id,
                    "driver_name":  result["driver"].name,
                    "confidence":   result["confidence"],
                })
                result["driver"].status = DriverStatus.EN_ROUTE
        return assignments


# ─────────────────────────────────────────
# Smart Router
# ─────────────────────────────────────────

class SmartRouter:
    """
    Wraps Google Maps routing.
    Backend dev injects: googlemaps.Client(key=Config.GOOGLE_MAPS_API_KEY)
    Falls back to straight-line estimate if no client provided.
    """

    def __init__(self, maps_client=None):
        self.maps_client = maps_client

    def get_route(self, origin: tuple, destination: tuple, departure_time: datetime) -> dict:
        if self.maps_client:
            return self.maps_client.directions(
                origin=origin, destination=destination,
                mode="driving", departure_time=departure_time,
                traffic_model="best_guess"
            )
        dist = GeoUtils.distance_km(origin[0], origin[1], destination[0], destination[1])
        return {
            "distance_km":       round(dist, 2),
            "duration_min":      round(GeoUtils.eta_minutes(dist)),
            "traffic_delay_min": 0,
            "source":            "fallback_estimate"
        }

    def recalculate_eta(self, driver_location: tuple, destination: tuple) -> int:
        dist = GeoUtils.distance_km(
            driver_location[0], driver_location[1],
            destination[0], destination[1]
        )
        return round(GeoUtils.eta_minutes(dist))


# ─────────────────────────────────────────
# ETA Polling Handler
# ─────────────────────────────────────────

class ETAPollingHandler:
    """
    Background thread — polls active trips and recalculates driver ETAs.
    Only fires callback when ETA shifts by 3+ minutes (no noise).
    Backend dev provides on_eta_update callback → push via Django Channels.
    """

    ETA_CHANGE_THRESHOLD_MIN = 3

    def __init__(
        self,
        smart_router:   SmartRouter,
        on_eta_update:  Callable[[str, int], None],
        interval_sec:   int = 30
    ):
        self.smart_router   = smart_router
        self.on_eta_update  = on_eta_update
        self.interval_sec   = interval_sec
        self._active_trips: dict[str, dict] = {}
        self._running       = False
        self._thread:       Optional[threading.Thread] = None

    def register_trip(self, trip_id: str, driver: Driver, destination: tuple):
        self._active_trips[trip_id] = {
            "driver": driver, "destination": destination, "last_eta": None
        }

    def unregister_trip(self, trip_id: str):
        self._active_trips.pop(trip_id, None)

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self):
        import time
        while self._running:
            self._recalculate_all()
            time.sleep(self.interval_sec)

    def _recalculate_all(self):
        for trip_id, data in list(self._active_trips.items()):
            driver      = data["driver"]
            destination = data["destination"]
            last_eta    = data["last_eta"]
            new_eta = self.smart_router.recalculate_eta(
                (driver.location.lat, driver.location.lng), destination
            )
            if last_eta is None or abs(new_eta - last_eta) >= self.ETA_CHANGE_THRESHOLD_MIN:
                data["last_eta"] = new_eta
                self.on_eta_update(trip_id, new_eta)


# ─────────────────────────────────────────
# Recommendation Builder
# ─────────────────────────────────────────

class RecommendationBuilder:
    """
    Builds plain-English AIRecommendation for all 6 monitoring triggers.
    what_happened / what_to_change / why_it_helps → shown in Provider Portal.
    """

    def build(
        self,
        trigger:          MonitoringTrigger,
        affected_trip:    Trip,
        suggested_driver: Optional[Driver],
        context:          dict
    ) -> AIRecommendation:
        builders = {
            MonitoringTrigger.TRIP_CANCELLED:   self._cancelled,
            MonitoringTrigger.DRIVER_LATE:      self._driver_late,
            MonitoringTrigger.NO_SHOW:          self._no_show,
            MonitoringTrigger.LAST_MINUTE_TRIP: self._last_minute,
            MonitoringTrigger.VEHICLE_ISSUE:    self._vehicle_issue,
            MonitoringTrigger.TRAFFIC_DELAY:    self._traffic_delay,
        }
        return builders[trigger](affected_trip, suggested_driver, context)

    def _cancelled(self, trip, driver, ctx) -> AIRecommendation:
        return AIRecommendation(
            trigger=MonitoringTrigger.TRIP_CANCELLED,
            what_happened=f"Trip #{trip.id} at {trip.pickup_time.strftime('%I:%M %p')} was cancelled.",
            what_to_change=f"Reassign {driver.name} to the next nearby unassigned trip." if driver else "No reassignment available.",
            why_it_helps=f"{driver.name} is now free and {ctx.get('distance_km','?')} km from other pickups." if driver else "",
            trip_id=trip.id, suggested_driver_id=driver.id if driver else None,
            confidence=ctx.get("confidence", 0.85)
        )

    def _driver_late(self, trip, driver, ctx) -> AIRecommendation:
        return AIRecommendation(
            trigger=MonitoringTrigger.DRIVER_LATE,
            what_happened=f"Driver is running {ctx.get('delay_minutes', 0)} min late for trip #{trip.id}.",
            what_to_change=f"Reassign trip #{trip.id} to {driver.name}." if driver else "Find nearest available driver.",
            why_it_helps=f"{driver.name} is {ctx.get('distance_km','?')} km away ({ctx.get('eta_minutes','?')} min). Prevents late arrival." if driver else "",
            trip_id=trip.id, suggested_driver_id=driver.id if driver else None,
            confidence=ctx.get("confidence", 0.80)
        )

    def _no_show(self, trip, driver, ctx) -> AIRecommendation:
        return AIRecommendation(
            trigger=MonitoringTrigger.NO_SHOW,
            what_happened=f"Passenger no-show on trip #{trip.id}.",
            what_to_change=f"Assign {driver.name} to a last-minute nearby booking." if driver else "Driver is now available.",
            why_it_helps="Keeps driver productive and fills a waiting booking." if driver else "",
            trip_id=trip.id, suggested_driver_id=driver.id if driver else None,
            confidence=ctx.get("confidence", 0.75)
        )

    def _last_minute(self, trip, driver, ctx) -> AIRecommendation:
        return AIRecommendation(
            trigger=MonitoringTrigger.LAST_MINUTE_TRIP,
            what_happened=f"New last-minute trip #{trip.id} just came in.",
            what_to_change=f"Assign to {driver.name} who finishes their current trip soon." if driver else "No available driver found.",
            why_it_helps=f"{driver.name} will be free in ~{ctx.get('free_in_minutes','?')} min and is nearby." if driver else "",
            trip_id=trip.id, suggested_driver_id=driver.id if driver else None,
            confidence=ctx.get("confidence", 0.78)
        )

    def _vehicle_issue(self, trip, driver, ctx) -> AIRecommendation:
        return AIRecommendation(
            trigger=MonitoringTrigger.VEHICLE_ISSUE,
            what_happened=f"Vehicle issue reported. {ctx.get('affected_trips', 1)} trip(s) affected.",
            what_to_change="Redistribute affected trips across remaining available drivers.",
            why_it_helps="Prevents service disruption by spreading load across the fleet.",
            trip_id=trip.id, suggested_driver_id=driver.id if driver else None,
            confidence=ctx.get("confidence", 0.90)
        )

    def _traffic_delay(self, trip, driver, ctx) -> AIRecommendation:
        return AIRecommendation(
            trigger=MonitoringTrigger.TRAFFIC_DELAY,
            what_happened=f"Traffic delay of {ctx.get('delay_minutes', 0)} min on trip #{trip.id} route.",
            what_to_change="Recalculate route and notify provider.",
            why_it_helps="New route saves time and keeps appointment on track.",
            trip_id=trip.id, suggested_driver_id=None,
            confidence=ctx.get("confidence", 0.88)
        )


# ─────────────────────────────────────────
# Monitoring Engine
# ─────────────────────────────────────────

class MonitoringEngine:
    """
    Live trigger processor. Supports Manual / One-Click / Automatic modes.
    Backend dev calls process_event() whenever a trigger fires.
    """

    def __init__(
        self,
        matcher:          DriverMatcher,
        rec_builder:      RecommendationBuilder,
        automation_level: AutomationLevel = AutomationLevel.MANUAL
    ):
        self.matcher          = matcher
        self.rec_builder      = rec_builder
        self.automation_level = automation_level
        self.pending:         list[AIRecommendation] = []

    def process_event(
        self,
        trigger:       MonitoringTrigger,
        affected_trip: Trip,
        drivers:       list[Driver],
        context:       dict = {}
    ) -> AIRecommendation:
        best = self.matcher.find_best(affected_trip, drivers)
        suggested_driver = best["driver"] if best else None
        if best:
            context.update({
                "confidence":  best["confidence"] / 100,
                "distance_km": best["distance_km"],
                "eta_minutes": best["eta_minutes"],
            })
        rec = self.rec_builder.build(trigger, affected_trip, suggested_driver, context)
        if self.automation_level == AutomationLevel.AUTOMATIC:
            rec.accepted = True
        else:
            self.pending.append(rec)
        return rec

    def batch_accept(self) -> list[AIRecommendation]:
        for rec in self.pending:
            rec.accepted = True
        accepted, self.pending = list(self.pending), []
        return accepted

    def dismiss(self, trip_id: str, feedback: Optional[str] = None) -> bool:
        for rec in self.pending:
            if rec.trip_id == trip_id:
                rec.accepted = False
                self.pending.remove(rec)
                return True
        return False

    def set_automation_level(self, level: AutomationLevel):
        self.automation_level = level


# ─────────────────────────────────────────
# Manual Override Handler
# ─────────────────────────────────────────

class ManualOverrideHandler:
    """
    Syncs AI state when dispatcher manually overrides an assignment.
    Called on every drag-and-drop on the dispatch board.
    """

    def __init__(self, monitoring_engine: MonitoringEngine):
        self.monitoring_engine = monitoring_engine
        self.override_log:     list[dict] = []

    def apply_override(
        self,
        trip:               Trip,
        new_driver:         Driver,
        previous_driver_id: Optional[str],
        dispatcher_id:      str,
        feedback:           Optional[str] = None
    ) -> dict:
        trip.assigned_driver_id = new_driver.id
        trip.status             = TripStatus.SCHEDULED
        self.monitoring_engine.dismiss(trip.id, feedback=feedback)

        event = {
            "trip_id":            trip.id,
            "previous_driver_id": previous_driver_id,
            "new_driver_id":      new_driver.id,
            "overridden_by":      dispatcher_id,
            "timestamp":          datetime.now().isoformat(),
            "feedback":           feedback,
        }
        self.override_log.append(event)
        return event

    def get_override_log(self) -> list[dict]:
        return self.override_log


# ─────────────────────────────────────────
# Dispatch Notifier
# ─────────────────────────────────────────

class DispatchNotifier:
    """Builds push/SMS notification payloads. Backend dev sends via FCM/Twilio."""

    def assignment_push(self, driver: Driver, trip: Trip) -> dict:
        return {
            "type":      "push",
            "driver_id": driver.id,
            "title":     "New Trip Assigned",
            "body":      f"Trip #{trip.id} — Pickup: {trip.pickup.address} at {trip.pickup_time.strftime('%I:%M %p')}",
            "data":      {"trip_id": trip.id}
        }

    def escalation_alert(self, driver: Driver, trip: Trip) -> dict:
        return {
            "type":    "escalation",
            "driver_id": driver.id,
            "trip_id": trip.id,
            "message": f"Driver {driver.name} has not acknowledged trip #{trip.id} after {Config.ACK_TIMEOUT_MIN} min."
        }


# ─────────────────────────────────────────
# Factory
# ─────────────────────────────────────────

class LiveDispatchFactory:
    """Single entry point for Live Map & Real-Time Dispatch AI."""

    @staticmethod
    def create(
        maps_client=None,
        automation_level: AutomationLevel = AutomationLevel.MANUAL,
        on_eta_update:    Optional[Callable[[str, int], None]] = None,
        eta_interval_sec: int = 30
    ) -> dict:
        scorer      = DriverScorer()
        matcher     = DriverMatcher(scorer)
        rec_builder = RecommendationBuilder()
        router      = SmartRouter(maps_client)
        engine      = MonitoringEngine(matcher, rec_builder, automation_level)

        components = {
            "auto_assigner":      AutoAssigner(matcher),
            "monitoring_engine":  engine,
            "smart_router":       router,
            "dispatch_notifier":  DispatchNotifier(),
            "driver_matcher":     matcher,
            "override_handler":   ManualOverrideHandler(engine),
        }

        if on_eta_update:
            components["eta_polling_handler"] = ETAPollingHandler(router, on_eta_update, eta_interval_sec)

        return components