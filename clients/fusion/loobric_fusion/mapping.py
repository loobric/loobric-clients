# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT

"""Mapping between Fusion tool dicts and the Loobric sectioned schema.

Pure functions, no network — fully testable headless.

- A Fusion tool -> a **ToolInstanceRecord**. The full original tool dict
  rides verbatim in ``clients.fusion360.data.tool`` (lossless — expressions,
  post-process, holder, start-values all survive). The well-understood
  ISO-13399-coded geometry, the name and the shape are surfaced as canonical
  **asserts**. Nothing is fabricated: a value we can't determine is simply
  not asserted (vendor/product-id have no canonical home on an instance and
  stay in the client section).
- Identity: the tool ``guid`` is the natural key — it becomes
  ``client_item_id`` (the server-held re-adoption fallback); the guid ->
  ``internal.id`` map is kept in the local state file. Nothing extra is
  written into the Fusion file: Fusion's tolerance for unknown per-tool keys
  is unproven and the file must re-import cleanly.

Lossless regeneration rule: on export the verbatim client copy is the base
and a canonical value overwrites a geometry code only when it actually
differs — parallel ``expressions`` entries are updated in step, because
Fusion recomputes geometry from expressions and a stale one would silently
undo the overlay.
"""
import copy
import math
from collections import namedtuple

from . import CLIENT_NAME, presetsync

# Fusion per-tool "unit" -> the unit stamped on canonical geometry leaves.
UNIT_MAP = {"millimeters": "mm", "inches": "in"}

# ISO-13399/GTC geometry codes -> canonical geometry keys (quantity-valued).
# Only the codes with a ratified canonical home; everything else (RE, LB, TA,
# DCX, shoulder-*, assemblyGaugeLength, ...) rides the client section.
QUANTITY_CODES = {
    "DC": "diameter",
    "OAL": "length",
    "LCF": "cutting_edge_height",
    "SFDM": "shank_diameter",
}
INT_CODES = {
    "NOF": "flutes",
}

# Geometry codes / doc fields with a parallel parametric expression key.
# When an overlay changes the resolved number, the expression must follow.
EXPRESSION_KEYS = {
    "DC": "tool_diameter",
    "SFDM": "tool_shaftDiameter",
    "NOF": "tool_numberOfFlutes",
}

# Fusion tool "type" -> canonical geometry.shape (the FreeCAD-rooted shape
# vocabulary the spec-label renderer also draws). Conservative: an unmapped
# type gets no shape assert — honest absence over a wrong silhouette.
TYPE_TO_SHAPE = {
    "flat end mill": "endmill",
    "ball end mill": "ballend",
    "bull nose end mill": "bullnose",
    "chamfer mill": "chamfer",
    "face mill": "facemill",
    "dovetail mill": "dovetail",
    "radius mill": "radius",
    "drill": "drill",
    "spot drill": "spotdrill",
    "counter sink": "countersink",
    "reamer": "reamer",
    "tap right hand": "tap",
    "tap left hand": "tap",
    "thread mill": "threadmill",
    "slot mill": "slittingsaw",
    "probe": "probe",
}
# The reverse, for synthesizing a Fusion tool from canonical only. First
# Fusion type listed above per shape wins (tap -> right hand).
SHAPE_TO_TYPE = {}
for _ftype, _shape in TYPE_TO_SHAPE.items():
    SHAPE_TO_TYPE.setdefault(_shape, _ftype)

# Fusion library members that are not cutting tools and never become records.
NON_TOOL_TYPES = {"holder"}

# Fusion type families with distinct schemas (observed from what Fusion's own
# editor writes when it "fixes" a tool — there is no published schema):
# drills carry SIG (point angle) and no shoulder-diameter; probes have a
# reduced geometry and a lead-in/link/measure preset instead of cutting data.
DRILL_TYPES = {"drill", "spot drill", "counter sink", "reamer"}

ToolSections = namedtuple("ToolSections", ["data", "client_item_id", "asserts"])


def _leaf_value(record, *path):
    """canonical.<path...>.value from a record dict, or None."""
    node = (record or {}).get("canonical") or {}
    for key in path[:-1]:
        node = node.get(key) or {}
    leaf = node.get(path[-1])
    return leaf.get("value") if isinstance(leaf, dict) else None


def _leaf_unit(record, *path):
    node = (record or {}).get("canonical") or {}
    for key in path[:-1]:
        node = node.get(key) or {}
    leaf = node.get(path[-1])
    return leaf.get("unit") if isinstance(leaf, dict) else None


def _convert_length(value, from_unit, to_unit):
    """mm <-> in, or None when the pair isn't convertible (never guessed)."""
    if from_unit == to_unit:
        return value
    if from_unit == "mm" and to_unit == "in":
        return value / 25.4
    if from_unit == "in" and to_unit == "mm":
        return value * 25.4
    return None


def tool_name(tool):
    """The record name a Fusion tool maps to: its description, else its
    product id, else its type."""
    return (tool.get("description") or tool.get("product-id")
            or tool.get("type") or "(unnamed tool)")


def tool_guid(tool):
    guid = tool.get("guid")
    return str(guid).strip("{}") if guid else None


def tool_to_sections(tool):
    """A Fusion tool dict -> (client data payload, client_item_id, asserts).

    ``asserts`` is a list of ``(path, value, unit_or_None)``, ready for the
    assert door with actor "fusion360"."""
    data = {"tool": copy.deepcopy(tool)}
    asserts = [("name", tool_name(tool), None)]
    shape = TYPE_TO_SHAPE.get(str(tool.get("type") or "").lower())
    if shape:
        asserts.append(("geometry.shape", shape, None))
    unit = UNIT_MAP.get(tool.get("unit"))
    geometry = tool.get("geometry") or {}
    if unit:  # an unknown unit system asserts no dimensioned value
        for code, key in QUANTITY_CODES.items():
            value = geometry.get(code)
            if isinstance(value, (int, float)) and value > 0:
                asserts.append(("geometry.%s" % key, value, unit))
    for code, key in INT_CODES.items():
        value = geometry.get(code)
        if isinstance(value, (int, float)) and value > 0:
            asserts.append(("geometry.%s" % key, int(value), None))
    return ToolSections(data=data, client_item_id=tool_guid(tool),
                        asserts=asserts)


def record_presets(record, catalog_entries=None):
    """The union a Fusion file should reflect: the record's own derived
    presets plus its linked catalog type's entries (never copied onto the
    instance server-side, so fetched separately by the caller)."""
    union = list(_leaf_value(record, "presets") or [])
    union += list(catalog_entries or [])
    return union


def record_to_tool(record, catalog_entries=None):
    """Regenerate a Fusion tool from a record that carries a fusion360
    section. The verbatim client copy is the base; canonical wins where it
    actually differs; presets are rebuilt as own + materialized externals."""
    section = ((record.get("clients") or {}).get(CLIENT_NAME) or {})
    base = (section.get("data") or {}).get("tool")
    if not isinstance(base, dict):
        return None
    tool = copy.deepcopy(base)

    name = _leaf_value(record, "name")
    if name and name != tool.get("description"):
        tool["description"] = name
        if isinstance(tool.get("expressions"), dict) \
                and "tool_description" in tool["expressions"]:
            tool["expressions"]["tool_description"] = "'%s'" % name

    tool_unit = UNIT_MAP.get(tool.get("unit"))
    geometry = tool.setdefault("geometry", {})
    expressions = tool.get("expressions")
    for code, key in QUANTITY_CODES.items():
        value, unit = _leaf_value(record, "geometry", key), \
            _leaf_unit(record, "geometry", key)
        if value is None or tool_unit is None:
            continue
        converted = _convert_length(value, unit or tool_unit, tool_unit)
        if converted is None:
            continue
        current = geometry.get(code)
        if not isinstance(current, (int, float)) \
                or abs(converted - current) > 1e-9:
            geometry[code] = converted
            expr_key = EXPRESSION_KEYS.get(code)
            if isinstance(expressions, dict) and expr_key in (
                    expressions or {}):
                expressions[expr_key] = "%g %s" % (converted, tool_unit)
    for code, key in INT_CODES.items():
        value = _leaf_value(record, "geometry", key)
        if value is None:
            continue
        if geometry.get(code) != value:
            geometry[code] = int(value)
            expr_key = EXPRESSION_KEYS.get(code)
            if isinstance(expressions, dict) and expr_key in (
                    expressions or {}):
                expressions[expr_key] = "%d" % int(value)

    union = record_presets(record, catalog_entries)
    existing = (tool.get("start-values") or {}).get("presets")
    own, _stale = presetsync.split_native(existing, union)
    external = presetsync.externalize(union, tool)
    if own or external or existing is not None:
        tool.setdefault("start-values", {})["presets"] = own + external
    return tool


_PI = 3.141592653589793


def default_preset(ftype, funit, diameter, flutes, record_id):
    """Fusion's own stock preset, reproduced — a library tool with NO preset
    at all is flagged "missing some required data", and these are the exact
    values Fusion's editor fabricates when it repairs one (n=5000,
    v_f=1000 mm/min, plunge=v_f/3, engineering values derived from those;
    probes get the stock lead-in/link/measure feeds). Machine-number
    template, not cutting advice — the user tunes it in Fusion."""
    metric = funit != "inches"
    scale = 1000.0 if metric else 12.0
    guid = presetsync.external_guid("fusion-default", record_id)
    if ftype == "probe":
        vf = 1000 if metric else round(1000 / 25.4, 3)
        return {"guid": guid, "name": "",
                "v_f_leadIn": vf,
                "v_f_link": 3000 if metric else round(3000 / 25.4, 3),
                "v_f_measure": 102 if metric else round(102 / 25.4, 3)}
    n = 5000
    vf = 1000 if metric else round(1000 / 25.4, 3)
    plunge = round(vf / 3.0, 10)
    vc = n * _PI * diameter / scale
    preset = {"guid": guid, "name": "",
              "material": {"category": "all", "query": "",
                           "use-hardness": False},
              "n": n, "v_c": vc, "tool-coolant": "flood"}
    if ftype in DRILL_TYPES:
        preset.update({"use-feed-per-revolution": False,
                       "v_f_plunge": vf, "v_f_retract": vf})
        return preset
    nof = flutes if isinstance(flutes, int) and flutes > 0 else 2
    preset.update({"n_ramp": n,
                   "f_z": round(vf / (n * nof), 10),
                   "f_n": round(plunge / n, 10),
                   "v_f": vf, "v_f_leadIn": vf, "v_f_leadOut": vf,
                   "v_f_transition": vf,
                   "v_f_plunge": plunge, "v_f_ramp": plunge,
                   "ramp-angle": 2,
                   "use-stepdown": False, "use-stepover": False})
    return preset


def synth_tool(record, catalog_entries=None):
    """Best-effort Fusion tool from canonical only, for records other clients
    created (EXPERIMENTAL — needs an in-Fusion import smoke test). Requires a
    mappable shape and a diameter; returns None otherwise, counted by the
    caller as an honest skip."""
    shape = _leaf_value(record, "geometry", "shape")
    ftype = SHAPE_TO_TYPE.get(shape or "")
    diameter = _leaf_value(record, "geometry", "diameter")
    # A unitless canonical leaf is millimeters — the ecosystem convention
    # (the FreeCAD client asserts bare mm values and falls back the same
    # way when regenerating), not a guess.
    unit = _leaf_unit(record, "geometry", "diameter") or "mm"
    funit = {"mm": "millimeters", "in": "inches"}.get(unit)
    if not ftype or not isinstance(diameter, (int, float)) or not funit:
        return None
    record_id = ((record.get("internal") or {}).get("id")) or ""
    geometry = {"DC": diameter}
    for code, key in QUANTITY_CODES.items():
        if code == "DC":
            continue
        value = _leaf_value(record, "geometry", key)
        vunit = _leaf_unit(record, "geometry", key)
        if isinstance(value, (int, float)):
            converted = _convert_length(value, vunit or unit, unit)
            if converted is not None:
                geometry[code] = converted
    flutes = _leaf_value(record, "geometry", "flutes")
    if isinstance(flutes, (int, float)) and flutes > 0:
        geometry["NOF"] = int(flutes)

    # Fusion validates a geometry LADDER (no published schema — these rules
    # come from its error messages plus what its own editor writes when it
    # "fixes" a tool): OAL > LB >= shoulder-length >= LCF, with equality
    # fine at the lower joints, plus per-type required fields — CSP/HAND on
    # everything but probes, SFDM defaulting to DC, SIG on drills (which
    # carry no shoulder-diameter), TA/tip-diameter on chamfer mills.
    # Probes are reduced: DC/LB/SFDM only, no OAL/LCF.
    oal = geometry.pop("OAL", None)
    if shape == "probe":
        geometry.pop("LCF", None)
        geometry.setdefault("SFDM", diameter)
        if oal is not None:
            geometry["LB"] = oal
            geometry["assemblyGaugeLength"] = oal
    else:
        geometry["CSP"] = False
        geometry["HAND"] = True
        geometry.setdefault("SFDM", diameter)
        if ftype in DRILL_TYPES:
            geometry.setdefault("SIG", 118)
        if ftype == "chamfer mill":
            geometry.setdefault("TA", 45)
            geometry.setdefault("tip-diameter", 0)
        if ftype == "dovetail mill":
            geometry.setdefault("TA", 30)
            geometry.setdefault("RE", 0)
        if ftype == "slot mill":
            geometry.setdefault("RE", 0)
        if oal is not None:
            geometry["OAL"] = oal
            lcf = geometry.get("LCF")
            if not isinstance(lcf, (int, float)) or not 0 < lcf < oal:
                # No stated (or no plausible) flute length: a display
                # starting point so the tool validates — the user trues it
                # up in Fusion. For a slot mill the "flute length" is the
                # BLADE THICKNESS — thin relative to the diameter, not a
                # multiple of it.
                if ftype == "slot mill":
                    lcf = round(diameter * 0.05, 3)
                else:
                    lcf = round(min(3 * diameter, oal * 0.5), 4)
            geometry["LCF"] = lcf
            geometry["shoulder-length"] = lcf
            if ftype == "dovetail mill":
                # The neck above the dovetail flare: Fusion computes (and
                # requires) shoulder-diameter = DC - 2*LCF*tan(TA); a
                # shoulder as wide as the cutting diameter is rejected.
                neck = diameter - 2 * lcf * math.tan(
                    math.radians(geometry["TA"]))
                geometry["shoulder-diameter"] = max(neck, diameter * 0.05)
            elif ftype == "slot mill":
                # The shoulder above a saw blade is the arbor, not the
                # blade: use the shank when known.
                geometry["shoulder-diameter"] = geometry.get(
                    "SFDM") or round(diameter * 0.25, 3)
            elif ftype not in DRILL_TYPES:
                geometry["shoulder-diameter"] = diameter
            geometry["LB"] = lcf
            geometry["assemblyGaugeLength"] = lcf
    tool = {
        "description": _leaf_value(record, "name") or "(unnamed tool)",
        "guid": presetsync.external_guid("loobric-record", record_id),
        "type": ftype,
        "unit": funit,
        "vendor": "",
        "product-id": "",
        "product-link": "",
        "geometry": geometry,
        "post-process": {"break-control": False, "comment": "",
                         "diameter-offset": 0, "length-offset": 0,
                         "live": True, "manual-tool-change": False,
                         "number": 0, "turret": 0},
    }
    if shape != "probe":     # probes carry no body-material concept
        tool["BMC"] = "unspecified"
    external = presetsync.externalize(
        record_presets(record, catalog_entries), tool)
    tool["start-values"] = {"presets": external or [
        default_preset(ftype, funit, diameter,
                       geometry.get("NOF"), record_id)]}
    return tool
