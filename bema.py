"""
HealthRide AI — Remaining AI Gaps (Final Fixes)
================================================
1. Balanced & Relaxed optimization modes — fully implemented
2. Continuous ETA recalculation polling handler
3. Manual override acknowledgment (AI state sync)
4. AI accuracy metric in analytics
"""

from datetime import datetime, timedelta
from typing import Optional, Callable
from dataclasses import dataclass, field
import threading

from models import (
    Trip, Driver, AIRecommendation,
    TripStatus, DriverStatus, OptimizationMode, MonitoringTrigger
)
from live_dispatch_ai import GeoUtils, DriverMatcher, DriverScorer
from daily_schedule_ai import ScheduleEntry, ScheduleOptimizer, ConflictDetector
from analytics import AnalyticsEngine, DispatchMetrics


# ═══════════════════════════════════════════════════════════════
# GAP 1 — Balanced & Relaxed Optimization Modes
# ═══════════════════════════════════════════════════════════════

class OptimizationModeConfig:
    """
    Defines constraints per optimization mode.
    ScheduleOptimizer reads these to adjust its behavior.
    """

    @dataclass
    class ModeRules:
        max_trips_per_driver:   int
        break_interval_trips:   int     # force a break after N trips
        break_duration_min:     int     # break length in minutes
        buffer_between_trips:   int     # minimum gap between trips (min)

    RULES = {
        OptimizationMode.EFFICIENT: ModeRules(
            max_trips_per_driver=10,
            break_interval_trips=10,    # no forced breaks
            break_duration_min=0,
            buffer_between_trips=5,
        ),
        OptimizationMode.BALANCED: ModeRules(
            max_trips_per_driver=7,
            break_interval_trips=4,     # break after every 4 trips
            break_duration_min=20,
            buffer_between_trips=10,
        ),
        OptimizationMode.RELAXED: ModeRules(
            max_trips_per_driver=5,
            break_interval_trips=3,     # break after every 3 trips
            break_duration_min=30,
            buffer_between_trips=20,
        ),
    }

    @classmethod
    def get(cls, mode: OptimizationMode) -> ModeRules:
        return cls.RULES[mode]


class FullScheduleOptimizer(ScheduleOptimizer):
    """
    Extends ScheduleOptimizer with full Balanced & Relaxed mode support.
    Replaces daily_schedule_ai.ScheduleOptimizer — drop-in upgrade.
    """

    def generate(self, trips: list[Trip], drivers: list[Driver]) -> list[ScheduleEntry]:
        rules           = OptimizationModeConfig.get(self.mode)
        sorted_trips    = self._sort_by_priority(trips)
        driver_pool     = {d.id: d for d in drivers if d.status != DriverStatus.OFFLINE}
        schedule: list[ScheduleEntry]                   = []
        driver_schedule: dict[str, list[ScheduleEntry]] = {d: [] for d in driver_pool}
        driver_trip_count: dict[str, int]               = {d: 0 for d in driver_pool}
        driver_next_available: dict[str, datetime]      = {
            d: datetime.now() for d in driver_pool
        }

        for trip in sorted_trips:
            best_driver = self._pick_driver_with_rules(
                trip, list(driver_pool.values()),
                driver_schedule, driver_trip_count,
                driver_next_available, rules
            )
            if best_driver:
                route = self._estimate_route(best_driver, trip)
                entry = ScheduleEntry(trip, best_driver, route)
                schedule.append(entry)
                driver_schedule[best_driver.id].append(entry)
                driver_trip_count[best_driver.id] += 1

                # Calculate when driver is free after this trip + buffer
                free_at = entry.end_time + timedelta(minutes=rules.buffer_between_trips)

                # Inject a break if driver hits the break interval
                count = driver_trip_count[best_driver.id]
                if rules.break_duration_min > 0 and count % rules.break_interval_trips == 0:
                    free_at += timedelta(minutes=rules.break_duration_min)

                driver_next_available[best_driver.id] = free_at
            else:
                trip.status = TripStatus.UNASSIGNED

        return schedule

    def _pick_driver_with_rules(
        self,
        trip:                   Trip,
        drivers:                list[Driver],
        driver_schedule:        dict[str, list[ScheduleEntry]],
        driver_trip_count:      dict[str, int],
        driver_next_available:  dict[str, datetime],
        rules:                  OptimizationModeConfig.ModeRules
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


# ═══════════════════════════════════════════════════════════════
# GAP 2 — Continuous ETA Recalculation Polling Handler
# ═══════════════════════════════════════════════════════════════

class ETAPollingHandler:
    """
    Polls active trips at a set interval and recalculates driver ETAs.
    Fires a callback when ETA changes significantly (threshold: 3 min).
    Backend dev starts/stops this handler and provides the callback.

    Usage:
        def on_eta_update(trip_id, new_eta):
            # push to frontend via WebSocket / Django Channels
            pass

        handler = ETAPollingHandler(smart_router, on_eta_update, interval_sec=30)
        handler.start()
        # ... later ...
        handler.stop()
    """

    ETA_CHANGE_THRESHOLD_MIN = 3    # only fire callback if ETA shifts by 3+ min

    def __init__(
        self,
        smart_router,
        on_eta_update: Callable[[str, int], None],
        interval_sec: int = 30
    ):
        self.smart_router   = smart_router
        self.on_eta_update  = on_eta_update
        self.interval_sec   = interval_sec
        self._active_trips: dict[str, dict] = {}   # trip_id → {driver, destination, last_eta}
        self._running       = False
        self._thread: Optional[threading.Thread] = None

    def register_trip(self, trip_id: str, driver: Driver, destination: tuple):
        """Register a trip for live ETA tracking."""
        self._active_trips[trip_id] = {
            "driver":       driver,
            "destination":  destination,
            "last_eta":     None
        }

    def unregister_trip(self, trip_id: str):
        """Remove a completed or cancelled trip from tracking."""
        self._active_trips.pop(trip_id, None)

    def start(self):
        """Start the background polling thread."""
        self._running = True
        self._thread  = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the polling thread gracefully."""
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
                (driver.location.lat, driver.location.lng),
                destination
            )

            if last_eta is None or abs(new_eta - last_eta) >= self.ETA_CHANGE_THRESHOLD_MIN:
                data["last_eta"] = new_eta
                self.on_eta_update(trip_id, new_eta)    # notify backend → push to frontend


# ═══════════════════════════════════════════════════════════════
# GAP 3 — Manual Override Acknowledgment (AI State Sync)
# ═══════════════════════════════════════════════════════════════

@dataclass
class OverrideEvent:
    trip_id:            str
    previous_driver_id: Optional[str]
    new_driver_id:      str
    overridden_by:      str         # dispatcher user ID
    timestamp:          datetime    = field(default_factory=datetime.now)
    feedback:           Optional[str] = None


class ManualOverrideHandler:
    """
    Syncs AI internal state when a dispatcher manually overrides an assignment
    (e.g. drag-and-drop on the dispatch board).

    Backend dev calls apply_override() whenever a manual change is saved.
    AI state stays consistent — no stale recommendations after overrides.
    """

    def __init__(self, monitoring_engine):
        self.monitoring_engine  = monitoring_engine
        self.override_log:      list[OverrideEvent] = []

    def apply_override(
        self,
        trip:               Trip,
        new_driver:         Driver,
        previous_driver_id: Optional[str],
        dispatcher_id:      str,
        feedback:           Optional[str] = None
    ) -> OverrideEvent:
        """
        Called when dispatcher manually assigns/reassigns a trip.
        1. Updates trip assignment
        2. Dismisses any pending AI recommendation for this trip
        3. Logs the override for analytics and model improvement
        """
        # 1. Update trip state
        trip.assigned_driver_id = new_driver.id
        trip.status             = TripStatus.SCHEDULED

        # 2. Dismiss any pending AI recommendation for this trip
        self.monitoring_engine.dismiss(trip.id, feedback=feedback)

        # 3. Log override
        event = OverrideEvent(
            trip_id             = trip.id,
            previous_driver_id  = previous_driver_id,
            new_driver_id       = new_driver.id,
            overridden_by       = dispatcher_id,
            feedback            = feedback
        )
        self.override_log.append(event)
        return event

    def get_override_log(self) -> list[dict]:
        """Returns override history — backend stores this in PostgreSQL."""
        return [
            {
                "trip_id":              e.trip_id,
                "previous_driver_id":   e.previous_driver_id,
                "new_driver_id":        e.new_driver_id,
                "overridden_by":        e.overridden_by,
                "timestamp":            e.timestamp.isoformat(),
                "feedback":             e.feedback,
            }
            for e in self.override_log
        ]


# ═══════════════════════════════════════════════════════════════
# GAP 4 — AI Accuracy Metric
# ═══════════════════════════════════════════════════════════════

@dataclass
class AIAccuracyReport:
    total_recommendations:  int
    accepted:               int
    dismissed:              int
    overridden:             int
    accuracy_score:         float       # 0–100%
    avg_confidence:         float       # average confidence of accepted recs
    top_dismiss_triggers:   list[dict]  # which triggers get dismissed most


class AIAccuracyAnalyzer:
    """
    Measures how accurate and useful the AI recommendations actually are.
    Combines recommendation outcomes + manual override data.
    Added to AnalyticsEngine as an extension.
    """

    def analyze(
        self,
        recommendations: list[AIRecommendation],
        override_log:    list[dict]
    ) -> AIAccuracyReport:

        total       = len(recommendations)
        accepted    = [r for r in recommendations if r.accepted is True]
        dismissed   = [r for r in recommendations if r.accepted is False]
        overridden  = len(override_log)

        # Accuracy = accepted / (accepted + dismissed) — ignores pending
        decided     = len(accepted) + len(dismissed)
        accuracy    = round(len(accepted) / decided * 100, 2) if decided else 0.0

        # Average confidence of accepted recommendations
        avg_conf    = (
            round(sum(r.confidence for r in accepted) / len(accepted) * 100, 2)
            if accepted else 0.0
        )

        # Which triggers get dismissed most
        from collections import Counter
        dismiss_counts = Counter(r.trigger.value for r in dismissed)
        top_dismiss = [
            {"trigger": t, "count": c}
            for t, c in dismiss_counts.most_common(3)
        ]

        return AIAccuracyReport(
            total_recommendations   = total,
            accepted                = len(accepted),
            dismissed               = len(dismissed),
            overridden              = overridden,
            accuracy_score          = accuracy,
            avg_confidence          = avg_conf,
            top_dismiss_triggers    = top_dismiss
        )


class ExtendedAnalyticsEngine(AnalyticsEngine):
    """
    Drops in as a replacement for analytics.AnalyticsEngine.
    Adds AI accuracy to the summary output.
    """

    def __init__(self):
        self.accuracy_analyzer = AIAccuracyAnalyzer()

    def summary(
        self,
        call_logs:       list[dict],
        recommendations: list[AIRecommendation],
        trips:           list[Trip],
        override_log:    list[dict] = []
    ) -> dict:
        base            = super().summary(call_logs, recommendations, trips)
        accuracy_report = self.accuracy_analyzer.analyze(recommendations, override_log)

        base.update({
            "ai_accuracy_score":        accuracy_report.accuracy_score,
            "ai_avg_confidence":        accuracy_report.avg_confidence,
            "ai_overrides":             accuracy_report.overridden,
            "top_dismissed_triggers":   accuracy_report.top_dismiss_triggers,
        })
        return base


# ═══════════════════════════════════════════════════════════════
# Factory — all gap fixes wired together
# ═══════════════════════════════════════════════════════════════

class AIGapFixesFactory:
    """
    Backend dev calls create() to get all gap-fix components.
    Pass in the existing monitoring_engine and smart_router from LiveDispatchFactory.
    """

    @staticmethod
    def create(
        monitoring_engine,
        smart_router,
        on_eta_update:      Callable[[str, int], None],
        optimization_mode:  OptimizationMode = OptimizationMode.EFFICIENT,
        eta_interval_sec:   int = 30
    ) -> dict:
        scorer  = DriverScorer()
        matcher = DriverMatcher(scorer)
        return {
            "schedule_optimizer":   FullScheduleOptimizer(matcher, optimization_mode),
            "eta_polling_handler":  ETAPollingHandler(smart_router, on_eta_update, eta_interval_sec),
            "override_handler":     ManualOverrideHandler(monitoring_engine),
            "analytics_engine":     ExtendedAnalyticsEngine(),
        }