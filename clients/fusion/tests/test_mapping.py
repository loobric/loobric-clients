# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT
import copy

from conftest import tool_named
from loobric_fusion import mapping, presetsync


def _assert_map(sections):
    return {path: (value, unit) for path, value, unit in sections.asserts}


def test_tool_to_sections_metric(sample_doc):
    tool = tool_named(sample_doc, "mysterybit")
    sections = mapping.tool_to_sections(tool)
    assert sections.client_item_id == "f93aeaa8-a649-4abb-a1ce-d23f998e4dee"
    assert sections.data["tool"] == tool
    asserts = _assert_map(sections)
    assert asserts["name"] == ("mysterybit", None)
    assert asserts["geometry.shape"] == ("ballend", None)  # its Fusion type
    assert asserts["geometry.diameter"] == (5, "mm")
    assert asserts["geometry.length"] == (36, "mm")
    assert asserts["geometry.cutting_edge_height"] == (18, "mm")
    assert asserts["geometry.shank_diameter"] == (5, "mm")
    assert asserts["geometry.flutes"] == (4, None)


def test_tool_to_sections_inch_with_holder(sample_doc):
    tool = tool_named(sample_doc, "4 Flute HSS")
    sections = mapping.tool_to_sections(tool)
    asserts = _assert_map(sections)
    assert asserts["geometry.shape"] == ("endmill", None)
    assert asserts["geometry.diameter"] == (0.375, "in")
    # The holder block rides the client section untouched.
    assert sections.data["tool"]["holder"]["vendor"] == "Tormach"


def test_unknown_type_gets_no_shape_assert(sample_doc):
    tool = copy.deepcopy(tool_named(sample_doc, "mysterybit"))
    tool["type"] = "lollipop mill"
    asserts = _assert_map(mapping.tool_to_sections(tool))
    assert "geometry.shape" not in asserts
    assert "geometry.diameter" in asserts


def _record_for(tool, canonical=None):
    return {
        "internal": {"id": "rec-1", "version": 3},
        "canonical": canonical or {},
        "clients": {"fusion360": {"client_item_id": tool.get("guid"),
                                  "data": {"tool": copy.deepcopy(tool)}}},
    }


def test_record_to_tool_verbatim_when_canonical_matches(sample_doc):
    tool = tool_named(sample_doc, "mysterybit")
    record = _record_for(tool, canonical={
        "name": {"value": "mysterybit"},
        "geometry": {"diameter": {"value": 5, "unit": "mm"}},
    })
    regenerated = mapping.record_to_tool(record)
    assert regenerated == tool     # no churn without a real change


def test_record_to_tool_canonical_wins_and_expressions_follow(sample_doc):
    tool = tool_named(sample_doc, "mysterybit")
    record = _record_for(tool, canonical={
        "name": {"value": "renamed on server"},
        "geometry": {"diameter": {"value": 6.35, "unit": "mm"},
                     "flutes": {"value": 3}},
    })
    regenerated = mapping.record_to_tool(record)
    assert regenerated["description"] == "renamed on server"
    assert regenerated["expressions"]["tool_description"] \
        == "'renamed on server'"
    assert regenerated["geometry"]["DC"] == 6.35
    assert regenerated["expressions"]["tool_diameter"] == "6.35 mm"
    assert regenerated["geometry"]["NOF"] == 3
    assert regenerated["expressions"]["tool_numberOfFlutes"] == "3"


def test_record_to_tool_converts_canonical_units(sample_doc):
    tool = tool_named(sample_doc, "mysterybit")      # a metric tool
    record = _record_for(tool, canonical={
        "geometry": {"diameter": {"value": 0.25, "unit": "in"}},
    })
    regenerated = mapping.record_to_tool(record)
    assert regenerated["geometry"]["DC"] == 6.35


def test_record_to_tool_rebuilds_presets(sample_doc):
    tool = tool_named(sample_doc, "mysterybit")
    record = _record_for(tool, canonical={
        "presets": {"value": [
            {"origin": "fusion360", "label": "Default preset",
             "material": {"name": "all"},
             "vc": {"value": 78.54, "unit": "m/min"}},
            {"origin": "sandvik", "label": "Steel",
             "material": {"name": "Steel"},
             "vc": {"value": 120, "unit": "m/min"},
             "fz": {"value": 0.04, "unit": "mm"}},
        ], "source": "derived:preset-union"},
    })
    regenerated = mapping.record_to_tool(record)
    presets = regenerated["start-values"]["presets"]
    names = [p["name"] for p in presets]
    # Fusion's own native preset survives verbatim; sandvik's materializes.
    assert names == ["Default preset", "sandvik: Steel"]
    external = presets[1]
    assert external[presetsync.EXTERNAL_KEY]["origin"] == "sandvik"
    assert external["n"] > 0 and external["v_f"] > 0


def test_record_to_tool_requires_fusion_section():
    assert mapping.record_to_tool({"canonical": {}}) is None


def test_synth_tool_from_canonical_only():
    record = {
        "internal": {"id": "rec-9"},
        "canonical": {
            "name": {"value": "6mm 3FL carbide"},
            "geometry": {
                "shape": {"value": "endmill"},
                "diameter": {"value": 6, "unit": "mm"},
                "length": {"value": 50, "unit": "mm"},
                "flutes": {"value": 3},
            },
        },
    }
    tool = mapping.synth_tool(record)
    assert tool["type"] == "flat end mill"
    assert tool["unit"] == "millimeters"
    geo = tool["geometry"]
    assert geo["DC"] == 6 and geo["OAL"] == 50 and geo["NOF"] == 3
    # No stated flute length -> display fallback min(3*DC, OAL/2), and the
    # full ladder Fusion validates: OAL > LB >= shoulder-length >= LCF.
    assert geo["LCF"] == geo["shoulder-length"] == geo["LB"] == 18
    assert geo["shoulder-diameter"] == 6
    assert geo["assemblyGaugeLength"] == geo["LB"] < geo["OAL"]
    assert tool["description"] == "6mm 3FL carbide"
    # deterministic guid: same record -> same guid on every export
    assert tool["guid"] == mapping.synth_tool(record)["guid"]


def test_synth_tool_geometry_ladder_from_stated_flute_length():
    record = {
        "internal": {"id": "rec-l"},
        "canonical": {
            "name": {"value": '1/4" 2 Flute'},
            "geometry": {
                "shape": {"value": "endmill"},
                "diameter": {"value": 6.35},
                "cutting_edge_height": {"value": 30.0},
                "length": {"value": 50.0},
                "shank_diameter": {"value": 9.52},
                "flutes": {"value": 2},
            },
        },
    }
    geo = mapping.synth_tool(record)["geometry"]
    assert geo["OAL"] == 50 and geo["LCF"] == 30
    assert geo["shoulder-length"] == geo["LB"] == 30   # equality is accepted
    assert geo["SFDM"] == 9.52 and geo["shoulder-diameter"] == 6.35
    # A stated flute length >= OAL is implausible: fall back, never emit a
    # ladder Fusion rejects.
    record["canonical"]["geometry"]["cutting_edge_height"]["value"] = 60.0
    geo = mapping.synth_tool(record)["geometry"]
    assert geo["LCF"] == geo["LB"] < geo["OAL"]


def test_synth_tool_type_family_fields_and_default_presets():
    # Reproduces what Fusion's editor writes when repairing a synthesized
    # tool: CSP/HAND + SFDM fallback on mills, SIG (no shoulder-diameter)
    # on drills, TA/tip-diameter on chamfer mills, and a stock preset when
    # the tool has none (a tool with zero presets is itself flagged).
    def rec(shape, **geo):
        geometry = {"shape": {"value": shape},
                    "diameter": {"value": 3.18},
                    "length": {"value": 50.0}}
        for key, value in geo.items():
            geometry[key] = {"value": value}
        return {"internal": {"id": "rec-%s" % shape},
                "canonical": {"name": {"value": shape}, "geometry": geometry}}

    drill = mapping.synth_tool(rec("drill", flutes=2))
    geo = drill["geometry"]
    assert geo["CSP"] is False and geo["HAND"] is True
    assert geo["SIG"] == 118 and geo["SFDM"] == 3.18
    assert "shoulder-diameter" not in geo
    [preset] = drill["start-values"]["presets"]
    assert preset["name"] == "" and preset["n"] == 5000
    assert preset["v_f_plunge"] == preset["v_f_retract"] == 1000
    assert preset["use-feed-per-revolution"] is False
    assert "f_z" not in preset and "v_f" not in preset

    chamfer = mapping.synth_tool(rec("chamfer", flutes=8))
    geo = chamfer["geometry"]
    assert geo["TA"] == 45 and geo["tip-diameter"] == 0
    [preset] = chamfer["start-values"]["presets"]
    assert preset["v_f"] == 1000 and preset["v_f_plunge"] == round(
        1000 / 3.0, 10)
    assert preset["f_z"] == round(1000 / (5000 * 8), 10)
    assert preset["v_c"] == 5000 * 3.141592653589793 * 3.18 / 1000
    # deterministic guid -> re-exports never churn
    assert preset["guid"] == mapping.synth_tool(
        rec("chamfer", flutes=8))["start-values"]["presets"][0]["guid"]

    import math
    dovetail = mapping.synth_tool(
        rec("dovetail", cutting_edge_height=0.9, flutes=8))
    geo = dovetail["geometry"]
    assert geo["TA"] == 30 and geo["RE"] == 0
    # Fusion requires the dovetail's neck: DC - 2*LCF*tan(TA).
    assert math.isclose(geo["shoulder-diameter"],
                        3.18 - 2 * 0.9 * math.tan(math.radians(30)))
    assert geo["shoulder-diameter"] != geo["DC"]
    # An implausibly long flare would go negative: clamped, never emitted.
    deep = mapping.synth_tool(
        rec("dovetail", cutting_edge_height=9.0, flutes=8))
    assert deep["geometry"]["shoulder-diameter"] == 3.18 * 0.05

    saw = mapping.synth_tool(
        rec("slittingsaw", shank_diameter=15.0, flutes=20))
    geo = saw["geometry"]
    assert saw["type"] == "slot mill" and geo["RE"] == 0
    # The "flute length" of a saw is its blade thickness — thin, and the
    # shoulder above the blade is the arbor (the shank), not the blade.
    assert geo["LCF"] == round(3.18 * 0.05, 3) < 1
    assert geo["shoulder-diameter"] == 15.0

    probe = mapping.synth_tool(rec("probe"))
    assert "BMC" not in probe
    assert "CSP" not in probe["geometry"]
    [preset] = probe["start-values"]["presets"]
    assert preset == {"guid": preset["guid"], "name": "",
                      "v_f_leadIn": 1000, "v_f_link": 3000,
                      "v_f_measure": 102}


def test_synth_tool_probe_uses_reduced_schema():
    record = {
        "internal": {"id": "rec-p"},
        "canonical": {
            "name": {"value": "Probe"},
            "geometry": {
                "shape": {"value": "probe"},
                "diameter": {"value": 3.0},
                "length": {"value": 50.0},
                "shank_diameter": {"value": 4.0},
            },
        },
    }
    geo = mapping.synth_tool(record)["geometry"]
    # Mirrors Fusion's own probe exports: DC/LB/SFDM, no OAL/LCF/shoulder.
    assert geo == {"DC": 3.0, "SFDM": 4.0, "LB": 50.0,
                   "assemblyGaugeLength": 50.0}


def test_synth_tool_unitless_leaves_are_millimeters():
    # FreeCAD asserts bare mm values with no unit key (its client falls back
    # `unit or "mm"` the same way) — a unitless record must synthesize, not
    # skip. Regression from the first live sandbox run (18/18 skipped).
    record = {
        "internal": {"id": "rec-fc"},
        "canonical": {
            "name": {"value": '1/4" 2 Flute', "source": "asserted:freecad"},
            "geometry": {
                "shape": {"value": "endmill", "source": "asserted:freecad"},
                "diameter": {"value": 6.35, "source": "asserted:freecad"},
                "shank_diameter": {"value": 9.52,
                                   "source": "asserted:freecad"},
                "flutes": {"value": 2, "source": "asserted:freecad"},
            },
        },
    }
    tool = mapping.synth_tool(record)
    assert tool is not None
    assert tool["unit"] == "millimeters"
    assert tool["geometry"]["DC"] == 6.35
    assert tool["geometry"]["SFDM"] == 9.52
    assert tool["geometry"]["NOF"] == 2


def test_synth_tool_honest_skips():
    assert mapping.synth_tool({"canonical": {}}) is None
    assert mapping.synth_tool({"canonical": {
        "geometry": {"shape": {"value": "endmill"}}}}) is None  # no diameter
    assert mapping.synth_tool({"canonical": {
        "geometry": {"shape": {"value": "lathe-insert"},
                     "diameter": {"value": 6, "unit": "mm"}}}}) is None
