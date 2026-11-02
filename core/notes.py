"""Rule-based keyword parser for free-text order notes.

This is keyword matching, NOT language understanding. It extracts extra
requirements by matching known terms. Unknown phrases are rejected and shown
to the manager; nothing is silently applied.
"""

from __future__ import annotations

import json
from typing import Dict, List, Tuple

# term -> (kind, canonical value)
KEYWORD_MAP: Dict[str, Tuple[str, str]] = {
    "titanium": ("skill", "Titanium Machining"),
    "titanium machining": ("skill", "Titanium Machining"),
    "certified inspector": ("cert", "CMM Inspection Cert"),
    "certified cmm": ("cert", "CMM Inspection Cert"),
    "cmm inspector": ("cert", "CMM Inspection Cert"),
    "surface finish n6": ("note", "Surface finish N6"),
    "n6": ("note", "Surface finish N6"),
    "5-axis": ("skill", "5-Axis Programming"),
    "five axis": ("skill", "5-Axis Programming"),
    "setup": ("skill", "Setup"),
    "deburr": ("skill", "Deburring"),
    "packing": ("skill", "Packing"),
}

KNOWN_SKILLS = {
    "CNC Turning", "VMC Milling", "5-Axis Programming", "Setup",
    "CMM Inspection", "Deburring", "Packing", "Titanium Machining",
}
KNOWN_CERTS = {
    "CMM Inspection Cert", "Titanium Machining Cert", "5-Axis Programming Cert",
    "CNC Turning Cert", "VMC Operator Cert", "Setup Technician Cert",
    "Deburring Cert", "Packing Cert",
}


def parse_notes(text: str) -> Dict[str, List[str]]:
    low = (text or "").lower()
    found_skills: List[str] = []
    found_certs: List[str] = []
    found_notes: List[str] = []
    matched_phrases: List[str] = []
    rejected: List[str] = []

    # try multi-word phrases first
    for phrase in sorted(KEYWORD_MAP.keys(), key=len, reverse=True):
        if phrase in low:
            kind, val = KEYWORD_MAP[phrase]
            if kind == "skill" and val not in found_skills:
                found_skills.append(val)
            elif kind == "cert" and val not in found_certs:
                found_certs.append(val)
            elif kind == "note" and val not in found_notes:
                found_notes.append(val)
            matched_phrases.append(phrase)

    # validate against known structured fields
    validated_skills = [s for s in found_skills if s in KNOWN_SKILLS]
    validated_certs = [c for c in found_certs if c in KNOWN_CERTS]

    # rejected = phrases present in text but not in keyword map
    words = low.split()
    # simple: any known keyword phrase not matched but text has content -> mark unknown tokens
    # We report the whole unmatched note chunks as rejected for transparency.
    rejected_phrases = []
    # Heuristic: split note by commas/and; check each chunk against matched phrases
    chunks = [c.strip() for c in text.replace(";", ",").split(",") if c.strip()]
    for ch in chunks:
        cl = ch.lower()
        if not any(p in cl for p in KEYWORD_MAP.keys()):
            rejected_phrases.append(ch)

    return {
        "skills": validated_skills,
        "certs": validated_certs,
        "notes": found_notes,
        "matched_phrases": matched_phrases,
        "rejected": rejected_phrases,
    }