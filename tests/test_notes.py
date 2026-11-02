import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.notes import parse_notes, KNOWN_SKILLS, KNOWN_CERTS


def test_titanium_note():
    p = parse_notes("Needs titanium, certified inspector only, surface finish N6.")
    assert "Titanium Machining" in p["skills"]
    assert "CMM Inspection Cert" in p["certs"]
    assert "Surface finish N6" in p["notes"]


def test_unknown_rejected():
    p = parse_notes("Needs unobtainium coating")
    assert p["rejected"], p
    assert "Titanium Machining" not in p["skills"]


def test_validation():
    p = parse_notes("Needs titanium")
    for s in p["skills"]:
        assert s in KNOWN_SKILLS