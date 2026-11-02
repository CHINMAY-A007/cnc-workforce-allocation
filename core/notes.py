"""Note reader: optional Gemini LLM, falling back to rule-based keyword parser."""

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
    return {
        "skills": validated_skills,
        "certs": validated_certs,
        "notes": found_notes,
        "matched_phrases": matched,
        "rejected": rejected,
        "source": "keyword",
    }


def _gemini_parse(text: str) -> Dict[str, List[str]] | None:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        except Exception:
            pass
    if not key:
        return None
    prompt = (
        "Extract structured requirements from these CNC manufacturing order notes: " + (text or "") + "\n"
        "Return ONLY a JSON object (no markdown, no code fences) with keys: skills, certs, notes, rejected.\n"
        "skills: array of strings, each MUST be one of these exact values or empty: " + json.dumps(sorted(KNOWN_SKILLS)) + "\n"
        "certs: array of strings, each MUST be one of these exact values or empty: " + json.dumps(sorted(KNOWN_CERTS)) + "\n"
        "notes: array of other requirement phrases that are not skills/certs.\n"
        "rejected: array of phrases that matched nothing.\n"
        "Do not invent new skill or cert names. If unsure, put the phrase in rejected."
    )
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        r = httpx.post(url, params={"key": key}, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20.0)
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
        return None
    raw_skills = parsed.get("skills", [])
    raw_certs = parsed.get("certs", [])
    notes = parsed.get("notes", [])
    skills = [s for s in raw_skills if s in KNOWN_SKILLS]
    certs = [c for c in raw_certs if c in KNOWN_CERTS]
    rejected = [s for s in raw_skills if s not in KNOWN_SKILLS] + [c for c in raw_certs if c not in KNOWN_CERTS]
    rejected += [n for n in notes if n.lower() in ("rejected",)]
    return {
        "skills": skills,
        "certs": certs,
        "notes": notes,
        "matched_phrases": [],
        "rejected": rejected,
        "source": "gemini",
    }


def parse_notes(text: str, use_llm: bool = True) -> Dict[str, List[str]]:
    if use_llm:
        res = _gemini_parse(text)
        if res is not None:
            return res
    return _keyword_parse(text)