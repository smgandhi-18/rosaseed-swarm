import json

import pytest

from agents.conditions import parse_regions
from swarm.tools import region_violation


def regions(*cons):
    return json.dumps({"regions": [{"name": "x", "rationale": "", "constraints": c} for c in cons]})


def test_valid_regions_parsed_and_renamed():
    r = parse_regions("Here you go:\n" + regions({"prechain": ["off"]}, {"k": {"min": 20}}, {}))
    assert [x["name"] for x in r] == ["explorer1", "explorer2", "explorer3"]
    assert r[1]["constraints"]["k"] == {"min": 20, "max": 25}


@pytest.mark.parametrize("bad", [
    regions({}, {}),                                   # only 2 regions
    regions({"bogus": [1]}, {}, {}),                   # unknown field
    regions({"cap": [300]}, {}, {}),                   # value not allowed
    regions({"k": {"min": 10, "max": 30}}, {}, {}),    # range outside 15..25
    regions({"prechain": []}, {}, {}),                 # empty list
    "no json here",
])
def test_bad_regions_rejected(bad):
    with pytest.raises((ValueError, KeyError, TypeError)):
        parse_regions(bad)


def test_region_violation():
    region = {"prechain": ["off"], "k": {"min": 20, "max": 25}}
    assert region_violation(region, {"prechain": "off", "k": 22}) is None
    assert "outside" in region_violation(region, {"prechain": "t50w60", "k": 22})
    assert "outside" in region_violation(region, {"prechain": "off", "k": 19})


def test_equivalent_forms_are_normalised():
    # Forms the planner actually produced in swarm repeat 1 (all three attempts rejected
    # by the old, too-strict parser).
    r = parse_regions(regions(
        {"k": {"min": 15, "max": 20}, "cap": {"min": 50, "max": 100}, "early_exit": True, "frc": True},
        {"early_exit": ["true"], "frc": "false", "prechain": "off"},
        {"cap": 500},
    ))
    assert r[0]["constraints"]["cap"] == [50, 100]
    assert r[0]["constraints"]["early_exit"] == [True] and r[0]["constraints"]["frc"] == [True]
    assert r[1]["constraints"]["early_exit"] == [True] and r[1]["constraints"]["frc"] == [False]
    assert r[1]["constraints"]["prechain"] == ["off"]
    assert r[2]["constraints"]["cap"] == [500]


def test_cap_range_with_no_allowed_value_rejected():
    with pytest.raises(ValueError):
        parse_regions(regions({"cap": {"min": 300, "max": 400}}, {}, {}))
