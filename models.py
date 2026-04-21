"""
HealthRide AI — Data Models & Enums
All shared data structures used across every AI module.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


# ─────────────────────────────────────────
# Enums
# ─────────────────────────────────────────

class VehicleType(str, Enum):
    SEDAN       = "sedan"
    WHEELCHAIR_VAN = "wheelchair_van"
    STRETCHER   = "stretcher"
    AMBULATORY  = "ambulatory"


class TripStatus(str, Enum):
    UNASSIGNED  = "unassigned"
    SCHEDULED   = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"


class DriverStatus(str, Enum):
    AVAILABLE       = "available"
    EN_ROUTE        = "en_route"
    WITH_PASSENGER  = "with_passenger"
    ON_BREAK        = "on_break"
    OFFLINE         = "offline"


class AutomationLevel(str, Enum):
    MANUAL      = "manual"       # AI suggests → provider approves
    ONE_CLICK   = "one_click"    # Queue up → batch approve
    AUTOMATIC   = "automatic"    # AI acts → notifies after


class OptimizationMode(str, Enum):
    EFFICIENT   = "efficient"    # Max trips, always meet appointment times
    BALANCED    = "balanced"     # Moderate with driver breaks
    RELAXED     = "relaxed"      # Fewer trips, more breathing room


class CallIntent(str, Enum):
    NEW_BOOKING     = "new_booking"
    MODIFY_BOOKING  = "modify_booking"
    CANCEL_BOOKING  = "cancel_booking"
    CHECK_STATUS    = "check_status"
    BILLING         = "billing"
    EMERGENCY       = "emergency"
    COMPLEX         = "complex"
    UNKNOWN         = "unknown"


class MonitoringTrigger(str, Enum):
    TRIP_CANCELLED      = "trip_cancelled"
    DRIVER_LATE         = "driver_late"
    NO_SHOW             = "no_show"
    LAST_MINUTE_TRIP    = "last_minute_trip"
    VEHICLE_ISSUE       = "vehicle_issue"
    TRAFFIC_DELAY       = "traffic_delay"


# ─────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────

@dataclass
class Location:
    address: str
    lat: float
    lng: float


@dataclass
class Passenger:
    id: str
    name: str
    phone: str
    saved_addresses: list[Location]     = field(default_factory=list)
    vehicle_requirement: VehicleType    = VehicleType.SEDAN
    hipaa_consent: bool                 = False
    notes: str                          = ""


@dataclass
class Driver:
    id: str
    name: str
    vehicle_type: VehicleType
    status: DriverStatus
    location: Location
    performance_rating: float               # 0.0 – 5.0
    active_trip_id: Optional[str]       = None
    specializations: list[str]          = field(default_factory=list)


@dataclass
class Trip:
    id: str
    passenger: Passenger
    pickup: Location
    dropoff: Location
    pickup_time: datetime
    appointment_time: Optional[datetime]
    vehicle_type: VehicleType
    status: TripStatus                  = TripStatus.UNASSIGNED
    assigned_driver_id: Optional[str]   = None
    estimated_duration_min: int         = 0
    notes: str                          = ""


@dataclass
class AIRecommendation:
    trigger: MonitoringTrigger
    what_happened: str
    what_to_change: str
    why_it_helps: str
    trip_id: str
    suggested_driver_id: Optional[str]
    confidence: float                   # 0.0 – 1.0
    accepted: Optional[bool]            = None
