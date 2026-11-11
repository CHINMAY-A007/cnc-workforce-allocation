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

# Current free-tier Flash model (availability confirmed in AI Studio model picker and live test).
GEMINI_MODEL = "gemini-3.8-flash"
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


def gemini_generate(prompt: str) -> str | None:
    """One Gemini call, shared by every AI feature (note reader, result explainer).

    Runs only when the owner explicitly enabled Gemini (GEMINI_ENABLED=1 plus a key),
    never more than GEMINI_MAX_CALLS times per server run across all features, so a
    visitor cannot run up usage. Returns the model's text, or None on any failure
    (disabled, cap reached, network, quota, auth) so callers fall back to rules.
    The key is read from the environment and never logged or returned.
    """
    global _gemini_calls
    if not gemini_enabled() or _gemini_calls >= GEMINI_MAX_CALLS:
        return None
    _gemini_calls += 1
    key = _resolve_key()
    if not key:
        return None
    try:
        r = httpx.post(
            GEMINI_URL,
            params={"key": key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20.0,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        # diagnostics only: exception class and HTTP status, never the key or body
        status = getattr(getattr(e, "response", None), "status_code", None)
        print(f"[gemini] call failed: {type(e).__name__} status={status}")
        return None


def _gemini_parse(text: str) -> Dict | None:
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
    raw = gemini_generate(prompt)
    if raw is None:
        return None
    try:
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
        # Bad JSON -> fall back to the keyword reader.
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


GEMINI_MAX_CALLS = int(os.environ.get("GEMINI_MAX_CALLS", "25"))  # hard cap per server run
_gemini_calls = 0


def gemini_enabled() -> bool:
    """Gemini is OFF unless the owner explicitly sets GEMINI_ENABLED=1 AND a key exists."""
    return os.environ.get("GEMINI_ENABLED", "").strip() == "1" and bool(_resolve_key())


def note_reader_mode() -> Dict[str, object]:
    if gemini_enabled():
        return {"mode": "gemini", "label": "AI-assisted note reader (Gemini) with keyword fallback", "calls_left": max(0, GEMINI_MAX_CALLS - _gemini_calls)}
    return {"mode": "keyword", "label": "Keyword note reader (free, runs locally, no AI service)", "calls_left": 0}


def parse_notes(text: str, use_llm: bool = True) -> Dict[str, List[str]]:
    """Parse order notes with the free keyword reader.

    Gemini is used only when the owner has explicitly opted in (GEMINI_ENABLED=1 plus a key),
    only for short notes, and never more than GEMINI_MAX_CALLS times per server run, so a
    visitor cannot run up usage. Any failure falls back to the keyword reader.
    """
    text = (text or "")[:500]
    notice = ""
    if use_llm and gemini_enabled():
        res = _gemini_parse(text)
        if res is not None:
            return res
        notice = "The AI note reader did not answer, so the keyword reader was used."
    res = _keyword_parse(text)
    res["source"] = "keyword"
    res["fallback"] = bool(notice)
    res["notice"] = notice
    return res
