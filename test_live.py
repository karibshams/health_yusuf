"""
HealthRide AI — Live Test
==========================
Interactive terminal test for every feature.
Tests TWO modes:

  MODE 1 — OFFLINE (no APIs needed)
    Tests all AI logic with mock data.
    Run anytime, no .env required.

  MODE 2 — LIVE (real APIs)
    Tests real Vapi config push, real SMS via Twilio,
    real Google Maps routing.
    Requires .env with real keys.

Run:
    python test_live.py            ← offline mode
    python test_live.py --live     ← live API mode
"""

import sys
import time
import json
from datetime import datetime, timedelta

# ── detect mode ──────────────────────────────────────
LIVE_MODE = "--live" in sys.argv

# ── colors ───────────────────────────────────────────
GREEN  = "\033[92m"; RED    = "\033[91m"; YELLOW = "\033[93m"
CYAN   = "\033[96m"; BLUE   = "\033[94m"; BOLD   = "\033[1m"
RESET  = "\033[0m";  DIM    = "\033[2m"

# ── counters ─────────────────────────────────────────
passed = 0; failed = 0; skipped = 0


def header():
    mode_label = f"{RED}🔴 LIVE API MODE{RESET}" if LIVE_MODE else f"{GREEN}🟢 OFFLINE MODE{RESET}"
    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════════════════════╗
║          HealthRide AI — Live Test Runner            ║
╚══════════════════════════════════════════════════════╝{RESET}
  Mode   : {mode_label}
  Time   : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
""")


def section(title):
    print(f"\n{BOLD}{BLUE}┌─────────────────────────────────────────────────────┐{RESET}")
    print(f"{BOLD}{BLUE}│  {title:<51}│{RESET}")
    print(f"{BOLD}{BLUE}└─────────────────────────────────────────────────────┘{RESET}")


def ok(label, detail=""):
    global passed; passed += 1
    print(f"  {GREEN}✓{RESET}  {label}", end="")
    if detail: print(f"  {DIM}({detail}){RESET}", end="")
    print()


def fail(label, detail=""):
    global failed; failed += 1
    print(f"  {RED}✗{RESET}  {label}")
    if detail: print(f"      {RED}↳ {detail}{RESET}")


def skip(label, reason=""):
    global skipped; skipped += 1
    print(f"  {YELLOW}⊘{RESET}  {DIM}{label} — {reason}{RESET}")


def check(label, condition, detail="", live_only=False):
    if live_only and not LIVE_MODE:
        skip(label, "live mode only")
        return
    if condition:
        ok(label, detail)
    else:
        fail(label, detail)


def show(label, value):
    """Display a value result to the tester."""
    print(f"  {CYAN}→{RESET}  {label}: {BOLD}{value}{RESET}")


def pause(msg=""):
    if msg:
        print(f"\n  {YELLOW}ℹ  {msg}{RESET}")
    time.sleep(0.05)


# ════════════════════════════════════════════════════════
# IMPORTS
# ════════════════════════════════════════════════════════

from models import (
    Location, Passenger, Driver, Trip, CallIntent, AIRecommendation,
    VehicleType, DriverStatus, TripStatus,
    AutomationLevel, OptimizationMode, MonitoringTrigger
)
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


# ════════════════════════════════════════════════════════
# MOCK DATA
# ════════════════════════════════════════════════════════

def mock_passenger(id="P-001", phone="+15551234567"):
    return Passenger(id=id, name="Linda Garcia", phone=phone,
        vehicle_requirement=VehicleType.AMBULATORY, hipaa_consent=True)

def mock_driver(id="D-001", name="David Wilson", lat=34.01, lng=-118.49,
                status=DriverStatus.AVAILABLE, rating=4.8):
    return Driver(id=id, name=name, vehicle_type=VehicleType.AMBULATORY,
        status=status, location=Location("123 Main St", lat, lng),
        performance_rating=rating)

def mock_trip(id="T-001", status=TripStatus.UNASSIGNED):
    return Trip(
        id=id, passenger=mock_passenger(),
        pickup=Location("222 Pacific Ave, Santa Monica", 34.01, -118.49),
        dropoff=Location("Cardiology Clinic, Beverly Hills", 34.07, -118.40),
        pickup_time=datetime.now() + timedelta(hours=2),
        appointment_time=datetime.now() + timedelta(hours=3),
        vehicle_type=VehicleType.AMBULATORY, status=status
    )

def mock_drivers():
    return [
        mock_driver("D-001", "David Wilson",   lat=34.01, lng=-118.49, rating=4.8),
        mock_driver("D-002", "Maria Rodriguez",lat=33.85, lng=-118.20, rating=4.2),
        mock_driver("D-003", "John Smith",      lat=34.05, lng=-118.30, rating=3.9,
                    status=DriverStatus.EN_ROUTE),
        mock_driver("D-004", "Emily Chen",      lat=33.70, lng=-118.10, rating=4.5,
                    status=DriverStatus.OFFLINE),
    ]


# ════════════════════════════════════════════════════════
# TEST 1 — VAPI ASSISTANT CONFIG
# ════════════════════════════════════════════════════════

section("TEST 1 — Vapi Assistant Configuration")
pause("Building Vapi assistant config...")

config = VapiAssistantConfig.build()
check("Config builds successfully",     config is not None)
check("HIPAA enabled",                  config.get("hipaaEnabled") is True)
check("Recording enabled",              config.get("recordingEnabled") is True)
check("Has 7 tools",                    len(config["model"]["tools"]) == 7)
check("Voice = PlayHT",                 config["voice"]["provider"] == "playht")
check("Transcriber = Deepgram",         config["transcriber"]["provider"] == "deepgram")
show("First message", config["firstMessage"])
show("Tools loaded",  ", ".join(t["function"]["name"] for t in config["model"]["tools"]))

if LIVE_MODE:
    section("TEST 1b — Push Config to Vapi API (LIVE)")
    try:
        import requests
        from config import Config
        resp = requests.post(
            "https://api.vapi.ai/assistant",
            headers={"Authorization": f"Bearer {Config.VAPI_API_KEY}",
                     "Content-Type": "application/json"},
            json=config, timeout=10
        )
        check("Vapi API responds 200/201",  resp.status_code in (200, 201),
              f"Status: {resp.status_code}", live_only=True)
        if resp.status_code in (200, 201):
            assistant_id = resp.json().get("id", "unknown")
            show("Vapi Assistant ID", assistant_id)
    except Exception as e:
        fail("Vapi API call", str(e))


# ════════════════════════════════════════════════════════
# TEST 2 — CALLER INTENT CLASSIFICATION
# ════════════════════════════════════════════════════════

section("TEST 2 — Intent Classifier (Simulated Callers)")
pause("Running caller phrase classification...")

clf = IntentClassifier()
caller_phrases = [
    ("I need to book a ride to my doctor appointment",  "new_booking"),
    ("I want to cancel my trip tomorrow",               "cancel_booking"),
    ("Can I change the time of my ride",                "modify_booking"),
    ("Where is my driver right now",                    "check_status"),
    ("I have a question about my insurance bill",       "billing"),
    ("Help me this is an emergency",                    "emergency"),
    ("Um I don't know what I need",                     "unknown"),
]
for phrase, expected in caller_phrases:
    result = clf.classify(phrase)
    check(f'"{phrase[:45]}..."', result.value == expected,
          f"got {result.value}, expected {expected}")


# ════════════════════════════════════════════════════════
# TEST 3 — CALL ROUTING TABLE
# ════════════════════════════════════════════════════════

section("TEST 3 — Call Routing Logic")
pause("Testing all routing paths...")

router = CallRouter()
routing_tests = [
    (CallIntent.EMERGENCY,      "transfer",  "emergency"),
    (CallIntent.BILLING,        "transfer",  "billing"),
    (CallIntent.COMPLEX,        "transfer",  "dispatcher"),
    (CallIntent.NEW_BOOKING,    "ai_handle", None),
    (CallIntent.MODIFY_BOOKING, "ai_handle", None),
    (CallIntent.CANCEL_BOOKING, "ai_handle", None),
    (CallIntent.CHECK_STATUS,   "ai_handle", None),
]
for intent, expected_action, expected_dest in routing_tests:
    route = router.route(intent)
    action_ok = route["action"] == expected_action
    dest_ok   = (expected_dest is None) or (route.get("destination") == expected_dest)
    check(f"Intent '{intent.value}'",  action_ok and dest_ok,
          f"action={route['action']} dest={route.get('destination','—')}")


# ════════════════════════════════════════════════════════
# TEST 4 — FULL BOOKING CONVERSATION (8 STEPS)
# ════════════════════════════════════════════════════════

section("TEST 4 — Full Booking Flow (Simulated Conversation)")
pause("Simulating a passenger booking call step by step...")

flow = BookingFlowHandler()
conversation = [
    ("CALLER: My number is +15551234567",
     {"phone": "+15551234567"}),
    ("CALLER: Pickup from 222 Pacific Ave, Santa Monica",
     {"pickup_address": "222 Pacific Ave, Santa Monica"}),
    ("CALLER: I'm going to Cardiology Clinic in Beverly Hills",
     {"dropoff_address": "Cardiology Clinic, Beverly Hills"}),
    ("CALLER: Tomorrow at 2 PM please",
     {"pickup_time": "2025-12-28T14:00:00"}),
    ("CALLER: My appointment is at 3 PM",
     {"appointment_time": "2025-12-28T15:00:00"}),
    ("CALLER: I use a wheelchair",
     {"requirements": "wheelchair", "vehicle_type": "wheelchair_van"}),
    ("CALLER: Yes that's all correct",
     {"confirmed": True}),
    ("SYSTEM: Finalizing booking",
     {}),
]
for caller_says, input_data in conversation:
    result = flow.advance(input_data)
    print(f"  {DIM}{caller_says}{RESET}")
    check(f"  Step passes", result.get("valid") is True, str(result))
    if result.get("prompt"):
        print(f"    {GREEN}AI:{RESET} {result['prompt']}")

show("Final booking state", json.dumps(flow.state, indent=2).replace("\n", "\n              "))


# ════════════════════════════════════════════════════════
# TEST 5 — IDENTITY VERIFICATION
# ════════════════════════════════════════════════════════

section("TEST 5 — Identity Verification (Before Modifications)")
pause("Testing caller identity verification...")

verifier  = IdentityVerifier()
passenger = mock_passenger(phone="+15551234567")
cases = [
    ("+15551234567", True,  "Exact match"),
    ("+1 555 123 4567", True,  "With spaces"),
    ("+1-555-123-4567", True,  "With dashes"),
    ("+19998887777", False, "Wrong number — should be rejected"),
]
for phone, expected, label in cases:
    result = verifier.verify(phone, passenger)
    check(label, result == expected, f"verify({phone}) = {result}")


# ════════════════════════════════════════════════════════
# TEST 6 — SMS CONFIRMATIONS
# ════════════════════════════════════════════════════════

section("TEST 6 — SMS Confirmation Messages")
pause("Building SMS messages...")

sms  = SMSConfirmationService()
trip = mock_trip()

booking_sms = sms.booking_confirmation(trip, "HR-2025-9001")
show("Booking SMS", booking_sms["body"])
check("Contains confirmation #",    "HR-2025-9001" in booking_sms["body"])
check("Contains pickup address",    "Pacific" in booking_sms["body"])
check("Has from number",            bool(booking_sms["from"]))

cancel_sms = sms.cancellation_confirmation("T-001")
show("Cancel SMS",  cancel_sms["body"])
check("Cancel SMS has trip ID",     "T-001" in cancel_sms["body"])

eta_sms = sms.driver_eta("David Wilson", 8)
show("ETA SMS",     eta_sms["body"])
check("ETA SMS has driver name",    "David Wilson" in eta_sms["body"])
check("ETA SMS has minutes",        "8" in eta_sms["body"])

if LIVE_MODE:
    section("TEST 6b — Send Real SMS via Twilio (LIVE)")
    try:
        from twilio.rest import Client
        from config import Config
        client = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
        # Sends to the Vapi phone number as a test destination
        msg = client.messages.create(
            to=Config.VAPI_PHONE_NUMBER,
            from_=Config.TWILIO_PHONE_NUMBER,
            body=booking_sms["body"]
        )
        check("Twilio SMS sent",    msg.sid is not None,
              f"SID: {msg.sid}", live_only=True)
        show("SMS SID", msg.sid)
    except ImportError:
        skip("Twilio SMS", "pip install twilio first")
    except Exception as e:
        fail("Twilio SMS send", str(e))


# ════════════════════════════════════════════════════════
# TEST 7 — DRIVER SCORING & MATCHING
# ════════════════════════════════════════════════════════

section("TEST 7 — AI Driver Scoring & Matching")
pause("Scoring all drivers against the trip...")

drivers = mock_drivers()
trip    = mock_trip()
scorer  = DriverScorer()
matcher = DriverMatcher(scorer)

print(f"\n  {'Driver':<18} {'Status':<16} {'Score':>6}  {'Confidence':>10}")
print(f"  {'─'*18} {'─'*16} {'─'*6}  {'─'*10}")
for d in drivers:
    score = scorer.score(d, trip)
    conf  = round(score * 100)
    bar   = "█" * (conf // 10) + "░" * (10 - conf // 10)
    print(f"  {d.name:<18} {d.status.value:<16} {score:>6.2f}  {bar} {conf}%")

result = matcher.find_best(trip, drivers)
print()
check("Best driver found",              result is not None)
check("Best driver is closest available", result["driver"].id == "D-001")
check("Confidence is meaningful %",     result["confidence"] >= 50)
show("AI Recommendation",
     f"{result['driver'].name} — {result['confidence']}% match, "
     f"{result['distance_km']} km away, ETA {result['eta_minutes']} min")

ranked = matcher.rank_all(trip, drivers)
print(f"\n  {CYAN}All drivers ranked:{RESET}")
for i, r in enumerate(ranked, 1):
    print(f"    {i}. {r['driver'].name} — {r['confidence']}%")


# ════════════════════════════════════════════════════════
# TEST 8 — AUTO ASSIGN (SINGLE + BULK)
# ════════════════════════════════════════════════════════

section("TEST 8 — Auto Assignment (Single + Bulk)")
pause("Testing AI auto-assign...")

assigner = AutoAssigner(matcher)

single = assigner.assign_single(trip, drivers)
check("Single assign returns result",   single is not None)
show("Single assign result",
     f"Trip {single['trip_id']} → {single['recommended_driver_name']} "
     f"({single['confidence']}% confidence, ETA {single['eta_minutes']} min)")

bulk_trips = [mock_trip(f"T-{i:03d}") for i in range(1, 6)]
fresh_drivers = mock_drivers()
bulk = assigner.bulk_assign(bulk_trips, fresh_drivers)
check("Bulk assign returns list",       isinstance(bulk, list))
check("Bulk assigns at least 1 trip",   len(bulk) >= 1)
print(f"\n  {CYAN}Bulk assignments:{RESET}")
for a in bulk:
    print(f"    Trip {a['trip_id']} → {a['driver_name']} ({a['confidence']}%)")


# ════════════════════════════════════════════════════════
# TEST 9 — SMART ROUTING
# ════════════════════════════════════════════════════════

section("TEST 9 — Smart Routing")
pause("Calculating route...")

router_ai = SmartRouter(maps_client=None)
route = router_ai.get_route(
    (34.05, -118.24), (34.07, -118.40), datetime.now()
)
check("Route calculated",               "distance_km" in route)
check("Duration available",             "duration_min" in route)
show("Route (offline estimate)",
     f"{route['distance_km']} km, ~{route['duration_min']} min")

eta = router_ai.recalculate_eta((34.05, -118.24), (34.07, -118.40))
show("Live ETA recalculation", f"{eta} min")

if LIVE_MODE:
    section("TEST 9b — Google Maps Real Route (LIVE)")
    try:
        import googlemaps
        from config import Config
        gmaps = googlemaps.Client(key=Config.GOOGLE_MAPS_API_KEY)
        live_router = SmartRouter(maps_client=gmaps)
        live_route = live_router.get_route(
            (34.05, -118.24), (34.07, -118.40), datetime.now()
        )
        check("Google Maps route returned",  "legs" in str(live_route) or "distance_km" in live_route,
              live_only=True)
        show("Live route data", str(live_route)[:100] + "...")
    except ImportError:
        skip("Google Maps routing", "pip install googlemaps first")
    except Exception as e:
        fail("Google Maps routing", str(e))


# ════════════════════════════════════════════════════════
# TEST 10 — ALL 6 MONITORING TRIGGERS
# ════════════════════════════════════════════════════════

section("TEST 10 — Live Monitoring (All 6 Triggers)")
pause("Simulating live dispatch events...")

rec_builder = RecommendationBuilder()
engine      = MonitoringEngine(matcher, rec_builder, AutomationLevel.MANUAL)
drivers     = mock_drivers()

trigger_scenarios = [
    (MonitoringTrigger.TRIP_CANCELLED,   {},                    "Trip T-001 at 2:00 PM was just cancelled"),
    (MonitoringTrigger.DRIVER_LATE,      {"delay_minutes": 12}, "Driver is 12 min late for pickup"),
    (MonitoringTrigger.NO_SHOW,          {},                    "Passenger did not show up"),
    (MonitoringTrigger.LAST_MINUTE_TRIP, {"free_in_minutes": 8},"New trip just came in last minute"),
    (MonitoringTrigger.VEHICLE_ISSUE,    {"affected_trips": 3}, "Vehicle breakdown — 3 trips affected"),
    (MonitoringTrigger.TRAFFIC_DELAY,    {"delay_minutes": 15}, "Heavy traffic on route"),
]

for trigger, ctx, scenario_label in trigger_scenarios:
    print(f"\n  {YELLOW}EVENT:{RESET} {scenario_label}")
    rec = engine.process_event(trigger, mock_trip(f"T-{trigger.value[:3].upper()}"), drivers, ctx)
    check(f"Recommendation built for '{trigger.value}'",
          bool(rec.what_happened))
    print(f"  {DIM}What happened:{RESET}  {rec.what_happened}")
    print(f"  {DIM}What to change:{RESET} {rec.what_to_change}")
    print(f"  {DIM}Why it helps:{RESET}  {rec.why_it_helps}")
    print(f"  {DIM}Confidence:{RESET}    {round(rec.confidence * 100)}%")


# ════════════════════════════════════════════════════════
# TEST 11 — AUTOMATION LEVELS
# ════════════════════════════════════════════════════════

section("TEST 11 — Automation Levels (Manual / One-Click / Automatic)")
pause("Testing all 3 automation levels...")

# Manual
engine_manual = MonitoringEngine(matcher, rec_builder, AutomationLevel.MANUAL)
engine_manual.process_event(MonitoringTrigger.TRIP_CANCELLED, mock_trip("T-M1"), mock_drivers())
engine_manual.process_event(MonitoringTrigger.DRIVER_LATE,    mock_trip("T-M2"), mock_drivers(), {"delay_minutes": 5})
check("Manual: 2 recs queued for review",   len(engine_manual.pending) == 2)
show("Manual pending count", len(engine_manual.pending))

# One-click batch accept
accepted = engine_manual.batch_accept()
check("One-Click: batch accept clears queue", len(engine_manual.pending) == 0)
check("One-Click: all recs accepted",         all(r.accepted for r in accepted))
show("Batch accepted", f"{len(accepted)} recommendations")

# Automatic
engine_auto = MonitoringEngine(matcher, rec_builder, AutomationLevel.AUTOMATIC)
rec_auto = engine_auto.process_event(MonitoringTrigger.NO_SHOW, mock_trip("T-A1"), mock_drivers())
check("Automatic: rec auto-accepted",         rec_auto.accepted is True)
check("Automatic: nothing in pending queue",  len(engine_auto.pending) == 0)
show("Automatic mode", "Recommendation applied immediately, provider notified")

# Dismiss with feedback
engine_manual2 = MonitoringEngine(matcher, rec_builder, AutomationLevel.MANUAL)
engine_manual2.process_event(MonitoringTrigger.TRAFFIC_DELAY, mock_trip("T-D1"), mock_drivers(), {"delay_minutes": 3})
dismissed = engine_manual2.dismiss("T-D1", feedback="Delay was too small to act on")
check("Dismiss clears recommendation",        dismissed is True)
show("Feedback logged", "Delay was too small to act on")


# ════════════════════════════════════════════════════════
# TEST 12 — MANUAL OVERRIDE
# ════════════════════════════════════════════════════════

section("TEST 12 — Manual Override (Dispatcher Drag & Drop)")
pause("Simulating dispatcher overriding an AI assignment...")

engine_ov = MonitoringEngine(matcher, rec_builder, AutomationLevel.MANUAL)
engine_ov.process_event(MonitoringTrigger.TRIP_CANCELLED, mock_trip("T-OV1"), mock_drivers())
override_handler = ManualOverrideHandler(engine_ov)

ov_trip   = mock_trip("T-OV1", TripStatus.UNASSIGNED)
new_driver = mock_driver("D-002", "Maria Rodriguez")
event = override_handler.apply_override(
    trip=ov_trip,
    new_driver=new_driver,
    previous_driver_id="D-001",
    dispatcher_id="DISP-001",
    feedback="Maria is closer to this pickup"
)
check("Trip assigned to new driver",   ov_trip.assigned_driver_id == "D-002")
check("Trip status → scheduled",       ov_trip.status == TripStatus.SCHEDULED)
check("AI rec cleared from queue",     len(engine_ov.pending) == 0)
check("Override logged",               len(override_handler.get_override_log()) == 1)
show("Override event", f"Trip T-OV1 → {event['new_driver_id']} by {event['overridden_by']}")
show("Feedback", event["feedback"])


# ════════════════════════════════════════════════════════
# TEST 13 — DAILY SCHEDULE (ALL 3 OPTIMIZATION MODES)
# ════════════════════════════════════════════════════════

section("TEST 13 — Daily Schedule Optimizer (All 3 Modes)")
pause("Generating optimized day schedule...")

sched_drivers = [
    Driver("D-A", "John S.",   VehicleType.AMBULATORY, DriverStatus.AVAILABLE,
           Location("", 34.01, -118.49), 4.5),
    Driver("D-B", "Maria R.",  VehicleType.AMBULATORY, DriverStatus.AVAILABLE,
           Location("", 34.02, -118.45), 4.2),
    Driver("D-C", "Mike T.",   VehicleType.AMBULATORY, DriverStatus.AVAILABLE,
           Location("", 34.03, -118.42), 3.9),
]
sched_trips = [mock_trip(f"T-SCH-{i:02d}") for i in range(6)]
matcher2    = DriverMatcher(DriverScorer())

for mode in [OptimizationMode.EFFICIENT, OptimizationMode.BALANCED, OptimizationMode.RELAXED]:
    d_copy = [Driver(d.id, d.name, d.vehicle_type, DriverStatus.AVAILABLE,
                     d.location, d.performance_rating) for d in sched_drivers]
    t_copy = [mock_trip(f"T-{mode.value[:3].upper()}-{i}") for i in range(4)]
    optimizer = ScheduleOptimizer(matcher2, mode)
    schedule  = optimizer.generate(t_copy, d_copy)
    check(f"Mode '{mode.value}': schedule generated",  len(schedule) > 0,
          f"{len(schedule)} entries")
    print(f"\n  {CYAN}[{mode.value.upper()}] Schedule:{RESET}")
    for entry in schedule:
        d = entry.to_dict()
        print(f"    {d['driver_name']:<14} → {d['pickup_time']} → {d['dropoff_time']}  "
              f"({d['duration_min']} min)  Passenger: {d['passenger_name']}")


# ════════════════════════════════════════════════════════
# TEST 14 — UNASSIGNED SIDEBAR AI
# ════════════════════════════════════════════════════════

section("TEST 14 — Unassigned Sidebar AI Suggestions")
pause("Generating sidebar suggestion cards...")

sidebar       = UnassignedSidebarAI(matcher2)
unassigned    = [mock_trip(f"T-SIDE-{i}") for i in range(3)]
suggestions   = sidebar.get_suggestions(unassigned, sched_drivers)

check("One card per unassigned trip",   len(suggestions) == 3)
print(f"\n  {CYAN}Unassigned Trip Sidebar:{RESET}")
for s in suggestions:
    print(f"    {s['passenger_name']:<14} → AI suggests: {s['ai_suggested_driver']:<16} "
          f"({s['confidence']}% match, ETA {s['eta_minutes']} min)")
    check(f"  Card has all required fields",
          all(k in s for k in ["trip_id","passenger_name","confidence","eta_minutes","ai_suggested_driver_id"]))


# ════════════════════════════════════════════════════════
# TEST 15 — CONFLICT DETECTION
# ════════════════════════════════════════════════════════

section("TEST 15 — Conflict Detection")
pause("Testing scheduling conflict detection...")

from daily_schedule_ai import ScheduleEntry
detector  = ConflictDetector()
drv       = mock_driver("D-CON", "Conflict Driver")
base_time = datetime.now() + timedelta(hours=1)

# Build two overlapping entries manually
entry_a = type("E", (), {
    "driver": drv, "trip": mock_trip("T-CON-A"),
    "start_time": base_time,
    "end_time":   base_time + timedelta(minutes=60)
})()
entry_b = type("E", (), {
    "driver": drv, "trip": mock_trip("T-CON-B"),
    "start_time": base_time + timedelta(minutes=30),   # overlaps
    "end_time":   base_time + timedelta(minutes=90)
})()
entry_c = type("E", (), {
    "driver": drv, "trip": mock_trip("T-CON-C"),
    "start_time": base_time + timedelta(minutes=90),   # no overlap
    "end_time":   base_time + timedelta(minutes=120)
})()

conflicts = detector.detect([entry_a, entry_b, entry_c])
check("Overlap detected between A and B",   len(conflicts) == 1)
check("C has no conflict",                  len(conflicts) < 2)
show("Conflict detail", f"Trip {conflicts[0]['trip_a']} overlaps {conflicts[0]['trip_b']} "
     f"by {conflicts[0]['overlap_min']} min")


# ════════════════════════════════════════════════════════
# TEST 16 — CAPACITY PLANNING
# ════════════════════════════════════════════════════════

section("TEST 16 — Capacity Planning & Load Balancing")
pause("Checking driver workload distribution...")

d1 = mock_driver("D-HEAVY", "Heavy Driver")
d2 = mock_driver("D-LIGHT", "Light Driver")
d3 = mock_driver("D-MID",   "Mid Driver")

all_trips = []
for i in range(9):  # D1 = overloaded
    t = mock_trip(f"T-H{i}", TripStatus.SCHEDULED)
    t.assigned_driver_id = "D-HEAVY"
    all_trips.append(t)
for i in range(2):  # D2 = underloaded
    t = mock_trip(f"T-L{i}", TripStatus.SCHEDULED)
    t.assigned_driver_id = "D-LIGHT"
    all_trips.append(t)
for i in range(5):  # D3 = normal
    t = mock_trip(f"T-M{i}", TripStatus.SCHEDULED)
    t.assigned_driver_id = "D-MID"
    all_trips.append(t)

planner  = CapacityPlanner()
summary  = planner.workload_summary([d1, d2, d3], all_trips)

print(f"\n  {'Driver':<16} {'Trips':>6} {'Util':>6}  {'Status'}")
print(f"  {'─'*16} {'─'*6} {'─'*6}  {'─'*10}")
for s in summary:
    bar   = "█" * (s['utilization'] // 10) + "░" * (10 - min(s['utilization'] // 10, 10))
    flag  = f" {RED}⚠ OVERLOADED{RESET}" if s['overloaded'] else ""
    print(f"  {s['driver_name']:<16} {s['trip_count']:>6} {s['utilization']:>5}%  {bar}{flag}")

overloaded = planner.flag_overbooking(summary)
check("Overloaded driver flagged",      len(overloaded) == 1)
check("Correct driver is flagged",      overloaded[0]["driver_id"] == "D-HEAVY")

balance = planner.balance_load(summary)
check("Load balance suggestions given", len(balance) > 0)
for b in balance:
    show("Balance suggestion", b["reason"])


# ════════════════════════════════════════════════════════
# TEST 17 — DAILY STATS (STAT CARDS)
# ════════════════════════════════════════════════════════

section("TEST 17 — Daily Stats Summary (Dashboard Cards)")
pause("Computing daily stat cards...")

stat_trips = [
    mock_trip("S1", TripStatus.COMPLETED),
    mock_trip("S2", TripStatus.COMPLETED),
    mock_trip("S3", TripStatus.COMPLETED),
    mock_trip("S4", TripStatus.IN_PROGRESS),
    mock_trip("S5", TripStatus.SCHEDULED),
    mock_trip("S6", TripStatus.SCHEDULED),
    mock_trip("S7", TripStatus.SCHEDULED),
    mock_trip("S8", TripStatus.UNASSIGNED),
]
stats = DailyStatsSummary().compute(stat_trips)
print(f"""
  ┌──────────┬──────────┬──────────┬──────────┬──────────┐
  │  Total   │Completed │In Progres│Scheduled │Unassigned│
  │   {stats['total']:^6}   │   {stats['completed']:^6}   │   {stats['in_progress']:^6}   │   {stats['scheduled']:^6}   │   {stats['unassigned']:^6}   │
  └──────────┴──────────┴──────────┴──────────┴──────────┘""")
check("Total = 8",          stats["total"] == 8)
check("Completed = 3",      stats["completed"] == 3)
check("In Progress = 1",    stats["in_progress"] == 1)
check("Scheduled = 3",      stats["scheduled"] == 3)
check("Unassigned = 1",     stats["unassigned"] == 1)


# ════════════════════════════════════════════════════════
# TEST 18 — ANALYTICS (PROVIDER PORTAL)
# ════════════════════════════════════════════════════════

section("TEST 18 — Analytics Engine (Provider Portal Metrics)")
pause("Computing full analytics report...")

call_logs = [
    {"intent": "new_booking",  "booking_created": True,  "escalated": False},
    {"intent": "new_booking",  "booking_created": True,  "escalated": False},
    {"intent": "new_booking",  "booking_created": True,  "escalated": False},
    {"intent": "check_status", "booking_created": False, "escalated": False},
    {"intent": "billing",      "booking_created": False, "escalated": True,
     "escalation_reason": "insurance dispute"},
    {"intent": "modify_booking","booking_created": False,"escalated": False},
]
recs = [
    AIRecommendation(MonitoringTrigger.TRIP_CANCELLED, "cancelled", "reassign", "faster", "T-1", "D-1", 0.88, accepted=True),
    AIRecommendation(MonitoringTrigger.DRIVER_LATE,    "late",      "reassign", "faster", "T-2", "D-2", 0.72, accepted=True),
    AIRecommendation(MonitoringTrigger.NO_SHOW,        "no show",   "fill",     "better", "T-3", "D-1", 0.65, accepted=False),
    AIRecommendation(MonitoringTrigger.DRIVER_LATE,    "late again","reassign", "faster", "T-4", "D-3", 0.80, accepted=False),
]
completed_trips  = [mock_trip(f"T-C{i}", TripStatus.COMPLETED) for i in range(10)]
override_log     = [{"trip_id": "T-1", "new_driver_id": "D-2", "overridden_by": "DISP-1"}]
analytics        = AnalyticsEngine()
report           = analytics.summary(call_logs, recs, completed_trips, override_log)

print(f"""
  ┌────────────────────────────────────────────────────┐
  │              Provider Portal Metrics               │
  ├────────────────────────────────────────────────────┤
  │  Call Volume          : {report['call_volume']:<27}│
  │  Booking Conversion   : {str(report['booking_conversion'])+'%':<27}│
  │  AI Acceptance Rate   : {str(report['ai_acceptance_rate'])+'%':<27}│
  │  AI Accuracy Score    : {str(report['ai_accuracy_score'])+'%':<27}│
  │  AI Avg Confidence    : {str(report['ai_avg_confidence'])+'%':<27}│
  │  Manual Overrides     : {report['ai_overrides']:<27}│
  │  On-Time Rate         : {str(report['on_time_rate'])+'%':<27}│
  │  Escalations          : {report['escalation_count']:<27}│
  └────────────────────────────────────────────────────┘""")

check("Call volume correct",        report["call_volume"] == 6)
check("Booking conversion = 50%",   report["booking_conversion"] == 50.0)
check("AI acceptance rate present", report["ai_acceptance_rate"] > 0)
check("AI accuracy present",        "ai_accuracy_score" in report)
check("Top intents present",        "top_intents" in report)
check("Dismissed triggers tracked", len(report["top_dismissed_triggers"]) > 0)
show("Top dismissed trigger", report["top_dismissed_triggers"][0]["trigger"]
     if report["top_dismissed_triggers"] else "none")


# ════════════════════════════════════════════════════════
# TEST 19 — DISPATCH NOTIFICATIONS
# ════════════════════════════════════════════════════════

section("TEST 19 — Dispatch Notifications")
pause("Building driver notification payloads...")

notifier = DispatchNotifier()
driver   = mock_driver()
trip     = mock_trip()

push = notifier.assignment_push(driver, trip)
show("Push notification", json.dumps(push, indent=2).replace("\n", "\n              "))
check("Push has driver_id",         "driver_id" in push)
check("Push has title",             push["title"] == "New Trip Assigned")
check("Push has trip data",         push["data"]["trip_id"] == trip.id)

escalation = notifier.escalation_alert(driver, trip)
show("Escalation alert",  escalation["message"])
check("Escalation has message",     "not acknowledged" in escalation["message"])


# ════════════════════════════════════════════════════════
# TEST 20 — FACTORY WIRING (END-TO-END SMOKE)
# ════════════════════════════════════════════════════════

section("TEST 20 — End-to-End Factory Smoke Test")
pause("Initializing all factories...")

r = VapiReceptionistFactory.create()
check("VapiReceptionistFactory",    all(k in r for k in ["assistant_config","webhook_handler","sms_service"]))

live_ai = LiveDispatchFactory.create()
check("LiveDispatchFactory",        all(k in live_ai for k in
    ["auto_assigner","monitoring_engine","smart_router","dispatch_notifier","override_handler"]))

sched_ai = DailyScheduleFactory.create()
check("DailyScheduleFactory",       all(k in sched_ai for k in
    ["schedule_optimizer","conflict_detector","capacity_planner","unassigned_sidebar","daily_stats"]))

# Run a mini end-to-end flow
flow_e2e = r["webhook_handler"]
trip_e2e = mock_trip()
drivers_e2e = mock_drivers()

r1 = flow_e2e.handle({"type": "call.started", "call": {"customer": {"number": "+15551234567"}}})
r2 = flow_e2e.handle({"type": "transcript.partial", "transcript": "I need to book a ride"})
r3 = live_ai["auto_assigner"].assign_single(trip_e2e, drivers_e2e)
r4 = live_ai["monitoring_engine"].process_event(
    MonitoringTrigger.DRIVER_LATE, trip_e2e, drivers_e2e, {"delay_minutes": 10}
)
check("E2E: call.started handled",  r1.get("action") == "lookup_passenger")
check("E2E: intent classified",     "intent" in r2)
check("E2E: driver assigned",       r3 is not None)
check("E2E: monitoring triggered",  bool(r4.what_happened))
show("E2E flow result",
     f"Call handled → Intent: {r2['intent']} → Driver: {r3['recommended_driver_name']} "
     f"({r3['confidence']}%) → Alert: {r4.what_happened[:50]}...")


# ════════════════════════════════════════════════════════
# FINAL SUMMARY
# ════════════════════════════════════════════════════════

total = passed + failed + skipped
bar_pass  = "█" * int(passed / total * 40) if total else ""
bar_fail  = "█" * int(failed / total * 40) if total else ""
bar_skip  = "░" * int(skipped / total * 40) if total else ""

print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════════════════════╗
║                   TEST SUMMARY                       ║
╠══════════════════════════════════════════════════════╣
║  {GREEN}Passed {RESET}{BOLD} : {passed:<4}{CYAN}                                      ║
║  {RED}Failed {RESET}{BOLD} : {failed:<4}{CYAN}                                      ║
║  {YELLOW}Skipped{RESET}{BOLD} : {skipped:<4}{CYAN} (live-mode only)                      ║
║  Total  : {total:<4}                                      ║
╠══════════════════════════════════════════════════════╣{RESET}""")

if failed == 0:
    print(f"{BOLD}{CYAN}║  {GREEN}✓ ALL TESTS PASSED — Ready to hand off to backend.{CYAN}  ║{RESET}")
else:
    print(f"{BOLD}{CYAN}║  {RED}✗ {failed} test(s) failed — review output above.{CYAN}      ║{RESET}")

if not LIVE_MODE:
    print(f"{BOLD}{CYAN}║  {YELLOW}ℹ  Run with --live for real API tests.{CYAN}              ║{RESET}")

print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════╝{RESET}\n")