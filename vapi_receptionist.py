"""
HealthRide AI — Part 1: Vapi Phone Receptionist
24/7 AI call handling, booking, routing, and SMS confirmation.
"""

import re
import hmac
import hashlib
from typing import Optional
from datetime import datetime

from config import Config
from models import CallIntent, Passenger, Trip, VehicleType, TripStatus, Location


# ─────────────────────────────────────────
# Vapi Assistant Configuration
# ─────────────────────────────────────────

class VapiAssistantConfig:
    """Builds the Vapi assistant payload. Push to Vapi API on startup."""

    SYSTEM_PROMPT = """
You are the HealthRide AI receptionist — a professional, empathetic voice assistant
for a medical transportation company.

Rules:
- Always verify caller identity before making any changes to existing bookings.
- Collect ALL required booking fields before confirming any booking.
- Never repeat full SSN, insurance numbers, or sensitive data aloud.
- If a request is too complex or caller is distressed, escalate to a human immediately.
- Keep responses brief, calm, and clear.
- Always read back all booking details to the caller before finalizing.
- Collect appointment time as a separate field from pickup time.
"""

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "lookup_passenger",
                "description": "Look up a passenger by their phone number",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string", "description": "Caller phone number"}
                    },
                    "required": ["phone"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "register_new_passenger",
                "description": "Register a brand new passenger and collect HIPAA verbal consent",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name":                 {"type": "string"},
                        "phone":                {"type": "string"},
                        "vehicle_requirement":  {"type": "string", "enum": ["sedan", "wheelchair_van", "stretcher", "ambulatory"]},
                        "hipaa_consent":        {"type": "boolean", "description": "Did caller verbally consent to HIPAA terms?"}
                    },
                    "required": ["name", "phone", "hipaa_consent"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_booking",
                "description": "Create a new trip after all fields are collected and confirmed",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "passenger_id":      {"type": "string"},
                        "pickup_address":    {"type": "string"},
                        "dropoff_address":   {"type": "string"},
                        "pickup_time":       {"type": "string", "description": "ISO 8601 datetime"},
                        "appointment_time":  {"type": "string", "description": "ISO 8601 datetime — patient's actual appointment time"},
                        "vehicle_type":      {"type": "string", "enum": ["sedan", "wheelchair_van", "stretcher", "ambulatory"]},
                        "special_requirements": {"type": "string", "description": "e.g. oxygen, stretcher, wheelchair"}
                    },
                    "required": ["passenger_id", "pickup_address", "dropoff_address", "pickup_time"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "modify_booking",
                "description": "Modify an existing booking after identity is verified",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trip_id":          {"type": "string"},
                        "passenger_id":     {"type": "string"},
                        "field_to_change":  {"type": "string", "enum": ["pickup_address", "dropoff_address", "pickup_time", "vehicle_type", "special_requirements"]},
                        "new_value":        {"type": "string"}
                    },
                    "required": ["trip_id", "passenger_id", "field_to_change", "new_value"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_booking",
                "description": "Cancel a booking after identity is verified",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trip_id":      {"type": "string"},
                        "passenger_id": {"type": "string"}
                    },
                    "required": ["trip_id", "passenger_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_trip_status",
                "description": "Get real-time driver ETA and trip status for an active trip",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trip_id":      {"type": "string"},
                        "passenger_id": {"type": "string"}
                    },
                    "required": ["trip_id", "passenger_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "transfer_call",
                "description": "Transfer call to human staff",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason":       {"type": "string"},
                        "destination":  {"type": "string", "enum": ["dispatcher", "billing", "emergency"]}
                    },
                    "required": ["reason", "destination"]
                }
            }
        }
    ]

    @classmethod
    def build(cls) -> dict:
        return {
            "model": {
                "provider":     "openai",
                "model":        "gpt-4o",
                "systemPrompt": cls.SYSTEM_PROMPT,
                "tools":        cls.TOOLS
            },
            "voice": {
                "provider": "playht",
                "voiceId":  "jennifer-playht"
            },
            "transcriber": {
                "provider": "deepgram",
                "model":    "nova-2",
                "language": "en-US"
            },
            "phoneNumber":      Config.VAPI_PHONE_NUMBER,
            "recordingEnabled": True,
            "hipaaEnabled":     True,
            "firstMessage": (
                "Thank you for calling HealthRide. "
                "I'm your AI assistant. How can I help you today?"
            )
        }


# ─────────────────────────────────────────
# Intent Classifier
# ─────────────────────────────────────────

class IntentClassifier:
    """Classifies caller intent from transcript text using keyword matching."""

    INTENT_PATTERNS: dict[CallIntent, list[str]] = {
        CallIntent.NEW_BOOKING:     ["book", "schedule", "need a ride", "pickup", "appointment", "reserve"],
        CallIntent.MODIFY_BOOKING:  ["change", "modify", "update", "move", "reschedule", "different time"],
        CallIntent.CANCEL_BOOKING:  ["cancel", "cancellation", "remove", "don't need", "wont need"],
        CallIntent.CHECK_STATUS:    ["where", "eta", "how long", "status", "driver", "on the way"],
        CallIntent.BILLING:         ["bill", "invoice", "payment", "charge", "insurance", "cost"],
        CallIntent.EMERGENCY:       ["emergency", "911", "urgent", "help", "hurt", "accident"],
    }

    def classify(self, transcript: str) -> CallIntent:
        lower = transcript.lower()
        for intent, keywords in self.INTENT_PATTERNS.items():
            if any(kw in lower for kw in keywords):
                return intent
        return CallIntent.UNKNOWN


# ─────────────────────────────────────────
# Call Router
# ─────────────────────────────────────────

class CallRouter:
    """Routes calls to the correct handler based on intent and business hours."""

    ROUTING_TABLE: dict[CallIntent, dict] = {
        CallIntent.EMERGENCY:       {"action": "transfer", "destination": "emergency",   "priority": "immediate"},
        CallIntent.BILLING:         {"action": "transfer", "destination": "billing"},
        CallIntent.COMPLEX:         {"action": "transfer", "destination": "dispatcher"},
        CallIntent.NEW_BOOKING:     {"action": "ai_handle", "flow": "booking"},
        CallIntent.MODIFY_BOOKING:  {"action": "ai_handle", "flow": "modification"},
        CallIntent.CANCEL_BOOKING:  {"action": "ai_handle", "flow": "modification"},
        CallIntent.CHECK_STATUS:    {"action": "ai_handle", "flow": "status"},
    }

    def __init__(self):
        self.start_hour = Config.BUSINESS_HOURS_START
        self.end_hour   = Config.BUSINESS_HOURS_END

    def is_business_hours(self) -> bool:
        return self.start_hour <= datetime.now().hour < self.end_hour

    def route(self, intent: CallIntent) -> dict:
        if intent in self.ROUTING_TABLE:
            return self.ROUTING_TABLE[intent]
        # Unknown intent fallback
        if self.is_business_hours():
            return {"action": "transfer", "destination": "dispatcher"}
        return {"action": "voicemail"}


# ─────────────────────────────────────────
# Booking Flow Handler
# ─────────────────────────────────────────

class BookingFlowHandler:
    """
    Step-by-step booking conversation.
    Each step validates its input before advancing to the next.
    Covers all required fields from the requirements doc.
    """

    STEPS = [
        "verify_passenger",         # phone → lookup or register
        "collect_pickup",           # pickup address
        "collect_dropoff",          # destination address
        "collect_pickup_time",      # date & time of ride
        "collect_appointment_time", # patient's actual appointment time
        "collect_requirements",     # wheelchair / oxygen / stretcher etc.
        "confirm_details",          # read everything back
        "finalize"                  # create booking
    ]

    def __init__(self):
        self.state: dict    = {}
        self.current_step   = 0

    @property
    def step(self) -> str:
        return self.STEPS[self.current_step]

    def advance(self, input_data: dict) -> dict:
        handler = getattr(self, f"_step_{self.step}")
        result  = handler(input_data)
        if result.get("valid"):
            self.current_step = min(self.current_step + 1, len(self.STEPS) - 1)
        return result

    # ── Individual Steps ──────────────────

    def _step_verify_passenger(self, data: dict) -> dict:
        phone = data.get("phone", "")
        if re.match(r"^\+?[\d\s\-]{10,15}$", phone):
            self.state["phone"] = phone
            return {"valid": True, "prompt": "Got it. Let me pull up your record."}
        return {"valid": False, "prompt": "Could you repeat your phone number please?"}

    def _step_collect_pickup(self, data: dict) -> dict:
        address = data.get("pickup_address", "")
        if len(address) > 5:
            self.state["pickup_address"] = address
            return {"valid": True, "prompt": "And where are you going?"}
        return {"valid": False, "prompt": "I didn't catch the pickup address. Could you repeat it?"}

    def _step_collect_dropoff(self, data: dict) -> dict:
        address = data.get("dropoff_address", "")
        if len(address) > 5:
            self.state["dropoff_address"] = address
            return {"valid": True, "prompt": "What date and time do you need to be picked up?"}
        return {"valid": False, "prompt": "Could you repeat the destination address?"}

    def _step_collect_pickup_time(self, data: dict) -> dict:
        dt = data.get("pickup_time", "")
        if dt:
            self.state["pickup_time"] = dt
            return {"valid": True, "prompt": "And what time is your actual appointment?"}
        return {"valid": False, "prompt": "What date and time do you need the ride?"}

    def _step_collect_appointment_time(self, data: dict) -> dict:
        apt = data.get("appointment_time", "")
        if apt:
            self.state["appointment_time"] = apt
        else:
            self.state["appointment_time"] = None   # optional — skip if not applicable
        return {"valid": True, "prompt": "Do you have any special requirements — wheelchair, oxygen, or stretcher?"}

    def _step_collect_requirements(self, data: dict) -> dict:
        self.state["special_requirements"] = data.get("requirements", "none")
        self.state["vehicle_type"]         = data.get("vehicle_type", "sedan")
        return {"valid": True, "prompt": self._build_confirmation_prompt()}

    def _step_confirm_details(self, data: dict) -> dict:
        if data.get("confirmed"):
            return {"valid": True, "prompt": "Booking confirmed! You will receive an SMS confirmation shortly."}
        return {"valid": False, "prompt": "What would you like to change?"}

    def _step_finalize(self, data: dict) -> dict:
        return {"valid": True, "booking_data": self.state, "complete": True}

    def _build_confirmation_prompt(self) -> str:
        s = self.state
        apt = f", appointment at {s.get('appointment_time')}" if s.get("appointment_time") else ""
        return (
            f"Let me confirm — Pickup from {s.get('pickup_address')}, "
            f"going to {s.get('dropoff_address')}, "
            f"pickup at {s.get('pickup_time')}{apt}, "
            f"requirements: {s.get('special_requirements')}. "
            "Is that all correct?"
        )


# ─────────────────────────────────────────
# Identity Verifier
# ─────────────────────────────────────────

class IdentityVerifier:
    """Verifies caller identity before allowing modifications or cancellations."""

    def verify(self, caller_phone: str, passenger: Passenger) -> bool:
        normalized_caller  = re.sub(r"\D", "", caller_phone)
        normalized_record  = re.sub(r"\D", "", passenger.phone)
        return normalized_caller == normalized_record


# ─────────────────────────────────────────
# Webhook Signature Verifier
# ─────────────────────────────────────────

class WebhookVerifier:
    """Verifies that incoming Vapi webhook requests are authentic."""

    def verify(self, payload: bytes, signature: str) -> bool:
        expected = hmac.new(
            Config.VAPI_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


# ─────────────────────────────────────────
# Vapi Webhook Handler
# ─────────────────────────────────────────

class VapiWebhookHandler:
    """
    Processes all inbound Vapi webhook events.
    Backend dev maps handle() to a Django POST endpoint.
    """

    def __init__(
        self,
        intent_classifier:  IntentClassifier,
        call_router:        CallRouter,
        booking_flow:       BookingFlowHandler,
        identity_verifier:  IdentityVerifier,
        webhook_verifier:   WebhookVerifier
    ):
        self.classifier         = intent_classifier
        self.router             = call_router
        self.booking            = booking_flow
        self.identity_verifier  = identity_verifier
        self.webhook_verifier   = webhook_verifier

    def handle(self, event: dict, raw_payload: bytes = b"", signature: str = "") -> dict:
        if signature and not self.webhook_verifier.verify(raw_payload, signature):
            return {"status": "unauthorized"}

        handlers = {
            "call.started":         self._on_call_started,
            "transcript.partial":   self._on_transcript,
            "function.call":        self._on_function_call,
            "call.ended":           self._on_call_ended,
        }
        handler = handlers.get(event.get("type"))
        return handler(event) if handler else {"status": "unhandled", "type": event.get("type")}

    def _on_call_started(self, event: dict) -> dict:
        phone = event.get("call", {}).get("customer", {}).get("number", "")
        return {"action": "lookup_passenger", "phone": phone}

    def _on_transcript(self, event: dict) -> dict:
        transcript  = event.get("transcript", "")
        intent      = self.classifier.classify(transcript)
        route       = self.router.route(intent)
        return {"intent": intent.value, "route": route}

    def _on_function_call(self, event: dict) -> dict:
        fn      = event.get("functionCall", {})
        return {"function": fn.get("name"), "params": fn.get("parameters", {}), "status": "dispatch_to_service"}

    def _on_call_ended(self, event: dict) -> dict:
        call = event.get("call", {})
        return {"call_id": call.get("id"), "duration": call.get("duration"), "action": "log_and_store"}


# ─────────────────────────────────────────
# SMS Confirmation Service
# ─────────────────────────────────────────

class SMSConfirmationService:
    """
    Builds HIPAA-compliant SMS message strings.
    Backend dev passes the returned string to Twilio client.
    Sender number loaded from Config.
    """

    @property
    def from_number(self) -> str:
        return Config.TWILIO_PHONE_NUMBER

    def booking_confirmation(self, trip: Trip, confirmation_number: str) -> dict:
        return {
            "from": self.from_number,
            "body": (
                f"HealthRide Confirmation #{confirmation_number}\n"
                f"Pickup: {trip.pickup.address}\n"
                f"To: {trip.dropoff.address}\n"
                f"Time: {trip.pickup_time.strftime('%b %d, %I:%M %p')}\n"
                "Reply CANCEL to cancel. Reply HELP for assistance."
            )
        }

    def cancellation_confirmation(self, trip_id: str) -> dict:
        return {
            "from": self.from_number,
            "body": f"HealthRide: Trip #{trip_id} has been cancelled. Call us to rebook."
        }

    def driver_eta(self, driver_name: str, eta_minutes: int) -> dict:
        return {
            "from": self.from_number,
            "body": f"HealthRide: Your driver {driver_name} is {eta_minutes} min away."
        }


# ─────────────────────────────────────────
# Factory
# ─────────────────────────────────────────

class VapiReceptionistFactory:
    """Single entry point — backend dev calls create() once."""

    @staticmethod
    def create() -> dict:
        return {
            "assistant_config": VapiAssistantConfig.build(),
            "webhook_handler":  VapiWebhookHandler(
                intent_classifier   = IntentClassifier(),
                call_router         = CallRouter(),
                booking_flow        = BookingFlowHandler(),
                identity_verifier   = IdentityVerifier(),
                webhook_verifier    = WebhookVerifier()
            ),
            "sms_service": SMSConfirmationService()
        }
