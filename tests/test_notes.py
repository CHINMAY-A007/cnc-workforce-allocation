import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.notes import parse_notes, KNOWN_SKILLS, KNOWN_CERTS


def _lower(xs): return [x.lower() for x in xs]


def test_titanium_note():
    p = parse_notes("Needs titanium, certified inspector only, surface finish N6.")
    assert "Titanium Machining" in p["skills"]
    assert "CMM Inspection Cert" in p["certs"]
    assert any("surface finish n6" in n.lower() for n in p["notes"])


def test_unknown_rejected():
    p = parse_notes("Needs unobtainium coating")
    assert not p["skills"] and not p["certs"]


def test_validation():
    p = parse_notes("Needs titanium")
    for s in p["skills"]:
        assert s in KNOWN_SKILLS