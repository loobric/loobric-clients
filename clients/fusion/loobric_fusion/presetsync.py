# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT

"""Fusion ``start-values`` presets <-> Loobric cutting data presets.

The server's design (loobric-server docs/PRESETS.md) makes translation the
CLIENT's job: the raw ``start-values`` block keeps riding the tool verbatim in
``clients.fusion360.data.tool`` (lossless), and this module additionally
translates each native preset into the ratified normal form and contributes it
through the preset door — mirroring loobric-freecad's presetsync.

Fusion's native preset (``start-values.presets[]``) carries machine numbers
(``n``, ``v_f``, ``v_f_*``) alongside the engineering values. Only the
engineering values normalize — raw feed and RPM are never persisted:

- ``v_c`` -> ``vc``. Fusion stores it in the tool's unit system: m/min for
  metric tools, ft/min for inch tools (verified against Fusion's own n/v_c
  arithmetic on real exports). The unit rides the leaf verbatim; the server
  never converts.
- ``f_z`` -> ``fz`` (mm or in per tooth, same rule).
- ``ratio`` is this client's own translation of its own data: Fusion states
  the plunge relationship as ``v_f_plunge``/``v_f``; when both are positive
  their quotient IS the vertical-feed ratio, no guessing involved.
- ``material`` is transcribed verbatim: the query string if the preset names
  one, else the category — including Fusion's ``"all"``, which is the source
  genuinely stating "any material", not an absence.
- Coolant, ramp angle and the preset's own guid ride ``extras`` (verbatim,
  non-comparable). The redundant machine numbers do not — they are
  derivations of vc/fz, not source data.

The floor: material + at least one engineering value. A preset below it (a
probe's ``v_f_measure``-only preset, an all-zeros default) stays
client-section-only, counted, never guessed.

Identity is ``(origin="fusion360", label)``; label = the preset's ``name``,
deduped within a tool by a guid suffix so replace-own never collides.

No Fusion imports; runs headless under pytest.
"""
import uuid

from . import CLIENT_NAME

ORIGIN = CLIENT_NAME

# Marker key on a NATIVE preset dict that says "this entry was materialized
# from the server's union, it is not Fusion's own": promotion skips it and
# regeneration refreshes it from the union. Caveat vs FreeCAD: Fusion's tool
# editor STRIPS unknown keys on save (confirmed 2026-08-17 against a real
# round trip), so recognition falls back to the "<origin>: <label>" name
# convention checked against the server's current entries (see split_native).
EXTERNAL_KEY = "loobric_external"

_PI = 3.141592653589793

# vc/fz units by the TOOL's unit system ("millimeters" | "inches").
_UNITS = {
    "millimeters": {"vc": "m/min", "fz": "mm", "dc_per_vc": 1000.0},
    "inches": {"vc": "ft/min", "fz": "in", "dc_per_vc": 12.0},
}

# Factors into each unit system's native vc/fz units, for materializing
# server entries whose origin used the other system. An unlisted unit is NOT
# guessed: that value is dropped and the entry carries whatever else
# translated.
_VC_TO_M_MIN = {"m/min": 1.0, "mmin": 1.0, "m/min.": 1.0,
                "sfm": 0.3048, "ft/min": 0.3048, "fpm": 0.3048}
_FZ_TO_MM = {"mm": 1.0, "mm/tooth": 1.0,
             "in": 25.4, "inch": 25.4, "in/tooth": 25.4}


def _tool_units(tool):
    return _UNITS.get(tool.get("unit"), _UNITS["millimeters"])


def _positive(value):
    return isinstance(value, (int, float)) and value > 0


def derive_labels(presets):
    """Stable per-tool labels: each preset's ``name`` (else "(unnamed)"),
    deduped by suffixing the preset guid's first 8 chars — duplicate
    "Default Preset" rows must not replace-own each other."""
    seen, labels = {}, []
    for preset in presets:
        base = str(preset.get("name") or "(unnamed)")
        if base in seen:
            tail = str(preset.get("guid") or "").strip("{}")[:8]
            label = "%s [%s]" % (base, tail or len(labels))
        else:
            label = base
        seen[base] = True
        labels.append(label)
    return labels


def translate(tool):
    """A Fusion tool dict -> preset contribution bodies.

    Returns ``(contributions, skipped)``; ``skipped`` is ``(label, reason)``
    for presets below the server's floor — they stay in the client section,
    honestly un-promoted."""
    contributions, skipped = [], []
    presets = (tool.get("start-values") or {}).get("presets")
    if not isinstance(presets, list):
        return contributions, skipped
    units = _tool_units(tool)
    native = [p for p in presets if isinstance(p, dict)]
    labels = derive_labels(native)
    for preset, label in zip(native, labels):
        if EXTERNAL_KEY in preset:
            continue          # materialized from the union — never re-promoted
        if not preset.get("name"):
            # An unnamed preset is Fusion's own repair/default template
            # (its editor fabricates one, name "", when a tool has no
            # cutting data) — template machine numbers, not a
            # recommendation. Stays in the client section.
            skipped.append((label, "unnamed — Fusion default template, "
                                   "not a recommendation"))
            continue
        material = preset.get("material")
        name = None
        if isinstance(material, dict):
            name = material.get("query") or material.get("category")
        if not name:
            skipped.append((label, "no material statement — cannot normalize"))
            continue
        body = {"origin": ORIGIN, "label": label,
                "material": {"name": str(name)}}
        vc, fz = preset.get("v_c"), preset.get("f_z")
        if _positive(vc):
            body["vc"] = {"value": vc, "unit": units["vc"]}
        if _positive(fz):
            body["fz"] = {"value": fz, "unit": units["fz"]}
        v_f, v_f_plunge = preset.get("v_f"), preset.get("v_f_plunge")
        if _positive(v_f) and _positive(v_f_plunge):
            body["ratio"] = {"value": round(v_f_plunge / v_f, 4)}
        if "vc" not in body and "fz" not in body and "ratio" not in body:
            skipped.append((label, "no engineering values"))
            continue
        extras = {}
        if preset.get("guid"):
            extras["fusion_guid"] = str(preset["guid"]).strip("{}")
        if preset.get("tool-coolant"):
            extras["tool_coolant"] = preset["tool-coolant"]
        if _positive(preset.get("ramp-angle")):
            extras["ramp_angle"] = preset["ramp-angle"]
        if extras:
            body["extras"] = extras
        contributions.append(body)
    return contributions, skipped


def _convert(leaf, factors):
    """A server {value, unit} leaf -> float in the factors' base unit, or
    None (never guessed)."""
    if not isinstance(leaf, dict):
        return None
    value, unit = leaf.get("value"), leaf.get("unit")
    if not isinstance(value, (int, float)) or unit is None:
        return None
    factor = factors.get(str(unit).strip().lower())
    return value * factor if factor is not None else None


def to_native(entry, tool):
    """Materialize one server union entry as a Fusion preset dict, marked
    external. Values land in the TOOL's unit system, and the machine numbers
    Fusion displays (n, v_f, plunge feeds) are computed from the tool's own
    DC/NOF — the client-side engineering->machine translation the server
    refuses to do. Returns None when nothing translates."""
    label = entry.get("label") or "(unnamed)"
    origin = entry.get("origin") or "?"
    units = _tool_units(tool)
    metric = units is _UNITS["millimeters"]

    vc_m_min = _convert(entry.get("vc"), _VC_TO_M_MIN)
    fz_mm = _convert(entry.get("fz"), _FZ_TO_MM)
    ratio_leaf = entry.get("ratio")
    ratio = ratio_leaf.get("value") if isinstance(ratio_leaf, dict) else None
    if vc_m_min is None and fz_mm is None and not _positive(ratio):
        return None
    if not _positive(ratio):
        # Fusion requires non-zero plunge/ramp feeds on a preset; an entry
        # with no stated ratio gets the same 0.33 default the FreeCAD
        # client uses when materializing (a display starting point, not a
        # canonical claim — the server entry still carries no ratio).
        ratio = 0.33

    vc = vc_m_min if metric else (
        None if vc_m_min is None else vc_m_min / 0.3048)
    fz = fz_mm if metric else (None if fz_mm is None else fz_mm / 25.4)

    geometry = tool.get("geometry") or {}
    dc, nof = geometry.get("DC"), geometry.get("NOF")
    n = v_f = 0
    if _positive(vc) and _positive(dc):
        # n = vc / (pi * DC), with DC in the tool's unit and vc per _UNITS
        # (m/min over mm needs x1000; ft/min over in needs x12).
        n = round(vc * units["dc_per_vc"] / (_PI * dc), 2)
        # Fusion treats the stored n as authoritative and recomputes v_c
        # from it on save; storing the origin's exact v_c next to a rounded
        # n makes the tool editor flag the preset as inconsistent. Derive
        # v_c back from the very n we store so the file validates as-is.
        vc = n * _PI * dc / units["dc_per_vc"]
    if _positive(n) and _positive(fz) and _positive(nof):
        v_f = round(n * fz * nof, 3)
    plunge = round(v_f * ratio, 3) if _positive(v_f) and _positive(ratio) else 0
    f_n = round(plunge / n, 6) if _positive(plunge) and _positive(n) else 0

    material = entry.get("material") or {}
    extras = entry.get("extras") or {}
    native = {
        "name": "%s: %s" % (origin, label),
        "guid": external_guid(origin, label),
        "material": {"category": "all",
                     "query": material.get("name") or "",
                     "use-hardness": False},
        "n": n, "n_ramp": n,
        "f_n": f_n,
        "f_z": fz or 0,
        "v_c": vc or 0,
        "v_f": v_f,
        "v_f_leadIn": v_f, "v_f_leadOut": v_f, "v_f_transition": v_f,
        "v_f_plunge": plunge, "v_f_ramp": plunge,
        "ramp-angle": extras.get("ramp_angle", 2),
        "use-stepdown": False,
        "use-stepover": False,
        "tool-coolant": extras.get("tool_coolant", "disabled"),
        EXTERNAL_KEY: {"origin": origin, "label": label,
                       "id": entry.get("id"),
                       "source": entry.get("source")},
    }
    return native


def external_guid(origin, label):
    """A deterministic guid for a materialized preset, so regeneration is
    stable and Fusion never sees a churned identity without a real change."""
    ns = uuid.uuid5(uuid.NAMESPACE_URL, "loobric-fusion-external")
    return str(uuid.uuid5(ns, "%s\x1f%s" % (origin, label)))


def externalize(entries, tool):
    """Server union entries -> deterministic, marked native presets.

    Non-fusion360 origins only (Fusion's own entries already live natively in
    the file), deduped by (origin, label), sorted for stable regeneration."""
    seen, out = set(), []
    for entry in entries or []:
        if not isinstance(entry, dict) or entry.get("origin") == ORIGIN:
            continue
        key = (entry.get("origin"), entry.get("label"))
        if key in seen:
            continue
        seen.add(key)
        native = to_native(entry, tool)
        if native is not None:
            out.append(native)
    out.sort(key=lambda p: (p[EXTERNAL_KEY]["origin"] or "",
                            p[EXTERNAL_KEY]["label"] or ""))
    return out


def split_native(presets, server_entries=None):
    """Partition a tool's presets: (fusion's own, externally-materialized).

    Recognition is the marker key first; failing that (Fusion's editor strips
    unknown keys on save) a preset whose name reads "<origin>: <label>"
    matching a live non-fusion server entry is still treated as external — an
    UNEDITED round trip must not fork someone else's recommendation into a
    fusion360 one. An edited name no longer matches, which forks it into a
    user-owned preset: exactly right, changed numbers are your recipe."""
    known = {"%s: %s" % (e.get("origin"), e.get("label"))
             for e in (server_entries or [])
             if isinstance(e, dict) and e.get("origin") != ORIGIN}
    own, external = [], []
    for preset in presets or []:
        if isinstance(preset, dict) and (
                EXTERNAL_KEY in preset or preset.get("name") in known):
            external.append(preset)
        else:
            own.append(preset)
    return own, external


def promote(client, record_id, tool, server_entries=None,
            log=lambda msg: None, fresh=False):
    """Contribute a tool's own presets (replace-own) and prune fusion360-
    origin server entries whose preset no longer exists locally.

    ``fresh``: the record was just created — nothing on the server can be
    stale, so the prune (and its GET) is skipped entirely.

    Never raises for policy reasons: a missing scope (403) or pre-preset
    server (404) logs and moves on — sync must not fail over presets.
    Returns a summary dict."""
    own, _external = split_native(
        (tool.get("start-values") or {}).get("presets"), server_entries)
    contributions, skipped = translate(
        {"unit": tool.get("unit"), "start-values": {"presets": own}})
    summary = {"promoted": 0, "skipped": len(skipped), "pruned": 0,
               "blocked": 0}
    for label, reason in skipped:
        log("  preset '%s' not promoted: %s" % (label, reason))
    if not isinstance((tool.get("start-values") or {}).get("presets"), list):
        return summary

    for body in contributions:
        try:
            client.contribute_preset(
                "tool-instance-records", record_id, actor=ORIGIN, **body)
            summary["promoted"] += 1
        except Exception as exc:
            summary["blocked"] += 1
            log("  preset '%s' contribution failed: %s"
                % (body["label"], exc))

    # Prune: fusion360-origin instance entries whose label vanished locally.
    if fresh:
        return summary
    labels = {body["label"] for body in contributions} \
        | {label for label, _ in skipped}
    pruned = prune(client, record_id, labels, log=log)
    summary["pruned"] += pruned["pruned"]
    summary["blocked"] += pruned["blocked"]
    return summary


def keep_labels(tool, server_entries=None):
    """The local preset labels a prune must keep: everything Fusion's own
    (promotable or floor-skipped), externals excluded."""
    own, _external = split_native(
        (tool.get("start-values") or {}).get("presets"), server_entries)
    contributions, skipped = translate(
        {"unit": tool.get("unit"), "start-values": {"presets": own}})
    return {body["label"] for body in contributions} \
        | {label for label, _ in skipped}


def prune(client, record_id, labels, log=lambda msg: None):
    """Delete fusion360-origin instance entries whose label vanished
    locally. Catalog-scope and other origins are never touched; a key
    without the delete door logs and moves on."""
    summary = {"pruned": 0, "blocked": 0}
    try:
        entries = client.list_presets("tool-instance-records", record_id)
    except Exception:
        return summary
    for entry in entries:
        if entry.get("origin") != ORIGIN or entry.get("scope") == "catalog":
            continue
        if entry.get("label") in labels:
            continue
        try:
            client.delete_preset("tool-instance-records", record_id,
                                 entry["id"])
            summary["pruned"] += 1
            log("  preset '%s' removed (deleted in Fusion)"
                % entry.get("label"))
        except Exception as exc:
            summary["blocked"] += 1
            log("  stale preset '%s' left on server (%s) — remove it in "
                "the Web UI" % (entry.get("label"), exc))
    return summary
