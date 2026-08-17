# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT
import math

from conftest import tool_named
from loobric_fusion import presetsync


def _contribution_map(contributions):
    return {body["label"]: body for body in contributions}


def test_translate_metric_tool(sample_doc):
    tool = tool_named(sample_doc, "mysterybit")
    contributions, skipped = presetsync.translate(tool)
    assert skipped == []
    [body] = contributions
    assert body["origin"] == "fusion360"
    assert body["label"] == "Default preset"
    assert body["material"] == {"name": "all"}
    assert body["vc"] == {"value": 78.5398163397448, "unit": "m/min"}
    assert body["fz"] == {"value": 0.05, "unit": "mm"}
    assert body["ratio"] == {"value": 0.3333}   # v_f_plunge / v_f
    assert body["extras"]["tool_coolant"] == "flood"
    assert body["extras"]["ramp_angle"] == 2
    assert "op_type" not in body                # Fusion presets carry no op


def test_translate_inch_tool_units(sample_doc):
    tool = tool_named(sample_doc, "4 Flute HSS")
    contributions, skipped = presetsync.translate(tool)
    assert skipped == []
    [body] = contributions
    assert body["vc"]["unit"] == "ft/min"
    assert math.isclose(body["vc"]["value"], 99.9998394068759)
    assert body["fz"] == {"value": 0.0025, "unit": "in"}
    assert body["ratio"] == {"value": 0.1}


def test_translate_floor_probe_and_zeros(sample_doc):
    # The probe preset has no material statement at all.
    probe = tool_named(sample_doc, "probe")
    contributions, skipped = presetsync.translate(probe)
    assert contributions == []
    assert skipped == [("Default preset",
                        "no material statement — cannot normalize")]
    # The Sandvik default preset states a material but every value is 0.
    sandvik = tool_named(sample_doc, "CoroMill")
    contributions, skipped = presetsync.translate(sandvik)
    assert contributions == []
    assert skipped == [("Default Preset", "no engineering values")]


def test_translate_skips_unnamed_fusion_default_templates():
    # Fusion's editor fabricates a name-"" preset (n=5000, v_f=1000) when it
    # repairs a tool with no cutting data; template numbers must never be
    # promoted as fusion360 recommendations.
    tool = {"unit": "millimeters", "start-values": {"presets": [
        {"name": "", "guid": "g", "n": 5000, "v_c": 31.4159, "f_z": 0.025,
         "v_f": 1000, "material": {"category": "all"}},
    ]}}
    contributions, skipped = presetsync.translate(tool)
    assert contributions == []
    assert skipped == [("(unnamed)",
                        "unnamed — Fusion default template, "
                        "not a recommendation")]


def test_translate_never_promotes_externals():
    tool = {"unit": "millimeters", "start-values": {"presets": [
        {"name": "sandvik: Steel", "v_c": 100, "f_z": 0.05,
         "material": {"category": "all"},
         presetsync.EXTERNAL_KEY: {"origin": "sandvik", "label": "Steel"}},
    ]}}
    contributions, skipped = presetsync.translate(tool)
    assert contributions == [] and skipped == []


def test_duplicate_labels_deduped():
    presets = [
        {"name": "Default", "guid": "aaaabbbb-1111"},
        {"name": "Default", "guid": "ccccdddd-2222"},
    ]
    assert presetsync.derive_labels(presets) == [
        "Default", "Default [ccccdddd]"]


def test_to_native_metric_computes_machine_numbers():
    tool = {"unit": "millimeters", "geometry": {"DC": 6, "NOF": 2}}
    entry = {"origin": "sandvik", "label": "Steel", "id": "p1",
             "source": "asserted:human@web",
             "material": {"name": "Steel"},
             "vc": {"value": 100, "unit": "m/min"},
             "fz": {"value": 0.05, "unit": "mm"}}
    native = presetsync.to_native(entry, tool)
    assert native["name"] == "sandvik: Steel"
    assert native["material"]["query"] == "Steel"
    assert native["f_z"] == 0.05
    assert native["n"] == round(100 * 1000 / (math.pi * 6), 2) == 5305.16
    # v_c is derived back from the STORED (rounded) n — Fusion recomputes
    # v_c from n on save, so anything else flags the preset inconsistent.
    assert native["v_c"] == 5305.16 * math.pi * 6 / 1000
    assert math.isclose(native["v_c"], 100, rel_tol=1e-5)
    assert native["v_f"] == round(5305.16 * 0.05 * 2, 3)
    assert native[presetsync.EXTERNAL_KEY]["origin"] == "sandvik"


def test_to_native_carries_fusions_full_field_set():
    # Regression: a materialized preset missing these fields makes Fusion's
    # library UI flag the tool with an error until it is opened and saved
    # (observed 2026-08-17). Pin the exact key set Fusion's editor writes.
    tool = {"unit": "millimeters", "geometry": {"DC": 5, "NOF": 4}}
    entry = {"origin": "sandvik", "label": "P steel finishing",
             "material": {"name": "P (steel)"},
             "vc": {"value": 150, "unit": "m/min"},
             "fz": {"value": 0.04, "unit": "mm"},
             "ratio": {"value": 0.25},
             "extras": {"tool_coolant": "flood", "ramp_angle": 2}}
    native = presetsync.to_native(entry, tool)
    assert set(native) == {
        "name", "guid", "material", "n", "n_ramp", "f_n", "f_z", "v_c",
        "v_f", "v_f_leadIn", "v_f_leadOut", "v_f_transition", "v_f_plunge",
        "v_f_ramp", "ramp-angle", "use-stepdown", "use-stepover",
        "tool-coolant", presetsync.EXTERNAL_KEY}
    assert native["n"] == 9549.3
    assert native["v_c"] == 9549.3 * math.pi * 5 / 1000   # self-consistent
    assert native["v_f"] == native["v_f_transition"] == 1527.888
    assert native["v_f_plunge"] == native["v_f_ramp"] == 381.972
    assert native["f_n"] == 0.04                          # plunge per rev
    assert native["ramp-angle"] == 2
    assert native["use-stepdown"] is False
    assert native["tool-coolant"] == "flood"


def test_to_native_converts_into_inch_tool():
    tool = {"unit": "inches", "geometry": {"DC": 0.375, "NOF": 4}}
    entry = {"origin": "kennametal", "label": "6061",
             "vc": {"value": 300, "unit": "sfm"},
             "fz": {"value": 0.0635, "unit": "mm"},
             "material": {"name": "6061"}}
    native = presetsync.to_native(entry, tool)
    assert math.isclose(native["v_c"], 300, rel_tol=1e-4)   # sfm IS ft/min
    assert math.isclose(native["f_z"], 0.0025)
    assert native["n"] == round(300 * 12 / (math.pi * 0.375), 2)
    assert native["v_c"] == native["n"] * math.pi * 0.375 / 12


def test_to_native_defaults_ratio_for_nonzero_plunge_feeds():
    # Fusion flags "Plunge/Ramp feedrate must be positive and non-zero" on a
    # preset with zero plunge feeds; a server entry with no stated ratio
    # gets the FreeCAD client's 0.33 display default (regression from the
    # first --all import: claude-origin presets carry vc+fz but no ratio).
    tool = {"unit": "millimeters", "geometry": {"DC": 3.18, "NOF": 2}}
    entry = {"origin": "claude", "label": "aluminum-general",
             "material": {"name": "Aluminum"},
             "vc": {"value": 60, "unit": "m/min"},
             "fz": {"value": 0.013, "unit": "mm"}}
    native = presetsync.to_native(entry, tool)
    assert native["v_f"] > 0
    assert native["v_f_plunge"] == native["v_f_ramp"] == round(
        native["v_f"] * 0.33, 3) > 0
    assert native["f_n"] > 0


def test_to_native_unknown_unit_is_dropped_not_guessed():
    tool = {"unit": "millimeters", "geometry": {}}
    entry = {"origin": "x", "label": "y",
             "vc": {"value": 9, "unit": "furlong/fortnight"},
             "material": {"name": "m"}}
    assert presetsync.to_native(entry, tool) is None
    entry["fz"] = {"value": 0.1, "unit": "mm"}
    native = presetsync.to_native(entry, tool)
    assert native["v_c"] == 0 and native["f_z"] == 0.1


def test_externalize_skips_own_origin_dedupes_and_sorts():
    tool = {"unit": "millimeters", "geometry": {"DC": 10, "NOF": 3}}
    entries = [
        {"origin": "fusion360", "label": "mine",
         "vc": {"value": 1, "unit": "m/min"}, "material": {"name": "m"}},
        {"origin": "b", "label": "z", "vc": {"value": 2, "unit": "m/min"},
         "material": {"name": "m"}},
        {"origin": "a", "label": "y", "vc": {"value": 3, "unit": "m/min"},
         "material": {"name": "m"}},
        {"origin": "a", "label": "y", "vc": {"value": 4, "unit": "m/min"},
         "material": {"name": "m"}},
    ]
    out = presetsync.externalize(entries, tool)
    assert [p["name"] for p in out] == ["a: y", "b: z"]
    # deterministic guid: same identity -> same guid on every regeneration
    assert out[0]["guid"] == presetsync.external_guid("a", "y")


def test_split_native_marker_and_name_fallback():
    server = [{"origin": "sandvik", "label": "Steel"},
              {"origin": "fusion360", "label": "sandvik-ish"}]
    presets = [
        {"name": "My roughing"},                       # own
        {"name": "x", presetsync.EXTERNAL_KEY: {}},    # marker
        {"name": "sandvik: Steel"},                    # stripped marker
        {"name": "fusion360: sandvik-ish"},            # own origin: NOT external
    ]
    own, external = presetsync.split_native(presets, server)
    assert [p["name"] for p in own] == ["My roughing",
                                       "fusion360: sandvik-ish"]
    assert len(external) == 2


class FakePresetClient:
    def __init__(self, entries=None, fail_contribute=False):
        self.entries = entries or []
        self.contributed = []
        self.deleted = []
        self.fail_contribute = fail_contribute

    def contribute_preset(self, resource, record_id, **body):
        if self.fail_contribute:
            raise RuntimeError("403 missing scope")
        self.contributed.append((resource, record_id, body))

    def list_presets(self, resource, record_id):
        return self.entries

    def delete_preset(self, resource, record_id, entry_id):
        self.deleted.append(entry_id)


def test_promote_contributes_and_prunes(sample_doc):
    tool = tool_named(sample_doc, "mysterybit")
    client = FakePresetClient(entries=[
        {"id": "stale", "origin": "fusion360", "label": "Old preset"},
        {"id": "keep", "origin": "fusion360", "label": "Default preset"},
        {"id": "cat", "origin": "fusion360", "label": "Gone",
         "scope": "catalog"},
        {"id": "other", "origin": "sandvik", "label": "Steel"},
    ])
    summary = presetsync.promote(client, "rec-1", tool)
    assert summary == {"promoted": 1, "skipped": 0, "pruned": 1, "blocked": 0}
    [(resource, record_id, body)] = client.contributed
    assert resource == "tool-instance-records" and record_id == "rec-1"
    assert body["actor"] == "fusion360"
    assert client.deleted == ["stale"]      # catalog + other origins protected


def test_promote_never_raises(sample_doc):
    tool = tool_named(sample_doc, "mysterybit")
    client = FakePresetClient(fail_contribute=True)
    summary = presetsync.promote(client, "rec-1", tool)
    assert summary["blocked"] == 1 and summary["promoted"] == 0


def test_promote_skips_tools_without_presets():
    client = FakePresetClient()
    summary = presetsync.promote(client, "rec-1", {"unit": "millimeters"})
    assert summary == {"promoted": 0, "skipped": 0, "pruned": 0, "blocked": 0}
    assert client.contributed == [] and client.deleted == []
