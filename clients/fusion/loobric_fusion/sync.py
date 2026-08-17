# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT

"""Import/export orchestration between a Fusion library file and the server.

Import (file -> server), per tool: find the record (state file first, then
re-adoption by ``client_item_id``), create or sync the client section, assert
canonical facts that actually changed, promote presets. Export (server ->
file): regenerate each fusion360-section record losslessly; ``include_all``
additionally synthesizes best-effort tools from canonical-only records.

Sync never prompts, blocks or guesses; anything untranslatable is counted
and logged, never invented.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import CLIENT_NAME, CLIENT_VERSION, mapping, presetsync, toolsfile

RESOURCE = "tool-instance-records"


def state_path():
    override = os.environ.get("LOOBRIC_FUSION_STATE")
    if override:
        return Path(override)
    return Path.home() / ".config" / "loobric" / "fusion-state.json"


def load_state():
    path = state_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    state.setdefault("records", {})
    return state


def save_state(state):
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _section(record):
    return (record.get("clients") or {}).get(CLIENT_NAME) or {}


def _record_id(record):
    return ((record.get("internal") or {}).get("id"))


def _changed_asserts(record, asserts):
    """Only the asserts whose canonical value actually differs — churn-free
    re-imports, and other actors' provenance survives an unchanged value."""
    out = []
    for path, value, unit in asserts:
        parts = path.split(".")
        current = mapping._leaf_value(record, *parts) if record else None
        if current == value:
            continue
        out.append((path, value, unit))
    return out


def import_file(client, doc, state, log=lambda msg: None, dry_run=False,
                set_name=None, workers=8):
    """Sync a Fusion library payload into the server. Returns a summary.

    Batch-shaped for real libraries (hundreds of tools): ONE listing
    request builds the record index, then the whole library goes through
    the server's batch sync door (loobric-server docs/BATCH_SYNC.md, one
    transaction per chunk — data, asserts and preset contributions ride
    each item). A pre-0.15 server (or a client library without the verb)
    falls back to the per-record doors over ``workers`` threads.

    ``set_name``: also gather every record this file maps to into the named
    ToolSet (found by name, created if missing; membership is additive)."""
    summary = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0,
               "errors": 0,
               "presets": {"promoted": 0, "skipped": 0, "pruned": 0,
                           "blocked": 0}}
    tools = []
    for tool in doc.get("data") or []:
        if not isinstance(tool, dict):
            continue
        if str(tool.get("type") or "").lower() in mapping.NON_TOOL_TYPES:
            summary["skipped"] += 1
            continue
        if not mapping.tool_guid(tool):
            log("skipping a tool with no guid: %s" % mapping.tool_name(tool))
            summary["skipped"] += 1
            continue
        tools.append(tool)

    by_item_id, by_id = {}, {}
    for record in client.list_tool_records():
        record_id = _record_id(record)
        if record_id:
            by_id[record_id] = record
        item_id = _section(record).get("client_item_id")
        if item_id:
            by_item_id[item_id] = record

    if dry_run:
        _import_per_record(client, tools, by_item_id, by_id, state, summary,
                           log, dry_run, workers)
    else:
        try:
            _import_batch(client, tools, by_item_id, by_id, state, summary,
                          log)
        except _NO_BATCH_DOOR:
            log("server has no batch sync door — per-record fallback")
            _import_per_record(client, tools, by_item_id, by_id, state,
                               summary, log, dry_run, workers)

    if set_name and not dry_run:
        ids = [state["records"][mapping.tool_guid(t)]
               for t in doc.get("data") or []
               if isinstance(t, dict)
               and state["records"].get(mapping.tool_guid(t))]
        if ids:
            summary["set"] = _gather_into_set(client, set_name, ids, log)
    return summary


def _no_batch_door():
    """The exceptions that mean 'use the per-record fallback': a pre-0.15
    server (404 on the door) or a client library without the verb."""
    try:
        from loobric.errors import NotFound
        return (NotFound, AttributeError)
    except ImportError:                     # pragma: no cover
        return (AttributeError,)


_NO_BATCH_DOOR = _no_batch_door()

_LOG_MARK = {"created": "+", "updated": "~", "unchanged": "="}


def _import_batch(client, tools, by_item_id, by_id, state, summary, log):
    """One pass through the batch sync door: data + asserts + preset
    contributions per item; stale own-origin presets pruned afterwards for
    updated records only."""
    items, metas = [], []
    for tool in tools:
        guid = mapping.tool_guid(tool)
        sections = mapping.tool_to_sections(tool)
        record = by_item_id.get(guid) or by_id.get(state["records"].get(guid))
        server_entries = mapping.record_presets(record) if record else []
        own, _external = presetsync.split_native(
            (tool.get("start-values") or {}).get("presets"), server_entries)
        contributions, floor_skipped = presetsync.translate(
            {"unit": tool.get("unit"), "start-values": {"presets": own}})
        item = {"client_item_id": guid, "data": sections.data,
                "asserts": [
                    dict({"path": path, "value": value},
                         **({"unit": unit} if unit else {}))
                    for path, value, unit in sections.asserts]}
        if record is not None:
            item["id"] = _record_id(record)
        if contributions:
            item["presets"] = contributions
        items.append(item)
        keep = {body["label"] for body in contributions} \
            | {label for label, _ in floor_skipped}
        metas.append((tool, guid, len(floor_skipped), keep,
                      "presets" in (tool.get("start-values") or {})))

    results = client.sync_tool_records(CLIENT_NAME, items,
                                       client_version=CLIENT_VERSION)
    for (tool, guid, floor_skips, keep, has_presets), res in zip(
            metas, results):
        name = mapping.tool_name(tool)
        result = res.get("result")
        if result not in _LOG_MARK:
            summary["errors"] += 1
            log("! %s: %s" % (name, res.get("error") or result))
            continue
        summary[result] += 1
        state["records"][guid] = res["id"]
        log("%s %s%s" % (_LOG_MARK[result], name,
                         " (unchanged)" if result == "unchanged" else ""))
        summary["presets"]["promoted"] += res.get("presets_contributed", 0)
        summary["presets"]["skipped"] += \
            res.get("presets_skipped", 0) + floor_skips
        summary["presets"]["blocked"] += res.get("asserts_blocked", 0)
        if result == "updated" and has_presets:
            pruned = presetsync.prune(client, res["id"], keep, log=log)
            summary["presets"]["pruned"] += pruned["pruned"]
            summary["presets"]["blocked"] += pruned["blocked"]


def _import_per_record(client, tools, by_item_id, by_id, state, summary,
                       log, dry_run, workers):
    """The pre-batch-door path: per-record doors over worker threads."""
    def work(tool):
        """One tool's sync; returns (kind, guid, record_id, presets, lines)."""
        guid = mapping.tool_guid(tool)
        name = mapping.tool_name(tool)
        record = by_item_id.get(guid) or by_id.get(state["records"].get(guid))
        if record is not None \
                and (_section(record).get("data") or {}).get("tool") == tool:
            return ("unchanged", guid, _record_id(record), None,
                    ["= %s (unchanged)" % name])
        kind = "created" if record is None else "updated"
        if dry_run:
            return (kind, guid, record and _record_id(record), None,
                    ["%s %s (dry run)" % ("+" if record is None else "~",
                                          name)])
        lines = []
        sections = mapping.tool_to_sections(tool)
        if record is None:
            created = client.create_tool_record(
                client=CLIENT_NAME, client_version=CLIENT_VERSION,
                client_item_id=guid, data=sections.data)
            record_id = _record_id(created)
            lines.append("+ %s" % name)
        else:
            record_id = _record_id(record)
            client.sync_client_section(
                RESOURCE, record_id, CLIENT_NAME, sections.data,
                client_version=CLIENT_VERSION, client_item_id=guid)
            lines.append("~ %s" % name)
        for path, value, unit in _changed_asserts(record, sections.asserts):
            try:
                client.assert_field(RESOURCE, record_id, path, value,
                                    actor=CLIENT_NAME, unit=unit)
            except Exception as exc:
                lines.append("  assert %s failed: %s" % (path, exc))
        presets = presetsync.promote(
            client, record_id, tool,
            server_entries=mapping.record_presets(record) if record else [],
            log=lines.append, fresh=record is None)
        return (kind, guid, record_id, presets, lines)

    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        results = list(pool.map(work, tools))
    finally:
        pool.shutdown()
    for kind, guid, record_id, presets, lines in results:
        summary[kind] += 1
        if record_id and not dry_run:
            state["records"][guid] = record_id
        for key, count in (presets or {}).items():
            summary["presets"][key] += count
        for line in lines:
            log(line)


def _gather_into_set(client, set_name, record_ids, log):
    """Find-or-create the named ToolSet and add the records (additive; the
    set may already exist and hold other tools)."""
    set_id = None
    for rec in client.list_tool_sets():
        name_leaf = (rec.get("canonical") or {}).get("name") or {}
        if name_leaf.get("value") == set_name:
            set_id = (rec.get("internal") or {}).get("id")
            break
    if set_id is None:
        rec = client.create_tool_set(name=set_name, actor=CLIENT_NAME)
        set_id = rec["internal"]["id"]
        log("+ tool set '%s'" % set_name)
    client.add_to_set(set_id, record_ids, actor=CLIENT_NAME)
    log("= tool set '%s': %d tools" % (set_name, len(record_ids)))
    return {"id": set_id, "name": set_name, "members_added": len(record_ids)}


def _catalog_presets(client, record, cache):
    catalog_id = mapping._leaf_value(record, "catalog_type_id")
    if not catalog_id:
        return []
    if catalog_id not in cache:
        try:
            cache[catalog_id] = client.list_presets(
                "tool-catalog-records", catalog_id)
        except Exception:
            cache[catalog_id] = []
    return cache[catalog_id]


def export_records(client, state, include_all=False, log=lambda msg: None):
    """Regenerate a Fusion library payload from the server. Returns
    ``(doc, summary)``."""
    summary = {"exported": 0, "synthesized": 0, "skipped": 0}
    tools = []
    cache = {}
    for record in client.list_tool_records():
        record_id = _record_id(record)
        catalog_entries = _catalog_presets(client, record, cache)
        if (_section(record).get("data") or {}).get("tool"):
            tool = mapping.record_to_tool(record, catalog_entries)
            if tool is None:
                summary["skipped"] += 1
                continue
            summary["exported"] += 1
        elif include_all:
            tool = mapping.synth_tool(record, catalog_entries)
            if tool is None:
                summary["skipped"] += 1
                log("- %s: no mappable shape/diameter — skipped"
                    % (mapping._leaf_value(record, "name") or record_id))
                continue
            summary["synthesized"] += 1
        else:
            summary["skipped"] += 1
            continue
        guid = mapping.tool_guid(tool)
        if guid and record_id:
            # Either regenerated or synthesized guids re-adopt on a later
            # import of this very file instead of duplicating.
            state["records"][guid] = record_id
        tools.append(tool)
        log("> %s" % mapping.tool_name(tool))
    doc = {"data": tools, "version": toolsfile.LIBRARY_VERSION}
    return doc, summary
