"""
HealthRide AI — Analytics Engine
Computes all AI performance metrics shown in the Provider Portal.
"""

from collections import Counter
from dataclasses import dataclass, field
from models import AIRecommendation, Trip, TripStatus


@dataclass
class CallMetrics:
    total_calls:        int = 0
    bookings_created:   int = 0
    escalations:        int = 0
    intents:            dict = field(default_factory=dict)
    escalation_reasons: list = field(default_factory=list)

    @property
    def conversion_rate(self) -> float:
        if not self.total_calls:
            return 0.0
        return round(self.bookings_created / self.total_calls * 100, 2)


@dataclass
class DispatchMetrics:
    total_recommendations: int = 0
    accepted:   int = 0
    dismissed:  int = 0

    @property
    def acceptance_rate(self) -> float:
        if not self.total_recommendations:
            return 0.0
        return round(self.accepted / self.total_recommendations * 100, 2)


class AnalyticsEngine:
    """
    Aggregates raw event data into Provider Portal metrics.
    Backend dev feeds lists of raw dicts / objects; gets metric objects back.
    """

    def call_metrics(self, call_logs: list[dict]) -> CallMetrics:
        metrics = CallMetrics(total_calls=len(call_logs))
        intent_counts = Counter()
        for log in call_logs:
            if intent := log.get("intent"):
                intent_counts[intent] += 1
            if log.get("booking_created"):
                metrics.bookings_created += 1
            if log.get("escalated"):
                metrics.escalations += 1
                if reason := log.get("escalation_reason"):
                    metrics.escalation_reasons.append(reason)
        metrics.intents = dict(intent_counts)
        return metrics

    def dispatch_metrics(self, recommendations: list[AIRecommendation]) -> DispatchMetrics:
        metrics = DispatchMetrics(total_recommendations=len(recommendations))
        for rec in recommendations:
            if rec.accepted is True:
                metrics.accepted += 1
            elif rec.accepted is False:
                metrics.dismissed += 1
        return metrics

    def on_time_rate(self, trips: list[Trip]) -> float:
        completed = [t for t in trips if t.status == TripStatus.COMPLETED]
        if not completed:
            return 0.0
        on_time = sum(1 for t in completed if t.notes != "late")
        return round(on_time / len(completed) * 100, 2)

    def summary(self, call_logs: list[dict], recommendations: list[AIRecommendation], trips: list[Trip]) -> dict:
        """Single method — returns everything the Provider Portal dashboard needs."""
        call    = self.call_metrics(call_logs)
        dispatch= self.dispatch_metrics(recommendations)
        return {
            "call_volume":          call.total_calls,
            "booking_conversion":   call.conversion_rate,
            "top_intents":          call.intents,
            "escalation_count":     call.escalations,
            "escalation_reasons":   call.escalation_reasons,
            "ai_acceptance_rate":   dispatch.acceptance_rate,
            "recommendations_total":dispatch.total_recommendations,
            "on_time_rate":         self.on_time_rate(trips),
        }
