"""
BFR KiCad Library Manager - Component Classifier
Determines which BFR library a component belongs to based on
keywords, description, reference designator, and other heuristics.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("bfr_plugin")


# Map of BFR library names to classification patterns
LIBRARY_PATTERNS = {
    "bfr_resistors": {
        "keywords": [
            "resistor", "resistance", "ohm", "shunt",
        ],
        "ref_prefix": ["R"],
        "description": [
            r"\bresistor\b", r"\bohm\b", r"\bres\b",
        ],
    },
    "bfr_potentiometers": {
        "keywords": [
            "potentiometer", "pot", "trimpot", "trimmer",
            "rheostat", "variable resistor",
        ],
        "ref_prefix": ["RV"],
        "description": [
            r"\bpotentiometer\b", r"\btrimpot\b", r"\btrimmer\b",
        ],
    },
    "bfr_capacitors": {
        "keywords": [
            "capacitor", "cap", "farad", "supercap", "ultracap",
            "mlcc", "ceramic", "electrolytic", "tantalum",
        ],
        "ref_prefix": ["C"],
        "description": [
            r"\bcapacitor\b", r"\bcap\b", r"\bfarad\b", r"\bmlcc\b",
        ],
    },
    "bfr_inductors": {
        "keywords": [
            "inductor", "inductance", "henry", "coil", "choke",
            "ferrite", "bead",
        ],
        "ref_prefix": ["L", "FB"],
        "description": [
            r"\binductor\b", r"\bhenry\b", r"\bcoil\b", r"\bchoke\b",
            r"\bferrite\b", r"\bbead\b",
        ],
    },
    "bfr_transformers": {
        "keywords": [
            "transformer", "xfmr", "coupled inductor", "isolation",
        ],
        "ref_prefix": ["T"],
        "description": [
            r"\btransformer\b", r"\bxfmr\b",
        ],
    },
    "bfr_crystals": {
        "keywords": [
            "crystal", "oscillator", "resonator", "xtal",
            "tcxo", "vcxo", "mems oscillator",
        ],
        "ref_prefix": ["Y"],
        "description": [
            r"\bcrystal\b", r"\boscillator\b", r"\bresonator\b", r"\bxtal\b",
        ],
    },
    "bfr_diodes": {
        "keywords": [
            "diode", "led", "zener", "schottky", "tvs",
            "rectifier", "varactor", "photodiode",
        ],
        "ref_prefix": ["D"],
        "description": [
            r"\bdiode\b", r"\bled\b", r"\bzener\b", r"\bschottky\b",
            r"\btvs\b", r"\brectifier\b",
        ],
    },
    "bfr_transistors": {
        "keywords": [
            "transistor", "mosfet", "bjt", "fet", "jfet", "igbt",
            "darlington", "npn", "pnp", "nmos", "pmos",
        ],
        "ref_prefix": ["Q"],
        "description": [
            r"\btransistor\b", r"\bmosfet\b", r"\bbjt\b", r"\bfet\b",
            r"\bnpn\b", r"\bpnp\b",
        ],
    },
    "bfr_amplifiers": {
        "keywords": [
            "amplifier", "amp", "opamp", "op-amp", "comparator",
            "instrumentation", "differential", "buffer",
        ],
        "ref_prefix": [],
        "description": [
            r"\bamplifier\b", r"\bop[\s-]?amp\b", r"\bcomparator\b",
        ],
    },
    "bfr_connectors": {
        "keywords": [
            "connector", "header", "jack", "socket", "plug", "terminal",
            "pin", "receptacle", "usb", "rj45", "barrel",
        ],
        "ref_prefix": ["J", "P"],
        "description": [
            r"\bconnector\b", r"\bheader\b", r"\bjack\b", r"\bsocket\b",
            r"\bplug\b", r"\bterminal\b", r"\busb\b",
        ],
    },
    "bfr_sensors": {
        "keywords": [
            "sensor", "accelerometer", "gyroscope", "imu",
            "temperature sensor", "thermocouple", "thermistor",
            "ntc", "ptc", "pressure", "humidity", "magnetometer",
            "hall effect", "current sense", "photodetector",
        ],
        "ref_prefix": [],
        "description": [
            r"\bsensor\b", r"\baccelerometer\b", r"\bgyro\b", r"\bimu\b",
            r"\bthermistor\b", r"\bntc\b", r"\bptc\b",
        ],
    },
    "bfr_microcontrollers": {
        "keywords": [
            "mcu", "microcontroller", "stm32", "atmega", "esp32",
            "pic", "arm", "cortex", "risc-v", "riscv", "nrf",
            "samd", "raspberry", "rp2040", "esp8266",
        ],
        "ref_prefix": [],
        "description": [
            r"\bmicrocontroller\b", r"\bmcu\b", r"\bstm32\b", r"\batmega\b",
            r"\besp32\b", r"\brp2040\b",
        ],
    },
    "bfr_power_ics": {
        "keywords": [
            "regulator", "ldo", "buck", "boost", "smps", "pmic",
            "dc-dc", "converter", "charger", "supervisor",
            "voltage reference", "vref",
        ],
        "ref_prefix": [],
        "description": [
            r"\bregulator\b", r"\bldo\b", r"\bbuck\b", r"\bboost\b",
            r"\bdc[\s-]?dc\b", r"\bconverter\b", r"\bpmic\b",
        ],
    },
    "bfr_power_symbols": {
        "keywords": [
            "vcc", "gnd", "power flag", "pwr", "supply",
            "ground", "vdd", "vss", "v+", "v-",
        ],
        "ref_prefix": ["#"],
        "description": [
            r"\bpower\s*(flag|symbol)\b",
        ],
    },
    "bfr_utilities": {
        "keywords": [
            "fuse", "relay", "switch", "button", "encoder",
            "display", "oled", "lcd", "buzzer", "speaker",
            "optocoupler", "optoisolator", "eeprom", "flash",
            "adc", "dac", "timer", "driver", "gate",
            "ic", "logic", "buffer", "level shifter",
        ],
        "ref_prefix": ["F", "SW", "K", "U"],
        "description": [
            r"\bfuse\b", r"\brelay\b", r"\bswitch\b",
            r"\bdisplay\b", r"\bdriver\b",
        ],
    },
}

# Components with these reference prefixes are considered "passive"
PASSIVE_REFS = {"R", "C", "L"}
PASSIVE_LIBS = {"bfr_resistors", "bfr_capacitors", "bfr_inductors", "bfr_potentiometers"}


@dataclass
class ClassificationResult:
    """Result of component classification."""
    library: str
    confidence: float
    is_passive: bool
    reason: str


def classify_component(
    name: str = "",
    description: str = "",
    keywords: list = None,
    reference: str = "",
    value: str = "",
    properties: dict = None,
) -> ClassificationResult:
    """
    Classify a component into a BFR library category.
    Uses scoring: keyword +3, description regex +5, reference prefix +4, name +2.
    """
    keywords = keywords or []
    properties = properties or {}

    all_text = " ".join([
        name, description, value,
        " ".join(keywords),
        " ".join(properties.values()),
    ]).lower()

    scores = {}

    for lib_name, patterns in LIBRARY_PATTERNS.items():
        score = 0
        reasons = []

        for kw in patterns["keywords"]:
            if kw.lower() in all_text:
                score += 3
                reasons.append(f"keyword '{kw}'")

        for desc_pattern in patterns["description"]:
            if re.search(desc_pattern, all_text, re.IGNORECASE):
                score += 5
                reasons.append(f"desc match")

        ref_clean = reference.strip().upper()
        for prefix in patterns["ref_prefix"]:
            if ref_clean == prefix or (ref_clean.startswith(prefix) and len(ref_clean) <= len(prefix) + 1):
                score += 4
                reasons.append(f"ref '{prefix}'")

        if score > 0:
            scores[lib_name] = (score, reasons)

    if scores:
        best_lib = max(scores, key=lambda k: scores[k][0])
        best_score, best_reasons = scores[best_lib]
        confidence = min(best_score / 12.0, 1.0)

        ref_clean = reference.strip().upper()
        is_passive = best_lib in PASSIVE_LIBS or any(
            ref_clean == p or (ref_clean.startswith(p) and len(ref_clean) <= len(p) + 1)
            for p in PASSIVE_REFS
        )

        return ClassificationResult(
            library=best_lib,
            confidence=confidence,
            is_passive=is_passive,
            reason=f"Matched: {', '.join(best_reasons[:3])}",
        )

    return ClassificationResult(
        library="bfr_misc",
        confidence=0.0,
        is_passive=False,
        reason="No match — bfr_misc fallback",
    )


def classify_from_component_data(component) -> ClassificationResult:
    return classify_component(
        name=component.name,
        description=component.description,
        keywords=component.keywords,
        reference=component.reference,
        value=component.value,
        properties=component.properties,
    )
