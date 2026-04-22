"""
HealthRide AI — Test Suite
===========================
Tests every feature of Part 1 and Part 2.
No real API keys needed — all tests run offline with mock data.

Run:  python test_healthride.py
"""

from datetime import datetime, timedelta
from models import (
    Location, Passenger, Driver, Trip, CallIntent,
    VehicleType, DriverStatus, TripStatus, AIRecommendation,
    AutomationLevel, OptimizationMode, MonitoringTrigger
)

# ── Helper (must be before imports that use it) ──────────
def from_intent(intent_str: str):
    return CallIntent(intent_str)

from vapi_receptionist import (
    VapiAssistantConfig, IntentClassifier, CallRouter,
    BookingFlowHandler, IdentityVerifier, SMSConfirmationService,
    VapiReceptionistFactory
)
from live_dispatch_ai import (
    GeoUtils, DriverScorer, DriverMatcher, AutoAssigner,
    SmartRouter, MonitoringEngine, RecommendationBuilder,
    DispatchNotifier, ManualOverrideHandler, LiveDispatchFactory
)
from daily_schedule_ai import (
    ScheduleOptimizer, ConflictDetector, CapacityPlanner,
    UnassignedSidebarAI, DailyStatsSummary, DailyScheduleFactory
)
from analytics import AnalyticsEngine


# ═══ Terminal colors ════════════════════════════════════
GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
CYAN  = "\033[96m"; BOLD = "\033[1m"; RESET  = "\033[0m"
passed = 0; failed = 0


def section(title):
    print(f"\n{BOLD}{CYAN}{'═'*55}{RESET}\n{BOLD}{CYAN}  {title}{RESET}\n{BOLD}{CYAN}{'═'*55}{RESET}")

def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1; print(f"  {GREEN}✓{RESET}  {label}")
    else:
        failed += 1; print(f"  {RED}✗{RESET}  {label}")
        if detail: print(f"      {RED}→ {detail}{RESET}")


# ═══ Mock Data ═══════════════════════════════════════════
def make_passenger(id="P-001", phone="+15551234567"):
    return Passenger(id=id, name="Linda Garcia", phone=phone,
        vehicle_requirement=VehicleType.AMBULATORY, hipaa_consent=True)

def make_driver(id="D-001", lat=34.05, lng=-118.24, status=DriverStatus.AVAILABLE, rating=4.5):
    return Driver(id=id, name="David Wilson", vehicle_type=VehicleType.AMBULATORY,
        status=status, location=Location("123 Main St", lat, lng), performance_rating=rating)

def make_trip(id="T-001", status=TripStatus.UNASSIGNED):
    return Trip(
        id=id, passenger=make_passenger(),
        pickup=Location("222 Pacific Ave, Santa Monica", 34.01, -118.49),
        dropoff=Location("Cardiology Clinic, Beverly Hills", 34.07, -118.40),
        pickup_time=datetime.now() + timedelta(hours=2),
        appointment_time=datetime.now() + timedelta(hours=3),
        vehicle_type=VehicleType.AMBULATORY, status=status
    )


# ════════════════════════════════════════════════════════
# PART 1 — VAPI RECEPTIONIST
# ════════════════════════════════════════════════════════

section("PART 1 — Vapi Assistant Config")
config = VapiAssistantConfig.build()
check("Has firstMessage",           "firstMessage" in config)
check("Has model",                  "model" in config)
check("Has 7 tools",                len(config["model"]["tools"]) == 7)
check("HIPAA enabled",              config.get("hipaaEnabled") is True)
check("Recording enabled",          config.get("recordingEnabled") is True)
check("Voice provider is playht",   config["voice"]["provider"] == "playht")

section("PART 1 — Intent Classifier")
clf = IntentClassifier()
check("Detects new_booking",        clf.classify("I need to book a ride").value == "new_booking")
check("Detects cancel_booking",     clf.classify("I want to cancel my trip").value == "cancel_booking")
check("Detects modify_booking",     clf.classify("I need to change my trip time").value == "modify_booking")
check("Detects check_status",       clf.classify("Where is my driver").value == "check_status")
check("Detects billing",            clf.classify("I have a question about my bill").value == "billing")
check("Detects emergency",          clf.classify("This is an emergency help me").value == "emergency")
check("Returns unknown",            clf.classify("blah blah blah").value == "unknown")

section("PART 1 — Call Router")
router = CallRouter()
check("Emergency → transfer",       router.route(from_intent("emergency"))["destination"] == "emergency")
check("Billing → billing",          router.route(from_intent("billing"))["destination"] == "billing")
check("New booking → ai_handle",    router.route(from_intent("new_booking"))["action"] == "ai_handle")
check("Modify → ai_handle",         router.route(from_intent("modify_booking"))["action"] == "ai_handle")
check("Check status → ai_handle",   router.route(from_intent("check_status"))["action"] == "ai_handle")

section("PART 1 — Booking Flow (All 8 Steps)")
flow = BookingFlowHandler()
steps = [
    ({"phone": "+15551234567"},                                       "verify_passenger"),
    ({"pickup_address": "222 Pacific Ave, Santa Monica"},             "collect_pickup"),
    ({"dropoff_address": "Cardiology Clinic, Beverly Hills"},         "collect_dropoff"),
    ({"pickup_time": "2025-12-28T14:00:00"},                          "collect_pickup_time"),
    ({"appointment_time": "2025-12-28T15:00:00"},                     "collect_appointment_time"),
    ({"requirements": "ambulatory", "vehicle_type": "ambulatory"},    "collect_requirements"),
    ({"confirmed": True},                                             "confirm_details"),
    ({},                                                              "finalize"),
]
for data, step_name in steps:
    result = flow.advance(data)
    check(f"Step '{step_name}' passes", result.get("valid") is True, str(result))
check("State has pickup",           "pickup_address" in flow.state)
check("State has dropoff",          "dropoff_address" in flow.state)
check("State has appointment_time", "appointment_time" in flow.state)
check("State has requirements",     "special_requirements" in flow.state)

section("PART 1 — Identity Verifier")
verifier  = IdentityVerifier()
passenger = make_passenger(phone="+15551234567")
check("Correct phone verifies",     verifier.verify("+15551234567", passenger))
check("Wrong phone rejected",       not verifier.verify("+19999999999", passenger))
check("Phone with spaces verifies", verifier.verify("+1 555 123 4567", passenger))

section("PART 1 — SMS Confirmation")
sms  = SMSConfirmationService()
trip = make_trip()
msg  = sms.booking_confirmation(trip, "HR-9001")
check("SMS has confirmation #",     "HR-9001" in msg["body"])
check("SMS has pickup address",     "Pacific" in msg["body"])
check("SMS has from number",        "from" in msg)
cancel_msg = sms.cancellation_confirmation("T-001")
check("Cancellation SMS correct",   "T-001" in cancel_msg["body"])
eta_msg = sms.driver_eta("David Wilson", 8)
check("ETA SMS has driver name",    "David Wilson" in eta_msg["body"])

section("PART 1 — Webhook Handler")
receptionist = VapiReceptionistFactory.create()
handler = receptionist["webhook_handler"]
r1 = handler.handle({"type": "call.started", "call": {"customer": {"number": "+15551234567"}}})
check("call.started → lookup",      r1.get("action") == "lookup_passenger")
check("call.started returns phone", r1.get("phone") == "+15551234567")
r2 = handler.handle({"type": "transcript.partial", "transcript": "I need to book a ride"})
check("Transcript returns intent",  "intent" in r2)
check("Transcript returns route",   "route" in r2)
r3 = handler.handle({"type": "call.ended", "call": {"id": "c-123", "duration": 120}})
check("call.ended → log_and_store", r3.get("action") == "log_and_store")
r4 = handler.handle({"type": "unknown.event"})
check("Unknown event → unhandled",  r4.get("status") == "unhandled")


# ════════════════════════════════════════════════════════
# PART 2a — LIVE MAP & REAL-TIME DISPATCH
# ════════════════════════════════════════════════════════

section("PART 2a — Geo Utils")
dist = GeoUtils.distance_km(34.05, -118.24, 34.07, -118.40)
check("Distance > 0",               dist > 0)
check("Distance < 50km",            dist < 50)
eta = GeoUtils.eta_minutes(10.0)
check("ETA for 10km ~ 15 min",      14 <= eta <= 16)

section("PART 2a — Driver Scorer")
scorer = DriverScorer()
driver = make_driver(lat=34.01, lng=-118.49)
trip   = make_trip()
score  = scorer.score(driver, trip)
check("Score 0.0–1.0",              0.0 <= score <= 1.0)
check("Close driver scores high",   score > 0.7)
offline = make_driver(status=DriverStatus.OFFLINE)
check("Offline driver scores low",  scorer.score(offline, trip) < 0.6)

section("PART 2a — Driver Matcher")
drivers = [
    make_driver("D-001", lat=34.01, lng=-118.49, rating=4.8),
    make_driver("D-002", lat=33.80, lng=-118.10, rating=3.0),
    make_driver("D-003", status=DriverStatus.OFFLINE),
]
matcher = DriverMatcher(DriverScorer())
result  = matcher.find_best(trip, drivers)
check("Finds best driver",          result is not None)
check("Has confidence %",           0 < result["confidence"] <= 100)
check("Closest driver wins",        result["driver"].id == "D-001")
ranked = matcher.rank_all(trip, drivers)
check("Excludes offline drivers",   len(ranked) == 2)
check("Sorted by confidence",       ranked[0]["confidence"] >= ranked[1]["confidence"])

section("PART 2a — Auto Assigner")
assigner = AutoAssigner(matcher)
single   = assigner.assign_single(trip, drivers)
check("Single assign result",       single is not None)
check("Has confidence",             "confidence" in single)
check("Has driver name",            "recommended_driver_name" in single)
bulk_trips = [make_trip(f"T-B{i}") for i in range(3)]
bulk = assigner.bulk_assign(bulk_trips, drivers)
check("Bulk returns list",          isinstance(bulk, list))
check("Bulk covers trips",          len(bulk) > 0)

section("PART 2a — Smart Router (offline fallback)")
smart_router = SmartRouter(maps_client=None)
route = smart_router.get_route((34.05,-118.24), (34.07,-118.40), datetime.now())
check("Route has distance_km",      "distance_km" in route)
check("Route has duration_min",     "duration_min" in route)
check("Uses fallback",              route.get("source") == "fallback_estimate")
eta_up = smart_router.recalculate_eta((34.05,-118.24), (34.07,-118.40))
check("ETA recalc returns int",     isinstance(eta_up, int))

section("PART 2a — Monitoring Engine (All 6 Triggers)")
rec_builder = RecommendationBuilder()
engine      = MonitoringEngine(matcher, rec_builder, AutomationLevel.MANUAL)
triggers    = [
    (MonitoringTrigger.TRIP_CANCELLED,   {}),
    (MonitoringTrigger.DRIVER_LATE,      {"delay_minutes": 12}),
    (MonitoringTrigger.NO_SHOW,          {}),
    (MonitoringTrigger.LAST_MINUTE_TRIP, {"free_in_minutes": 10}),
    (MonitoringTrigger.VEHICLE_ISSUE,    {"affected_trips": 2}),
    (MonitoringTrigger.TRAFFIC_DELAY,    {"delay_minutes": 8}),
]
for trigger, ctx in triggers:
    rec = engine.process_event(trigger, make_trip(), drivers, ctx)
    check(f"Trigger '{trigger.value}'", bool(rec.what_happened) and bool(rec.what_to_change))
check("6 pending recommendations",  len(engine.pending) == 6)
accepted = engine.batch_accept()
check("Batch accept clears queue",  len(engine.pending) == 0)
check("All accepted = True",        all(r.accepted is True for r in accepted))

engine2 = MonitoringEngine(matcher, rec_builder, AutomationLevel.MANUAL)
engine2.process_event(MonitoringTrigger.TRIP_CANCELLED, make_trip("T-DIS"), drivers)
check("Dismiss removes rec",        engine2.dismiss("T-DIS") is True)
check("Pending empty after dismiss",len(engine2.pending) == 0)

engine3 = MonitoringEngine(matcher, rec_builder, AutomationLevel.AUTOMATIC)
rec_auto = engine3.process_event(MonitoringTrigger.DRIVER_LATE, make_trip(), drivers, {"delay_minutes": 5})
check("Automatic mode auto-accepts",rec_auto.accepted is True)
check("Automatic skips pending",    len(engine3.pending) == 0)

section("PART 2a — Manual Override Handler")
engine4  = MonitoringEngine(matcher, rec_builder, AutomationLevel.MANUAL)
engine4.process_event(MonitoringTrigger.TRIP_CANCELLED, make_trip("T-OVR"), drivers)
override = ManualOverrideHandler(engine4)
new_drv  = make_driver("D-NEW")
ov_trip  = make_trip("T-OVR", TripStatus.UNASSIGNED)
event    = override.apply_override(ov_trip, new_drv, "D-001", "DISP-1", "Driver was closer")
check("Trip driver updated",        ov_trip.assigned_driver_id == "D-NEW")
check("Trip status → scheduled",    ov_trip.status == TripStatus.SCHEDULED)
check("Pending rec cleared",        len(engine4.pending) == 0)
check("Override log has 1 entry",   len(override.get_override_log()) == 1)
check("Override log has feedback",  override.get_override_log()[0]["feedback"] == "Driver was closer")

section("PART 2a — Dispatch Notifier")
notifier   = DispatchNotifier()
push       = notifier.assignment_push(make_driver(), trip)
check("Push has driver_id",         "driver_id" in push)
check("Push has title",             push["title"] == "New Trip Assigned")
check("Push has trip data",         push["data"]["trip_id"] == trip.id)
escalation = notifier.escalation_alert(make_driver(), trip)
check("Escalation has message",     "not acknowledged" in escalation["message"])


# ════════════════════════════════════════════════════════
# PART 2b — DAILY SCHEDULE
# ════════════════════════════════════════════════════════

section("PART 2b — Schedule Optimizer (All 3 Modes)")
multi_drivers = [
    Driver("D-A", "John S.",  VehicleType.AMBULATORY, DriverStatus.AVAILABLE, Location("", 34.01, -118.49), 4.5),
    Driver("D-B", "Maria R.", VehicleType.AMBULATORY, DriverStatus.AVAILABLE, Location("", 34.02, -118.45), 4.2),
]
matcher2 = DriverMatcher(DriverScorer())
for mode in [OptimizationMode.EFFICIENT, OptimizationMode.BALANCED, OptimizationMode.RELAXED]:
    d_copy = [Driver(d.id, d.name, d.vehicle_type, DriverStatus.AVAILABLE, d.location, d.performance_rating) for d in multi_drivers]
    t_copy = [make_trip(f"T-{mode.value[:3]}-{i}") for i in range(3)]
    sched  = ScheduleOptimizer(matcher2, mode).generate(t_copy, d_copy)
    check(f"Mode '{mode.value}' generates entries", len(sched) > 0)
    check(f"Mode '{mode.value}' to_dict works",     all("trip_id" in e.to_dict() for e in sched))

section("PART 2b — Conflict Detector")
detector  = ConflictDetector()
drv       = make_driver("D-CON")
base_time = datetime.now() + timedelta(hours=1)
entry_a   = type("E", (), {"driver": drv, "trip": make_trip("T-A"),
    "start_time": base_time, "end_time": base_time + timedelta(minutes=60)})()
entry_b   = type("E", (), {"driver": drv, "trip": make_trip("T-B"),
    "start_time": base_time + timedelta(minutes=30),
    "end_time":   base_time + timedelta(minutes=90)})()
conflicts = detector.detect([entry_a, entry_b])
check("Conflict detected",          len(conflicts) == 1)
check("Conflict lists trip IDs",    "T-A" in str(conflicts[0]))

section("PART 2b — Capacity Planner")
d1 = make_driver("D-BUSY"); d2 = make_driver("D-FREE")
cap_trips = [make_trip(f"T-CAP-{i}", TripStatus.SCHEDULED) for i in range(9)]
for t in cap_trips:
    t.assigned_driver_id = "D-BUSY"
summary    = CapacityPlanner().workload_summary([d1, d2], cap_trips)
overloaded = CapacityPlanner().flag_overbooking(summary)
check("Summary has both drivers",   len(summary) == 2)
check("Overbooking flagged",        len(overloaded) == 1)
check("Correct driver flagged",     overloaded[0]["driver_id"] == "D-BUSY")
balance = CapacityPlanner().balance_load(summary)
check("Balance suggestions given",  len(balance) > 0)

section("PART 2b — Unassigned Sidebar AI")
sidebar     = UnassignedSidebarAI(matcher2)
suggestions = sidebar.get_suggestions([make_trip("T-S1"), make_trip("T-S2")], multi_drivers)
check("One card per trip",          len(suggestions) == 2)
check("Card has passenger name",    "passenger_name" in suggestions[0])
check("Card has suggested driver",  suggestions[0]["ai_suggested_driver"] is not None)
check("Card has confidence %",      suggestions[0]["confidence"] > 0)
check("Card has eta_minutes",       suggestions[0]["eta_minutes"] is not None)

section("PART 2b — Daily Stats Summary")
stats_trips = [
    make_trip("S1", TripStatus.COMPLETED), make_trip("S2", TripStatus.COMPLETED),
    make_trip("S3", TripStatus.IN_PROGRESS), make_trip("S4", TripStatus.SCHEDULED),
    make_trip("S5", TripStatus.UNASSIGNED),
]
stats = DailyStatsSummary().compute(stats_trips)
check("Total = 5",          stats["total"] == 5)
check("Completed = 2",      stats["completed"] == 2)
check("In progress = 1",    stats["in_progress"] == 1)
check("Scheduled = 1",      stats["scheduled"] == 1)
check("Unassigned = 1",     stats["unassigned"] == 1)


# ════════════════════════════════════════════════════════
# ANALYTICS
# ════════════════════════════════════════════════════════

section("Analytics Engine")
call_logs = [
    {"intent": "new_booking",  "booking_created": True,  "escalated": False},
    {"intent": "new_booking",  "booking_created": True,  "escalated": False},
    {"intent": "check_status", "booking_created": False, "escalated": False},
    {"intent": "billing",      "booking_created": False, "escalated": True, "escalation_reason": "payment dispute"},
]
rec1 = AIRecommendation(MonitoringTrigger.TRIP_CANCELLED, "trip cancelled", "reassign", "faster", "T-1", "D-1", 0.88, accepted=True)
rec2 = AIRecommendation(MonitoringTrigger.DRIVER_LATE,    "driver late",    "reassign", "faster", "T-2", "D-2", 0.72, accepted=False)
rec3 = AIRecommendation(MonitoringTrigger.NO_SHOW,        "no show",        "fill gap", "productive", "T-3", "D-1", 0.65, accepted=True)
all_trips    = [make_trip(f"T-AN-{i}", TripStatus.COMPLETED) for i in range(5)]
override_log = [{"trip_id": "T-1", "new_driver_id": "D-2", "overridden_by": "DISP-1"}]
analytics    = AnalyticsEngine()
summary      = analytics.summary(call_logs, [rec1, rec2, rec3], all_trips, override_log)
check("Call volume = 4",            summary["call_volume"] == 4)
check("Conversion rate = 50%",      summary["booking_conversion"] == 50.0)
check("Escalation count = 1",       summary["escalation_count"] == 1)
check("AI acceptance rate > 0",     summary["ai_acceptance_rate"] > 0)
check("AI accuracy score present",  "ai_accuracy_score" in summary)
check("AI avg confidence present",  "ai_avg_confidence" in summary)
check("AI overrides = 1",           summary["ai_overrides"] == 1)
check("On-time rate present",       "on_time_rate" in summary)
check("Top intents present",        "top_intents" in summary)
check("Dismissed triggers present", "top_dismissed_triggers" in summary)


# ════════════════════════════════════════════════════════
# FACTORY SMOKE TESTS
# ════════════════════════════════════════════════════════

section("Factory Smoke Tests")
r = VapiReceptionistFactory.create()
check("VapiReceptionistFactory",    all(k in r for k in ["assistant_config", "webhook_handler", "sms_service"]))
live = LiveDispatchFactory.create()
check("LiveDispatchFactory",        all(k in live for k in ["auto_assigner", "monitoring_engine", "smart_router", "dispatch_notifier", "override_handler"]))
sched = DailyScheduleFactory.create()
check("DailyScheduleFactory",       all(k in sched for k in ["schedule_optimizer", "conflict_detector", "capacity_planner", "unassigned_sidebar", "daily_stats"]))


# ════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════
total = passed + failed
print(f"\n{BOLD}{'═'*55}{RESET}")
print(f"{BOLD}  RESULTS: {GREEN}{passed} passed{RESET}{BOLD} / {RED}{failed} failed{RESET}{BOLD} / {total} total{RESET}")
if failed == 0:
    print(f"  {GREEN}{BOLD}✓ All tests passed — AI layer is ready to hand off.{RESET}")
else:
    print(f"  {YELLOW}⚠  {failed} test(s) failed — review above.{RESET}")
print(f"{BOLD}{'═'*55}{RESET}\n")