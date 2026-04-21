"""
HealthRide AI — Central Config
Loads all environment variables from .env via python-decouple.
Every module imports from here — never reads os.environ directly.

Install: pip install python-decouple
"""

from decouple import config


class Config:
    # ─── Vapi ──────────────────────────────────────
    VAPI_API_KEY:               str = config("VAPI_API_KEY")
    VAPI_PHONE_NUMBER:          str = config("VAPI_PHONE_NUMBER")
    VAPI_WEBHOOK_SECRET:        str = config("VAPI_WEBHOOK_SECRET")

    # ─── Twilio ────────────────────────────────────
    TWILIO_ACCOUNT_SID:         str = config("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN:          str = config("TWILIO_AUTH_TOKEN")
    TWILIO_PHONE_NUMBER:        str = config("TWILIO_PHONE_NUMBER")

    # ─── Google Maps ───────────────────────────────
    GOOGLE_MAPS_API_KEY:        str = config("GOOGLE_MAPS_API_KEY")

    # ─── OpenAI ────────────────────────────────────
    OPENAI_API_KEY:             str = config("OPENAI_API_KEY")

    # ─── Business Hours ────────────────────────────
    BUSINESS_HOURS_START:       int = config("BUSINESS_HOURS_START", default=8,  cast=int)
    BUSINESS_HOURS_END:         int = config("BUSINESS_HOURS_END",   default=18, cast=int)

    # ─── AI Defaults ───────────────────────────────
    DEFAULT_AUTOMATION_LEVEL:   str = config("DEFAULT_AUTOMATION_LEVEL",  default="manual")
    DEFAULT_OPTIMIZATION_MODE:  str = config("DEFAULT_OPTIMIZATION_MODE", default="efficient")
    ACK_TIMEOUT_MIN:            int = config("DRIVER_ACKNOWLEDGMENT_TIMEOUT_MIN", default=5, cast=int)
