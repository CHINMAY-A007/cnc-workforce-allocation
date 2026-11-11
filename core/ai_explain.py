"""Plain-language explanation of validated results (spec section 5: "AI explanation").

The LLM only ever receives results the solver and the resource analyzer have already
produced and validated, and explains them in plain language for the production manager.
It never decides allocations, never changes a number, and its text is advisory.

When Gemini is off or does not answer, the same explanation is built by rules from the
same validated data, so the feature works identically in structure either way; only the
wording source differs, and the response says which one produced it.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core.notes import gemini_enabled, gemini_generate


def _facts(a: Dict[str, Any]) -> Dict[str, Any]:
    """The validated numbers the explanation is allowed to talk about. Nothing else."""
    return {
        "overall_status": a.get("overall_status", ""),
        "resources": [
            {k: r.get(k) for k in ("resource", "required", "available", "shortage", "status", "verdict")}
            for r in a.get("rows", [])
        ],
        "recommendations": [
            {"resource": r.get("resource"), "severity": r.get("severity"), "actions": r.get("actions", [])}
            for r in a.get("recommendations", [])
        ],
        "schedule_impact": [
            {"order_id": o.get("order_id"), "finishes": o.get("finish_text"), "due": o.get("due_date"),
             "status": o.get("status"), "hours_late": o.get("hours_late")}
            for o in (a.get("schedule_impact") or {}).get("orders", [])
        ],
    }


def _rule_based(a: Dict[str, Any]) -> str:
    """Deterministic plain-language summary built from the same validated results."""
    rows = a.get("rows", [])
    deficits = [r for r in rows if r.get("shortage") and str(r.get("verdict", "")).startswith("true deficit")]
    peaks = [r for r in rows if r.get("shortage") and not str(r.get("verdict", "")).startswith("true deficit")]
    parts: List[str] = [a.get("overall_status", "").strip() or "Resource status computed."]
    if deficits:
        parts.append("True shortages: " + "; ".join(
            f"{r['resource']} needs {r['required']:g} but only {max(0, r['available']):g} are available ({r['shortage']:g} short)"
            for r in deficits) + ". These must be fixed or the schedule revised before approval.")
    if peaks:
        parts.append("Timing peaks, not true shortages: " + "; ".join(
            f"{r['resource']} is {r['shortage']:g} short at the busiest moment" for r in peaks) +
            ". The week's capacity covers the work, so the planner sequences jobs across days.")
    if not deficits and not peaks:
        parts.append("Every required machine, person and material is available for the selected orders.")
    critical = [r for r in a.get("recommendations", []) if r.get("severity") == "critical"]
    if critical:
        first = critical[0]
        parts.append(f"Top recommended action for {first['resource']}: {first['actions'][0]}")
    orders = (a.get("schedule_impact") or {}).get("orders", [])
    late = [o for o in orders if o.get("status") == "late"]
    risky = [o for o in orders if o.get("status") == "at_risk"]
    if orders:
        s = f"Schedule impact: {len(orders)} order(s) estimated, "
        late_txt = "; ".join("{} about {:g} h over".format(o["order_id"], o["hours_late"]) for o in late[:3])
        s += f"{len(late)} late" + (f" ({late_txt})" if late else "")
        s += f", {len(risky)} at risk, {len(orders) - len(late) - len(risky)} on time."
        parts.append(s)
    parts.append("Recommendations are advisory only: nothing is booked until the manager approves a schedule.")
    return " ".join(parts)


def explain_analysis(a: Dict[str, Any]) -> Dict[str, str]:
    """Explain a resource_analysis() result. Source is labelled honestly."""
    facts = _facts(a)
    if gemini_enabled():
        prompt = (
            "You are explaining validated production-planning results to a factory production manager. "
            "The JSON below comes from an OR-Tools solver and a resource availability analysis; every number in it is final. "
            "Do not change, invent or recompute any number, and do not suggest the system has done anything it only recommends. "
            "In plain language, 120-180 words: the overall resource status, each shortage and what causes it, "
            "the most important recommended actions, and the delivery impact. "
            "End with one sentence saying the recommendations are advisory until the manager approves a schedule.\n"
            "Validated results (JSON):\n" + json.dumps(facts)
        )
        text = gemini_generate(prompt)
        if text:
            return {"text": text.strip(), "source": "gemini",
                    "label": "Written by Gemini from the validated solver and analysis results above. Advisory only; numbers come from the app, not the AI."}
    return {"text": _rule_based(a), "source": "rule-based",
            "label": "Rule-based plain-language summary of the same validated results (Gemini off or unavailable)."}
