"""Note reader: optional Gemini LLM, falling back to a rule-based keyword parser.

Separation of concerns (hard boundary):
  * The LLM (Gemini) ONLY reads free-text order notes and extracts requirement phrases.
  * OR-Tools (core/solver.py) makes ALL assignment/scheduling decisions. It never calls
    the LLM and never receives LLM output for assignment logic.

The Gemini key is read strictly from the GEMINI_API_KEY environment variable (or a local
``.env`` file that is gitignored). It is never hardcoded, never committed, and never
logged or displayed.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

import httpx

KEYWORD_MAP: Dict[str, tuple] = {
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

# Current fast Gemini model (availability confirmed on generativelanguage.googleapis.com).
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

_UNKNOWN_PREFIX = "Not recognized, please confirm: "


def _resolve_key() -> str | None:
    """Read the Gemini key strictly from the environment / local .env.

    Never hardcodes a key, never writes it to logs, and never returns it to callers.
    """
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _empty_result(source: str, fallback: bool = False, notice: str = "") -> Dict:
    return {
        "required_skills": [],
        "required_certifications": [],
        "special_notes": [],
        # Legacy keys kept for backward compatibility with existing callers/tests.
        "skills": [],
        "certs": [],
        "notes": [],
        "rejected": [],
        "unknown_items": [],
        "matched_phrases": [],
        "source": source,
        "fallback": fallback,
        "notice": notice,
        "summary": "",
    }


def _validate_lists(raw_skills, raw_certs, raw_notes, raw_rejected):
    """Validate every extracted item against known skills/certs.

    Items that match a known value are kept. Anything unknown is surfaced as
    "Not recognized, please confirm: <item>" so a human can confirm it.
    """
    skills = [s for s in (raw_skills or []) if s in KNOWN_SKILLS]
    certs = [c for c in (raw_certs or []) if c in KNOWN_CERTS]
    notes = list(raw_notes or [])
    unknown: List[str] = []
    for s in raw_skills or []:
        if s not in KNOWN_SKILLS:
            unknown.append(_UNKNOWN_PREFIX + s)
    for c in raw_certs or []:
        if c not in KNOWN_CERTS:
            unknown.append(_UNKNOWN_PREFIX + c)
    rejected = list(raw_rejected or []) + unknown
    return skills, certs, notes, rejected


def _build_summary(skills, certs, notes) -> str:
    parts: List[str] = []
    if skills:
        parts.append(", ".join(skills))
    if certs:
        parts.append("certified " + ", ".join(c.replace(" Cert", "") for c in certs))
    if notes:
        parts.append("; ".join(notes))
    if not parts:
        return "We read your note and found no recognized requirements."
    return "We read your note and added: " + ", ".join(parts) + "."


def _gemini_parse(text: str) -> Dict | None:
    key = _resolve_key()
    if not key:
        return None
    prompt = (
        "Extract structured requirements from these CNC manufacturing order notes. "
        "Return ONLY a JSON object (no markdown, no code fences) with keys: "
        "required_skills, required_certifications, special_notes, rejected.\n"
        "required_skills: array of strings, each MUST be one of these exact values or empty: "
        + json.dumps(sorted(KNOWN_SKILLS)) + "\n"
        "required_certifications: array of strings, each MUST be one of these exact values or empty: "
        + json.dumps(sorted(KNOWN_CERTS)) + "\n"
        "special_notes: array of other requirement phrases that are not skills/certs.\n"
        "rejected: array of phrases that matched nothing known.\n"
        "Do not invent new skill or cert names. If unsure, put the phrase in rejected.\n"
        "Notes: " + (text or "")
    )
    try:
        r = httpx.post(
            GEMINI_URL,
            params={"key": key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20.0,
        )
        r.raise_for_status()
        data = r.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            lines = raw.splitlines()
            if lines and lines[0].strip().lower() in ("json",):
                lines = lines[1:]
            raw = "\n".join(lines)
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        parsed = json.loads(raw)
    except Exception:
        # Any failure (network, quota, auth, bad JSON) -> fall back to keyword reader.
        return None

    skills, certs, notes, rejected = _validate_lists(
        parsed.get("required_skills", []),
        parsed.get("required_certifications", []),
        parsed.get("special_notes", []),
        parsed.get("rejected", []),
    )
    return {
        "required_skills": skills,
        "required_certifications": certs,
        "special_notes": notes,
        "skills": skills,
        "certs": certs,
        "notes": notes,
        "rejected": rejected,
        "unknown_items": [r for r in rejected if r.startswith(_UNKNOWN_PREFIX)],
        "matched_phrases": [],
        "source": "gemini",
        "fallback": False,
        "notice": "",
        "summary": _build_summary(skills, certs, notes),
    }


def _keyword_parse(text: str) -> Dict[str, List[str]]:
    low = (text or "").lower()
    found_skills: List[str] = []
    found_certs: List[str] = []
    found_notes: List[str] = []
    matched: List[str] = []
    for phrase in sorted(KEYWORD_MAP.keys(), key=len, reverse=True):
        if phrase in low:
            kind, val = KEYWORD_MAP[phrase]
            if kind == "skill" and val not in found_skills:
                found_skills.append(val)
            elif kind == "cert" and val not in found_certs:
                found_certs.append(val)
            elif kind == "note" and val not in found_notes:
                found_notes.append(val)
            matched.append(phrase)
    validated_skills = [s for s in found_skills if s in KNOWN_SKILLS]
    validated_certs = [c for c in found_certs if c in KNOWN_CERTS]
    rejected = []
    chunks = [c.strip() for c in (text or "").replace(";", ",").split(",") if c.strip()]
    for ch in chunks:
        cl = ch.lower()
        if not any(p in cl for p in KEYWORD_MAP.keys()):
            rejected.append(ch)
    skills, certs, notes, rejected2 = _validate_lists(
        validated_skills, validated_certs, found_notes, rejected
    )
    # keyword parser: rejected already holds unmatched chunks; keep them plus any unknowns.
    rejected = rejected2
    return {
        "required_skills": skills,
        "required_certifications": certs,
        "special_notes": notes,
        "skills": skills,
        "certs": certs,
        "notes": notes,
        "rejected": rejected,
        "unknown_items": [r for r in rejected if r.startswith(_UNKNOWN_PREFIX)],
        "matched_phrases": matched,
        "source": "keyword",
        "fallback": False,
        "notice": "",
        "summary": _build_summary(skills, certs, notes),
    }


def parse_notes(text: str, use_llm: bool = True) -> Dict[str, List[str]]:
    """Parse order notes.

    Tries Gemini first when ``use_llm`` is true and a key is available. If the key is
    missing or the Gemini call fails (quota, network, bad response), falls back to the
    keyword reader so the demo never breaks. Returns a JSON-serializable dict.
    """
    notice = ""
    if use_llm:
        res = _gemini_parse(text)
        if res is not None:
            return res
        notice = (
            "Gemini key missing or call failed; using keyword reader. "
            "Set GEMINI_API_KEY to enable AI-assisted note parsing."
        )
    res = _keyword_parse(text)
    res["source"] = "keyword"
    res["fallback"] = True
    res["notice"] = notice
    return res
