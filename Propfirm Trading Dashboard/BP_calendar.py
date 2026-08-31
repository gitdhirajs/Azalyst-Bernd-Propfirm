"""Economic Calendar & Holiday Blackout Engine.

Implements audit gap #4 (MASTER_FINDINGS.md):
  - US federal holiday two-session gate (CLAUDE.md rule #26)
  - High-impact news blackout: CPI, FOMC, NFP, ECB, BoE, GDP, retail sales, PMI
    within ±2 hours = suppress signals (reduce risk or skip entirely)
  - Thanksgiving + Christmas week COT freshness suppression (CLAUDE.md rule #27)
  - Blackout detection returns structured warnings for BP_rules_engine

Bernd checks the economic calendar at every session open per the Funded
Trader weekly outlook recordings. High-impact events in the next trading
window = either skip the trade or reduce size to 0.5%.

Data sources (in priority order):
  1. Hard-coded 2025-2026 calendar of known high-impact dates (NFP, FOMC, CPI, etc.)
  2. Rule-based recurring patterns (first Friday = NFP, mid-month = CPI, etc.)
  3. Optional live fetch from ForexFactory RSS (to be added in a future release)

Usage:
    from BP_calendar import EconomicCalendar
    cal = EconomicCalendar()
    blackout = cal.check_blackout(datetime.now())
    if blackout.in_blackout:
        print(f"Cannot trade: {blackout.reason}")
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


# ========================================================================
# Data model
# ========================================================================

class EventImpact(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EventType(str, Enum):
    ECONOMIC = "economic"       # data release (NFP, CPI, GDP, etc.)
    CENTRAL_BANK = "cbank"      # rate decision / minutes (FOMC, ECB, BoE)
    HOLIDAY = "holiday"         # market closed or half-day
    EARNINGS = "earnings"       # (future) major earnings


@dataclass
class CalendarEvent:
    """A single economic-calendar entry."""
    title: str
    event_type: EventType
    impact: EventImpact
    timestamp: datetime           # scheduled release datetime (UTC)
    duration_minutes: int = 120   # blackout window (± from timestamp)
    currency: str = "USD"
    description: str = ""
    recurring_rule: str = ""      # e.g. "first_friday", "mid_month_wed"

    def blackout_start(self) -> datetime:
        return self.timestamp - timedelta(minutes=self.duration_minutes)

    def blackout_end(self) -> datetime:
        return self.timestamp + timedelta(minutes=self.duration_minutes)

    def overlaps(self, when: datetime) -> bool:
        return self.blackout_start() <= when <= self.blackout_end()

    def to_dict(self) -> Dict:
        return {
            'title': self.title,
            'type': self.event_type.value,
            'impact': self.impact.value,
            'timestamp': self.timestamp.isoformat(),
            'currency': self.currency,
            'description': self.description,
        }


@dataclass
class BlackoutStatus:
    """Result of a calendar blackout check."""
    in_blackout: bool = False
    blackout_events: List[CalendarEvent] = field(default_factory=list)
    reason: str = ""
    risk_multiplier: float = 1.0          # 1.0 = normal, 0.5 = reduced, 0.0 = skip
    cot_suppressed: bool = False          # Thanksgiving / Christmas week
    holiday_season: bool = False          # thin liquidity period

    def to_dict(self) -> Dict:
        return {
            'in_blackout': self.in_blackout,
            'blackout_events': [e.to_dict() for e in self.blackout_events],
            'reason': self.reason,
            'risk_multiplier': self.risk_multiplier,
            'cot_suppressed': self.cot_suppressed,
            'holiday_season': self.holiday_season,
        }


# ========================================================================
# Static event database — 2025 high-impact dates
# ========================================================================

# NFP: first Friday of each month, 8:30 AM ET (13:30 UTC)
# CPI: ~mid-month Tuesday-Thursday, 8:30 AM ET
# FOMC: 8 meetings/year, Wednesdays 2:00 PM ET (19:00 UTC)
# GDP: quarterly, ~end of month, 8:30 AM ET
# Retail Sales: ~mid-month, 8:30 AM ET
# PPI: ~mid-month, day after CPI sometimes
# ECB: every ~6 weeks, Thursdays 14:15 CET (13:15 UTC)

# Hardcoded 2025 dates (ET → UTC: ET+5, EDT+4)
# Trading hours blackout: ±2 hours from release = 4-hour window

_ET_TO_UTC = 5   # Eastern Standard Time offset (ET = UTC-5)

def _et(hour: int, minute: int = 0) -> time:
    """Eastern Time → UTC hour (standard time). Adjust for DST in the caller."""
    h = (hour + _ET_TO_UTC) % 24
    return time(h, minute)


_HIGH_IMPACT_2025: List[CalendarEvent] = [
    # ---- NFP (first Friday) ----
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 1, 10, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 2, 7, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 3, 7, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 4, 4, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 5, 2, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 6, 6, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 7, 3, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 8, 1, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 9, 5, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 10, 3, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 11, 7, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 12, 5, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="first_friday"),

    # ---- CPI (approx mid-month, typically Wed/Thu) ----
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 1, 15, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 2, 12, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 3, 12, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 4, 10, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 5, 14, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 6, 11, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 7, 15, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 8, 13, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 9, 11, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 10, 15, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 11, 13, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 12, 10, _et(8,30).hour, _et(8,30).minute),
                  currency="USD", recurring_rule="mid_month"),

    # ---- FOMC (8 meetings in 2025, Wednesdays 2:00 PM ET = 19:00 UTC) ----
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 1, 29, 19, 0),
                  duration_minutes=180, currency="USD",
                  description="FOMC statement + press conference"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 3, 19, 19, 0),
                  duration_minutes=180, currency="USD",
                  description="FOMC statement + press conference"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 5, 7, 19, 0),
                  duration_minutes=180, currency="USD",
                  description="FOMC statement + press conference"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 6, 18, 19, 0),
                  duration_minutes=180, currency="USD",
                  description="FOMC statement + press conference"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 7, 30, 19, 0),
                  duration_minutes=180, currency="USD",
                  description="FOMC statement + press conference"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 9, 17, 19, 0),
                  duration_minutes=180, currency="USD",
                  description="FOMC statement + press conference"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 11, 5, 19, 0),
                  duration_minutes=180, currency="USD",
                  description="FOMC statement + press conference"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 12, 17, 19, 0),
                  duration_minutes=180, currency="USD",
                  description="FOMC statement + press conference"),

    # ---- FOMC Minutes (3 weeks after each decision, Wednesdays 2:00 PM) ----
    CalendarEvent("FOMC Minutes", EventType.CENTRAL_BANK, EventImpact.MEDIUM,
                  datetime(2025, 2, 19, 19, 0),
                  duration_minutes=120, currency="USD"),
    CalendarEvent("FOMC Minutes", EventType.CENTRAL_BANK, EventImpact.MEDIUM,
                  datetime(2025, 4, 9, 19, 0),
                  duration_minutes=120, currency="USD"),
    CalendarEvent("FOMC Minutes", EventType.CENTRAL_BANK, EventImpact.MEDIUM,
                  datetime(2025, 5, 28, 19, 0),
                  duration_minutes=120, currency="USD"),
    CalendarEvent("FOMC Minutes", EventType.CENTRAL_BANK, EventImpact.MEDIUM,
                  datetime(2025, 7, 9, 19, 0),
                  duration_minutes=120, currency="USD"),
    CalendarEvent("FOMC Minutes", EventType.CENTRAL_BANK, EventImpact.MEDIUM,
                  datetime(2025, 8, 20, 19, 0),
                  duration_minutes=120, currency="USD"),
    CalendarEvent("FOMC Minutes", EventType.CENTRAL_BANK, EventImpact.MEDIUM,
                  datetime(2025, 10, 8, 19, 0),
                  duration_minutes=120, currency="USD"),
    CalendarEvent("FOMC Minutes", EventType.CENTRAL_BANK, EventImpact.MEDIUM,
                  datetime(2025, 11, 26, 19, 0),
                  duration_minutes=120, currency="USD"),

    # ---- PPI (Producer Price Index, usually day before or after CPI) ----
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 1, 14, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 2, 13, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 3, 13, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 4, 11, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 5, 15, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 6, 13, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 7, 11, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 8, 12, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 9, 12, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 10, 14, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 11, 14, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("PPI (Producer Price Index)", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 12, 12, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),

    # ---- Retail Sales (mid-month, 8:30 AM ET) ----
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 1, 16, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 2, 14, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 3, 17, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 4, 16, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 5, 15, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 6, 17, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 7, 16, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 8, 15, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 9, 16, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 10, 16, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 11, 14, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("Retail Sales", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 12, 16, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),

    # ---- GDP (quarterly, advance estimate ~end of month) ----
    CalendarEvent("GDP (Quarterly Advance)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 1, 30, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("GDP (Quarterly Advance)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 4, 30, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("GDP (Quarterly Advance)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 7, 30, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),
    CalendarEvent("GDP (Quarterly Advance)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2025, 10, 29, _et(8,30).hour, _et(8,30).minute),
                  currency="USD"),

    # ---- ECB Rate Decisions (every ~6 weeks, 14:15 CET = 13:15 UTC) ----
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 1, 30, 13, 15),
                  duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 3, 6, 13, 15),
                  duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 4, 17, 13, 15),
                  duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 6, 5, 13, 15),
                  duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 7, 24, 13, 15),
                  duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 9, 11, 13, 15),
                  duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 10, 23, 13, 15),
                  duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 12, 11, 13, 15),
                  duration_minutes=180, currency="EUR"),

    # ---- BoE Rate Decisions (every ~6 weeks, Thursdays 12:00 GMT) ----
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 2, 6, 12, 0),
                  duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 3, 20, 12, 0),
                  duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 5, 8, 12, 0),
                  duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 6, 19, 12, 0),
                  duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 8, 7, 12, 0),
                  duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 9, 18, 12, 0),
                  duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 11, 6, 12, 0),
                  duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2025, 12, 18, 12, 0),
                  duration_minutes=180, currency="GBP"),

    # ---- ISM Manufacturing PMI (first business day of month, 10:00 AM ET) ----
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 1, 2, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 2, 3, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 3, 3, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 4, 1, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 5, 1, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 6, 2, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 7, 1, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 8, 1, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 9, 2, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 10, 1, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 11, 3, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
    CalendarEvent("ISM Manufacturing PMI", EventType.ECONOMIC, EventImpact.MEDIUM,
                  datetime(2025, 12, 1, _et(10).hour, _et(10).minute),
                  currency="USD", recurring_rule="first_business_day"),
]

# ========================================================================
# FIX Bug 5: 2026 high-impact calendar dates
# ========================================================================
_HIGH_IMPACT_2026: List[CalendarEvent] = [
    # ---- NFP 2026 (first Friday of each month) ----
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 1, 9,  _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 2, 6,  _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 3, 6,  _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 4, 3,  _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 5, 1,  _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 6, 5,  _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 7, 2,  _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 8, 7,  _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 9, 4,  _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 10, 2, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 11, 6, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 12, 4, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    # ---- CPI 2026 ----
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 1, 14, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 2, 11, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 3, 11, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 4, 15, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 5, 13, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 6, 10, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 7, 15, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 8, 12, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 9, 9,  _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 10, 14, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 11, 12, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("CPI (Consumer Price Index)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 12, 9, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    # ---- FOMC 2026 (8 meetings, Wednesdays 19:00 UTC) ----
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 1, 28, 19, 0), duration_minutes=180, currency="USD"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 3, 18, 19, 0), duration_minutes=180, currency="USD"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 5, 6,  19, 0), duration_minutes=180, currency="USD"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 6, 17, 19, 0), duration_minutes=180, currency="USD"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 7, 29, 19, 0), duration_minutes=180, currency="USD"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 9, 16, 19, 0), duration_minutes=180, currency="USD"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 11, 4, 19, 0), duration_minutes=180, currency="USD"),
    CalendarEvent("FOMC Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 12, 16, 19, 0), duration_minutes=180, currency="USD"),
    # ---- ECB 2026 (every ~6 weeks, Thursdays 13:15 UTC) ----
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 1, 22, 13, 15), duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 3, 5,  13, 15), duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 4, 16, 13, 15), duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 6, 4,  13, 15), duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 7, 23, 13, 15), duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 9, 10, 13, 15), duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 10, 22, 13, 15), duration_minutes=180, currency="EUR"),
    CalendarEvent("ECB Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 12, 10, 13, 15), duration_minutes=180, currency="EUR"),
    # ---- BoE 2026 (every ~6 weeks, Thursdays 12:00 UTC) ----
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 2, 5,  12, 0), duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 3, 19, 12, 0), duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 5, 7,  12, 0), duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 6, 18, 12, 0), duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 8, 6,  12, 0), duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 9, 17, 12, 0), duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 11, 5, 12, 0), duration_minutes=180, currency="GBP"),
    CalendarEvent("BoE Rate Decision", EventType.CENTRAL_BANK, EventImpact.HIGH,
                  datetime(2026, 12, 17, 12, 0), duration_minutes=180, currency="GBP"),
    # ---- GDP 2026 (quarterly, ~end of Jan/Apr/Jul/Oct) ----
    CalendarEvent("GDP (Quarterly Advance)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 1, 29, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("GDP (Quarterly Advance)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 4, 29, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("GDP (Quarterly Advance)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 7, 29, _et(8,30).hour, _et(8,30).minute), currency="USD"),
    CalendarEvent("GDP (Quarterly Advance)", EventType.ECONOMIC, EventImpact.HIGH,
                  datetime(2026, 10, 28, _et(8,30).hour, _et(8,30).minute), currency="USD"),
]


# ========================================================================
# US Federal Holidays (market closed) — 2025
# ========================================================================

def _date_utc(y: int, m: int, d: int) -> datetime:
    """Midnight UTC on a given date."""
    return datetime(y, m, d, 0, 0, 0)


_US_FEDERAL_HOLIDAYS_2025: List[Tuple[date, str, bool]] = [
    # (date, name, market_closed)
    # NYSE observes all of these. CME futures trade abbreviated hours on some.
    (date(2025, 1, 1),   "New Year's Day",          True),
    (date(2025, 1, 20),  "Martin Luther King Jr Day",True),
    (date(2025, 2, 17),  "Presidents' Day",          True),
    (date(2025, 4, 18),  "Good Friday",              True),   # early close 9:30-12:00
    (date(2025, 5, 26),  "Memorial Day",             True),
    (date(2025, 6, 19),  "Juneteenth",               True),
    (date(2025, 7, 4),   "Independence Day",         True),
    (date(2025, 9, 1),   "Labor Day",                True),
    (date(2025, 11, 27), "Thanksgiving",             True),   # closed Thu + early close Fri
    (date(2025, 12, 25), "Christmas",                True),
]

# FIX Bug 5: 2026 US federal holidays
_US_FEDERAL_HOLIDAYS_2026: List[Tuple[date, str, bool]] = [
    (date(2026, 1, 1),   "New Year's Day",           True),
    (date(2026, 1, 19),  "Martin Luther King Jr Day", True),
    (date(2026, 2, 16),  "Presidents' Day",           True),
    (date(2026, 4, 3),   "Good Friday",               True),
    (date(2026, 5, 25),  "Memorial Day",              True),
    (date(2026, 6, 19),  "Juneteenth",                True),
    (date(2026, 7, 3),   "Independence Day (observed)",True),
    (date(2026, 9, 7),   "Labor Day",                 True),
    (date(2026, 11, 26), "Thanksgiving",              True),
    (date(2026, 12, 25), "Christmas",                 True),
]

# Thanksgiving week = Monday-Wednesday before Thanksgiving (thin liquidity, COT suppressed)
# Christmas week = Dec 22-31 (thin liquidity, COT suppressed)
# CLAUDE.md rule #27: Thanksgiving + Christmas week COT freshness suppression


# ========================================================================
# C-90 (2026-08-26) — rule-derived extension for years past the curated tables
# ========================================================================
#
# The curated tables above stop at the end of 2026. Once the clock rolls into
# 2027 every blackout silently becomes a no-op and the system trades straight
# through NFP. The existing safeguard only LOGS that; it does not prevent it.
#
# Two of the six categories are genuinely rule-derived and are generated below.
# The other four are NOT, and are deliberately NOT invented:
#
#   generated      NYSE holidays   exact by statute + NYSE convention
#                  NFP             BLS scheduling convention
#   NOT generated  CPI, GDP        BLS picks the day; no rule reproduces it
#                  FOMC, ECB, BoE  announced by the banks, ~1 year ahead
#
# Fabricating a plausible-looking FOMC date would be worse than having none: it
# would blackout the wrong day AND leave the real one unguarded. When central-bank
# coverage lapses, `_load_static` escalates to ERROR instead.
#
# BOTH GENERATORS WERE VALIDATED AGAINST THE HAND-CURATED TABLES BEFORE USE:
#
#   holidays   2025: 10/10 dates   2026: 10/10 dates
#   NFP        2025: 12/12         2026: 12/12      (24/24 total)
#
# Two NFP conventions had to be encoded to reach 24/24, and both were derived from
# the curated data rather than assumed:
#   1. JANUARY lands on the SECOND Friday, not the first — the December report
#      needs the extra week. True in both curated years.
#   2. If the target Friday is a FEDERAL holiday the release moves one day earlier
#      (seen at July 4 in both years). Good Friday does NOT move it: the BLS is a
#      government agency and is open, even though the NYSE is shut — which is why
#      the curated 2026 table has NFP ON Good Friday, 2026-04-03. A naive
#      "skip market holidays" rule gets that one wrong.
#
# Kill-switch: BP_CALENDAR_NO_AUTOEXTEND=1 restores the old fixed-table behaviour.


def _easter(year: int) -> date:
    """Western Easter Sunday (anonymous Gregorian computus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th `weekday` (Mon=0) of a month, e.g. 3rd Monday of January."""
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(days=7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month, 28)
    while (d + timedelta(days=7)).month == month:
        d += timedelta(days=7)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """Saturday -> the Friday before; Sunday -> the Monday after."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _federal_holidays(year: int) -> set:
    """Statutory US federal holidays — the days the BLS itself is shut.

    Used only to shift an NFP release. Includes Columbus Day and Veterans Day,
    which are federal but do NOT close the NYSE, and excludes Good Friday, which
    closes the NYSE but is not federal.
    """
    return {
        _observed(date(year, 1, 1)),           # New Year's Day
        _nth_weekday(year, 1, 0, 3),           # MLK Jr Day
        _nth_weekday(year, 2, 0, 3),           # Presidents' Day
        _last_weekday(year, 5, 0),             # Memorial Day
        _observed(date(year, 6, 19)),          # Juneteenth
        _observed(date(year, 7, 4)),           # Independence Day
        _nth_weekday(year, 9, 0, 1),           # Labor Day
        _nth_weekday(year, 10, 0, 2),          # Columbus Day
        _observed(date(year, 11, 11)),         # Veterans Day
        _nth_weekday(year, 11, 3, 4),          # Thanksgiving
        _observed(date(year, 12, 25)),         # Christmas
    }


def _nyse_holidays(year: int) -> List[Tuple[date, str, bool]]:
    """The ten full NYSE closures, in the same shape as the curated tables."""
    out = [
        (_observed(date(year, 1, 1)),          "New Year's Day"),
        (_nth_weekday(year, 1, 0, 3),          "Martin Luther King Jr Day"),
        (_nth_weekday(year, 2, 0, 3),          "Presidents' Day"),
        (_easter(year) - timedelta(days=2),    "Good Friday"),
        (_last_weekday(year, 5, 0),            "Memorial Day"),
        (_observed(date(year, 6, 19)),         "Juneteenth"),
        (_observed(date(year, 7, 4)),          "Independence Day"),
        (_nth_weekday(year, 9, 0, 1),          "Labor Day"),
        (_nth_weekday(year, 11, 3, 4),         "Thanksgiving"),
        (_observed(date(year, 12, 25)),        "Christmas"),
    ]
    return [(d, n, True) for d, n in sorted(out)]


def _nfp_dates(year: int) -> List[date]:
    """The twelve NFP release dates. See the conventions in the block above."""
    fed = _federal_holidays(year)
    out = []
    for month in range(1, 13):
        d = _nth_weekday(year, month, 4, 2 if month == 1 else 1)
        while d in fed:
            d -= timedelta(days=1)
        out.append(d)
    return out


def generate_year(year: int) -> Tuple[List[CalendarEvent], List[Tuple[date, str, bool]]]:
    """Rule-derived events + holidays for one year. NFP only — never a bank date."""
    events = [
        CalendarEvent(
            "Non-Farm Payrolls (NFP)", EventType.ECONOMIC, EventImpact.HIGH,
            datetime(d.year, d.month, d.day, _et(8, 30).hour, _et(8, 30).minute),
            currency="USD", recurring_rule="first_friday",
            description="RULE-DERIVED, not confirmed against the official BLS schedule",
        )
        for d in _nfp_dates(year)
    ]
    return events, _nyse_holidays(year)


# ========================================================================
# EconomicCalendar class
# ========================================================================

class EconomicCalendar:
    """Manages the economic calendar and answers blackout queries.

    Construction loads the static event database and optionally fetches
    live data. All event timestamps are stored in UTC and blackout queries
    work against UTC.

    Thread-safe for read-only queries after construction.
    """

    # High-impact event blackout: ±2 hours (per Bernd's session-open check)
    DEFAULT_BLACKOUT_MINUTES = 120
    # Holiday blackout: entire trading session (6.5 hours ET = 13:00-20:00 UTC)
    HOLIDAY_BLACKOUT_HOURS = 8
    # COT suppression window (Thanksgiving week, Christmas week)
    COT_SUPPRESSION_WEEKS = [
        # Thanksgiving week (4th Thursday of November ± 4 days)
        # Christmas/New Year (Dec 20 - Jan 2)
    ]

    def __init__(self, blackout_minutes: int = DEFAULT_BLACKOUT_MINUTES):
        self.blackout_minutes = blackout_minutes
        self._events: List[CalendarEvent] = []
        self._holidays: Dict[date, str] = {}
        self._loaded = False
        self._load_static()

    def _load_static(self) -> None:
        """Load hardcoded 2025 event database and holidays."""
        if self._loaded:
            return

        # High-impact events (2025 + 2026)
        for e in _HIGH_IMPACT_2025 + _HIGH_IMPACT_2026:
            e.duration_minutes = self.blackout_minutes
            self._events.append(e)

        # Holidays (2025 + 2026)
        for d, name, closed in _US_FEDERAL_HOLIDAYS_2025 + _US_FEDERAL_HOLIDAYS_2026:
            if closed:
                self._holidays[d] = name

        # --- C-90: what the CURATED tables actually cover -------------------
        # Tracked before the generated years are added, so the generated NFP
        # entries cannot mask a lapse in the categories that are NOT generated.
        self._curated_max_year = max((e.timestamp.year for e in self._events),
                                     default=2026)
        self._cbank_max_year = max(
            (e.timestamp.year for e in self._events
             if e.event_type == EventType.CENTRAL_BANK), default=self._curated_max_year)
        self._generated_years: List[int] = []

        # --- C-90: extend the two rule-derived categories ------------------
        if os.environ.get('BP_CALENDAR_NO_AUTOEXTEND') != '1':
            horizon = max(datetime.utcnow().year + 1, self._curated_max_year)
            for year in range(self._curated_max_year + 1, horizon + 1):
                gen_events, gen_holidays = generate_year(year)
                for e in gen_events:
                    e.duration_minutes = self.blackout_minutes
                    self._events.append(e)
                for d, name, closed in gen_holidays:
                    if closed:
                        self._holidays.setdefault(d, name)
                self._generated_years.append(year)
            if self._generated_years:
                logger.info(
                    "EconomicCalendar: NFP + NYSE holidays rule-derived for %s "
                    "(validated 24/24 NFP and 20/20 holiday dates against the curated "
                    "2025-2026 tables). CPI/GDP/FOMC/ECB/BoE are NOT derivable and are "
                    "NOT generated.",
                    ", ".join(str(y) for y in self._generated_years),
                )

        self._loaded = True
        logger.info(
            f"EconomicCalendar loaded: {len(self._events)} events, "
            f"{len(self._holidays)} holidays"
        )
        # Phase 25 (DeepSeek P3): warn if today is past the last hardcoded event.
        # The static lists currently cover through end of 2026; once the system
        # rolls into 2027, all event-blackout logic silently becomes a no-op
        # and the system would allow trades during NFP/FOMC. Log a loud warning
        # so the operator knows to refresh `_HIGH_IMPACT_*` and `_US_FEDERAL_HOLIDAYS_*`.
        try:
            # Phase 37 fix: CalendarEvent has `timestamp` attribute, not `start`.
            # The previous `e.start.year` always raised AttributeError which was
            # silently swallowed by the surrounding try/except, making the stale
            # event warning completely inert.
            #
            # C-90: report per CATEGORY. NFP and holidays now auto-extend, so a
            # single "last_event_year" over all events would show 2027+ and hide
            # the fact that FOMC/ECB/BoE coverage still stops dead at the curated
            # year. The bank dates are the ones that cannot be derived, so they
            # are the ones the warning has to be about.
            current_year = datetime.utcnow().year
            if current_year > self._cbank_max_year:
                logger.error(
                    f"EconomicCalendar STALE: central-bank dates (FOMC/ECB/BoE) and "
                    f"CPI/GDP end in {self._cbank_max_year} but the current year is "
                    f"{current_year}. Those blackouts are DISABLED until BP_calendar.py "
                    f"is refreshed from the published schedules. NFP and NYSE holidays "
                    f"ARE covered (rule-derived for "
                    f"{', '.join(str(y) for y in self._generated_years) or 'no years'})."
                )
            elif current_year == self._cbank_max_year:
                logger.warning(
                    f"EconomicCalendar: central-bank + CPI dates end in "
                    f"{self._cbank_max_year} (current year). Refresh BP_calendar.py from "
                    f"the published FOMC/ECB/BoE schedules before year-end. NFP and "
                    f"NYSE holidays extend automatically and need no action."
                )
        except Exception:
            pass  # never let this safeguard break the loader

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_upcoming_events(
        self, after: Optional[datetime] = None, days_ahead: int = 14,
        min_impact: EventImpact = EventImpact.MEDIUM,
    ) -> List[CalendarEvent]:
        """Return events between `after` and `after + days_ahead`, sorted by time.

        Args:
            after: Starting datetime (UTC). Defaults to now.
            days_ahead: How many days to look ahead.
            min_impact: Minimum impact level to include.
        """
        if after is None:
            after = datetime.utcnow()
        cutoff = after + timedelta(days=days_ahead)

        level_order = {EventImpact.LOW: 0, EventImpact.MEDIUM: 1, EventImpact.HIGH: 2}
        min_level = level_order.get(min_impact, 1)

        upcoming = [
            e for e in self._events
            if after <= e.timestamp <= cutoff
            and level_order.get(e.impact, 0) >= min_level
        ]
        upcoming.sort(key=lambda e: e.timestamp)
        return upcoming

    def get_upcoming_high_impact(
        self, after: Optional[datetime] = None, days_ahead: int = 7,
    ) -> List[CalendarEvent]:
        """Shortcut: high-impact events only."""
        return self.get_upcoming_events(after=after, days_ahead=days_ahead,
                                        min_impact=EventImpact.HIGH)

    def check_blackout(
        self, when: Optional[datetime] = None,
    ) -> BlackoutStatus:
        """Check if `when` falls within any blackout period.

        Mirrors Bernd's session-open calendar check process:
          1. Is today a US federal holiday? → entire session blackout
          2. Is a high-impact event releasing within ±N minutes? → event blackout
          3. Is it Thanksgiving or Christmas week? → COT suppressed

        Args:
            when: Datetime to check (UTC). Defaults to now.

        Returns:
            BlackoutStatus with full details. Caller gates trade on
            `.in_blackout` and adjusts risk by `.risk_multiplier`.
        """
        if when is None:
            when = datetime.utcnow()

        status = BlackoutStatus()

        # ---- Holiday check ----
        when_date = when.date()
        # Also check adjacent day (holidays can have pre/post effects)
        for d, name in self._holidays.items():
            delta = abs((when_date - d).days)
            if delta == 0:
                status.in_blackout = True
                status.holiday_season = True
                status.reason = f"US Federal Holiday: {name} — market closed"
                status.risk_multiplier = 0.0  # cannot trade
                return status
            if delta <= 1:
                # Adjacent to holiday: thin liquidity, reduce but don't skip
                status.holiday_season = True
                status.risk_multiplier = min(status.risk_multiplier, 0.5)
                if not status.reason:
                    status.reason = f"Adjacent to holiday ({name}): thin liquidity"

        # ---- Event blackout check ----
        for event in self._events:
            if event.overlaps(when) and event.impact == EventImpact.HIGH:
                status.in_blackout = True
                status.blackout_events.append(event)
                status.risk_multiplier = min(status.risk_multiplier, 0.5)

        if status.blackout_events:
            names = ", ".join(e.title for e in status.blackout_events)
            status.reason = f"High-impact news blackout: {names}"
            if status.holiday_season:
                status.reason += " (holiday-adjacent session)"

        # ---- COT suppression check (Thanksgiving / Christmas week) ----
        if self._is_cot_suppression_week(when_date):
            status.cot_suppressed = True
            if not status.reason:
                status.reason = "COT freshness suppressed (holiday season — thin liquidity)"
            else:
                status.reason += " | COT suppressed (holiday season)"

        return status

    def is_market_holiday(self, when: Optional[datetime] = None) -> Tuple[bool, str]:
        """Check if a given day is a US market holiday.

        Returns (is_holiday, holiday_name).
        """
        if when is None:
            when = datetime.utcnow()
        name = self._holidays.get(when.date())
        return (name is not None, name or "")

    def _is_cot_suppression_week(self, d: date) -> bool:
        """Check if a date falls in the COT freshness suppression window.

        Per Blueprint rule #27: during Thanksgiving week and Christmas week,
        markets trade on reduced institutional volume. COT data from these
        weeks has limited predictive value and should be treated as stale.

        Windows:
          - Thanksgiving week: Mon-Wed of Thanksgiving (4th Thu of Nov)
          - Christmas week: Dec 20 - Jan 2
        """
        # Thanksgiving week: 4th Thursday of November ± 3 session days
        # Find the 4th Thursday of November for the given year
        nov1 = date(d.year, 11, 1)
        # 4th Thursday = first Thursday + 21 days
        days_to_thu = (3 - nov1.weekday()) % 7  # Thursday = 3
        first_thu = nov1 + timedelta(days=days_to_thu)
        thanksgiving = first_thu + timedelta(days=21)
        tgiving_start = thanksgiving - timedelta(days=4)  # Mon before
        tgiving_end = thanksgiving + timedelta(days=1)     # Fri

        if tgiving_start <= d <= tgiving_end:
            return True

        # Christmas/New Year window: Dec 20 - Jan 2
        # FIX Bug 4: original used `or` so matched nearly every date of year.
        # Split into two clean half-window checks instead.
        if d.month == 12 and d.day >= 20:
            return True
        if d.month == 1 and d.day <= 2:
            return True

        return False

    # ------------------------------------------------------------------
    # Dashboard serialization
    # ------------------------------------------------------------------

    def upcoming_summary(
        self, days_ahead: int = 14,
    ) -> Dict:
        """Return a dashboard-friendly summary of upcoming events and status."""
        now = datetime.utcnow()
        high = self.get_upcoming_events(after=now, days_ahead=days_ahead,
                                        min_impact=EventImpact.HIGH)
        medium = self.get_upcoming_events(after=now, days_ahead=days_ahead,
                                          min_impact=EventImpact.MEDIUM)
        blackout = self.check_blackout(now)

        return {
            'current_time': now.isoformat(),
            'blackout': blackout.to_dict(),
            'upcoming_high': [e.to_dict() for e in high[:8]],
            'upcoming_medium': [e.to_dict() for e in medium[:12]],
            'next_holiday': self._next_holiday(now),
        }

    def _next_holiday(self, after) -> Optional[Dict]:
        """Find the next upcoming US market holiday.

        `after` may be a date or a datetime; we normalise to date so the
        comparison and subtraction with date-keyed self._holidays never
        raises TypeError on mixed date/datetime arithmetic.
        """
        after_date: date = after.date() if isinstance(after, datetime) else after
        upcoming = [(d, n) for d, n in self._holidays.items() if d >= after_date]
        if not upcoming:
            return None
        upcoming.sort()
        d, name = upcoming[0]
        days_away = (d - after_date).days
        return {
            'date': d.isoformat(),
            'name': name,
            'days_away': days_away,
        }


# ========================================================================
# Module-level convenience
# ========================================================================

_default_calendar: Optional[EconomicCalendar] = None


def get_calendar() -> EconomicCalendar:
    """Return the module-level singleton EconomicCalendar, creating it on
    first access. The calendar is stateless after construction (all data
    is hardcoded), so a single instance is safe to share across the app.
    """
    global _default_calendar
    if _default_calendar is None:
        _default_calendar = EconomicCalendar()
    return _default_calendar


def check_blackout(when: Optional[datetime] = None) -> BlackoutStatus:
    """Convenience: check blackout using the default calendar."""
    return get_calendar().check_blackout(when)