# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT
import copy
import json
import threading

import pytest

from loobric_fusion import mapping, sync


class FakeClient:
    """The verbs sync.py touches, over an in-memory record store."""

    def __init__(self):
        self.records = {}
        self.catalog_presets = {}
        self.sets = {}
        self.next_id = 0
        self.asserts = []
        self.contributions = []
        self._lock = threading.Lock()

    # -- records ---------------------------------------------------------
    def list_tool_records(self):
        return [copy.deepcopy(r) for r in self.records.values()]

    def get_tool_record(self, record_id):
        if record_id not in self.records:
            raise KeyError(record_id)
        return copy.deepcopy(self.records[record_id])

    def create_tool_record(self, **section):
        with self._lock:
            self.next_id += 1
            record_id = "rec-%d" % self.next_id
        record = {"internal": {"id": record_id, "version": 1},
                  "canonical": {},
                  "clients": {section["client"]: {
                      "client_item_id": section.get("client_item_id"),
                      "data": copy.deepcopy(section.get("data") or {})}}}
        self.records[record_id] = record
        return copy.deepcopy(record)

    def sync_client_section(self, resource, record_id, client, data,
                            client_version="", client_item_id=None):
        section = self.records[record_id]["clients"].setdefault(client, {})
        section["data"] = copy.deepcopy(data)
        section["client_item_id"] = client_item_id

    def assert_field(self, resource, record_id, path, value,
                     actor="human@cli", unit=None):
        self.asserts.append((record_id, path, value, unit))
        node = self.records[record_id]["canonical"]
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        leaf = {"value": value, "source": "asserted:%s" % actor}
        if unit is not None:
            leaf["unit"] = unit
        node[parts[-1]] = leaf

    # -- presets ---------------------------------------------------------
    def contribute_preset(self, resource, record_id, origin, label,
                          material, actor="human@cli", **rest):
        entry = {"id": "p-%s-%s" % (record_id, label), "origin": origin,
                 "label": label, "material": material}
        entry.update({k: v for k, v in rest.items() if v is not None})
        self.contributions.append((record_id, entry))
        canonical = self.records[record_id]["canonical"]
        union = canonical.setdefault(
            "presets", {"value": [], "source": "derived:preset-union"})
        union["value"] = [e for e in union["value"]
                          if (e["origin"], e["label"]) != (origin, label)]
        union["value"].append(copy.deepcopy(entry))

    def list_presets(self, resource, record_id):
        if resource == "tool-catalog-records":
            return self.catalog_presets.get(record_id, [])
        canonical = self.records[record_id]["canonical"]
        return copy.deepcopy((canonical.get("presets") or {}).get("value")
                             or [])

    def delete_preset(self, resource, record_id, entry_id):
        canonical = self.records[record_id]["canonical"]
        union = canonical.get("presets") or {"value": []}
        union["value"] = [e for e in union["value"] if e["id"] != entry_id]

    # -- tool sets -------------------------------------------------------
    def list_tool_sets(self):
        return list(self.sets.values())

    def create_tool_set(self, name=None, actor="human@cli"):
        rec = {"internal": {"id": "set-%d" % (len(self.sets) + 1)},
               "canonical": {"name": {"value": name}, "members": []}}
        self.sets[rec["internal"]["id"]] = rec
        return rec

    def get_tool_set(self, set_id):
        return self.sets[set_id]

    def add_to_set(self, set_id, tool_record_ids, actor="human@cli",
                   numbers=None):
        members = self.sets[set_id]["canonical"]["members"]
        have = {m["tool_record_id"] for m in members}
        for tid in tool_record_ids:
            if tid not in have:
                members.append({"tool_record_id": tid})
                have.add(tid)


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOBRIC_FUSION_STATE",
                       str(tmp_path / "fusion-state.json"))
    return sync.load_state()


def test_import_creates_records_and_promotes_presets(sample_doc, state):
    client = FakeClient()
    summary = sync.import_file(client, sample_doc, state)
    assert summary["created"] == 6
    assert summary["updated"] == 0 and summary["skipped"] == 0
    # Two sample tools carry promotable presets (mysterybit + Tormach);
    # the probe and the all-zero defaults are honest skips.
    assert summary["presets"]["promoted"] == 2
    assert summary["presets"]["skipped"] == 4
    # guid -> record id learned for every tool
    assert len(state["records"]) == 6
    # canonical asserts landed
    record = client.get_tool_record(state["records"][
        "f93aeaa8-a649-4abb-a1ce-d23f998e4dee"])
    assert record["canonical"]["name"]["value"] == "mysterybit"
    assert record["canonical"]["geometry"]["diameter"]["value"] == 5


def test_import_is_idempotent(sample_doc, state):
    client = FakeClient()
    sync.import_file(client, sample_doc, state)
    asserts_before = len(client.asserts)
    summary = sync.import_file(client, sample_doc, state)
    assert summary["unchanged"] == 6
    assert summary["created"] == summary["updated"] == 0
    assert len(client.asserts) == asserts_before   # zero churn


def test_import_updates_changed_tool(sample_doc, state):
    client = FakeClient()
    sync.import_file(client, sample_doc, state)
    doc = copy.deepcopy(sample_doc)
    tool = next(t for t in doc["data"]
                if t["description"] == "mysterybit")
    tool["geometry"]["DC"] = 6
    summary = sync.import_file(client, doc, state)
    assert summary["updated"] == 1 and summary["unchanged"] == 5
    record = client.get_tool_record(state["records"][
        "f93aeaa8-a649-4abb-a1ce-d23f998e4dee"])
    assert record["canonical"]["geometry"]["diameter"]["value"] == 6
    assert record["clients"]["fusion360"]["data"]["tool"]["geometry"]["DC"] \
        == 6


def test_import_readopts_by_client_item_id(sample_doc, state):
    client = FakeClient()
    sync.import_file(client, sample_doc, state)
    count = len(client.records)
    state["records"].clear()          # lost state file
    summary = sync.import_file(client, sample_doc, state)
    assert summary["created"] == 0    # re-adopted, never duplicated
    assert len(client.records) == count
    assert len(state["records"]) == 6


def test_import_dry_run_writes_nothing(sample_doc, state):
    client = FakeClient()
    summary = sync.import_file(client, sample_doc, state, dry_run=True)
    assert summary["created"] == 6
    assert client.records == {} and client.asserts == []


def test_import_skips_holders(state):
    client = FakeClient()
    doc = {"data": [{"type": "holder", "guid": "h-1",
                     "description": "a holder"}]}
    summary = sync.import_file(client, doc, state)
    assert summary["skipped"] == 1 and client.records == {}


def test_export_round_trip(sample_doc, state):
    client = FakeClient()
    sync.import_file(client, sample_doc, state)
    doc, summary = sync.export_records(client, state)
    assert summary["exported"] == 6 and summary["synthesized"] == 0
    by_desc = {t.get("description"): t for t in doc["data"]}
    tool = by_desc["mysterybit"]
    # Its own promoted preset stays native (no duplicate external copy).
    names = [p["name"] for p in tool["start-values"]["presets"]]
    assert names == ["Default preset"]


def test_export_materializes_other_origins(sample_doc, state):
    client = FakeClient()
    sync.import_file(client, sample_doc, state)
    record_id = state["records"]["f93aeaa8-a649-4abb-a1ce-d23f998e4dee"]
    client.contribute_preset(
        "tool-instance-records", record_id, origin="sandvik", label="Steel",
        material={"name": "Steel"}, vc={"value": 120, "unit": "m/min"},
        fz={"value": 0.04, "unit": "mm"})
    doc, _ = sync.export_records(client, state)
    tool = next(t for t in doc["data"] if t["description"] == "mysterybit")
    names = [p["name"] for p in tool["start-values"]["presets"]]
    assert names == ["Default preset", "sandvik: Steel"]
    # ...and a re-import of that file does not fork sandvik's entry.
    summary = sync.import_file(client, doc, state)
    assert not any(e["origin"] == "fusion360" and "sandvik" in e["label"]
                   for _rid, e in client.contributions)


def test_export_includes_catalog_scope_presets(sample_doc, state):
    client = FakeClient()
    sync.import_file(client, sample_doc, state)
    record_id = state["records"]["f93aeaa8-a649-4abb-a1ce-d23f998e4dee"]
    client.records[record_id]["canonical"]["catalog_type_id"] = {
        "value": "cat-1"}
    client.catalog_presets["cat-1"] = [
        {"origin": "manufacturer", "label": "Aluminum", "scope": "catalog",
         "material": {"name": "Aluminum"},
         "vc": {"value": 200, "unit": "m/min"}}]
    doc, _ = sync.export_records(client, state)
    tool = next(t for t in doc["data"] if t["description"] == "mysterybit")
    names = [p["name"] for p in tool["start-values"]["presets"]]
    assert "manufacturer: Aluminum" in names


def test_export_all_synthesizes_foreign_records(state):
    client = FakeClient()
    client.records["rec-x"] = {
        "internal": {"id": "rec-x", "version": 1},
        "canonical": {"name": {"value": "FreeCAD endmill"},
                      "geometry": {"shape": {"value": "endmill"},
                                   "diameter": {"value": 8, "unit": "mm"}}},
        "clients": {"freecad": {"data": {"fctb": {}}}},
    }
    doc, summary = sync.export_records(client, state)
    assert summary["skipped"] == 1 and doc["data"] == []
    doc, summary = sync.export_records(client, state, include_all=True)
    assert summary["synthesized"] == 1
    tool = doc["data"][0]
    assert tool["type"] == "flat end mill"
    # the synth guid is remembered, so importing the exported file re-adopts
    assert state["records"][tool["guid"]] == "rec-x"
    summary = sync.import_file(client, doc, state)
    assert summary["created"] == 0


def test_import_gathers_into_named_set(sample_doc, state):
    client = FakeClient()
    summary = sync.import_file(client, sample_doc, state, set_name="Amana")
    assert summary["set"]["name"] == "Amana"
    assert summary["set"]["members_added"] == 6
    [rec] = client.sets.values()
    assert rec["canonical"]["name"]["value"] == "Amana"
    assert len(rec["canonical"]["members"]) == 6
    # Re-import into the same named set: additive, no duplicates, no new set.
    summary = sync.import_file(client, sample_doc, state, set_name="Amana")
    assert len(client.sets) == 1
    assert len(rec["canonical"]["members"]) == 6


def test_import_dry_run_creates_no_set(sample_doc, state):
    client = FakeClient()
    summary = sync.import_file(client, sample_doc, state, dry_run=True,
                               set_name="Amana")
    assert client.sets == {} and "set" not in summary


class FakeBatchClient(FakeClient):
    """A 0.15.0-shaped server: the batch door exists. Results are scripted
    per call; the fake records what the client sent."""

    def __init__(self, script=None):
        super().__init__()
        self.batch_calls = []
        self.script = script or []

    def sync_tool_records(self, client, items, client_version="", **kw):
        self.batch_calls.append({"client": client, "items": items,
                                 "client_version": client_version})
        if self.script:
            return self.script.pop(0)
        out = []
        for n, item in enumerate(items):
            out.append({"client_item_id": item.get("client_item_id"),
                        "id": "rec-%d" % (n + 1), "result": "created",
                        "asserts_applied": len(item.get("asserts") or []),
                        "presets_contributed": len(item.get("presets") or []),
                        "presets_skipped": 0})
        return out


def test_import_prefers_batch_door(sample_doc, state):
    client = FakeBatchClient()
    summary = sync.import_file(client, sample_doc, state)
    assert summary["created"] == 6 and summary["errors"] == 0
    [call] = client.batch_calls
    assert call["client"] == "fusion360"
    assert len(call["items"]) == 6
    item = next(i for i in call["items"]
                if i["client_item_id"] == "f93aeaa8-a649-4abb-a1ce-d23f998e4dee")
    # data + asserts + presets ride the item; units ride the asserts
    assert item["data"]["tool"]["description"] == "mysterybit"
    diameter = next(a for a in item["asserts"]
                    if a["path"] == "geometry.diameter")
    assert diameter == {"path": "geometry.diameter", "value": 5,
                        "unit": "mm"}
    [preset] = item["presets"]
    assert preset["origin"] == "fusion360"
    assert preset["material"] == {"name": "all"}
    # the batch results fed the state map
    assert state["records"]["f93aeaa8-a649-4abb-a1ce-d23f998e4dee"].startswith(
        "rec-")
    # floor-skipped presets (probe, all-zero defaults) counted locally
    assert summary["presets"]["skipped"] == 4
    assert summary["presets"]["promoted"] == 2


def test_batch_error_items_are_counted_and_logged(sample_doc, state):
    doc = {"data": sample_doc["data"][:2], "version": 36}
    script = [[{"client_item_id": "x", "id": None, "result": "error",
                "error": "ambiguous_item_id"},
               {"client_item_id": "y", "id": "rec-2", "result": "created",
                "asserts_applied": 3}]]
    client = FakeBatchClient(script=script)
    lines = []
    summary = sync.import_file(client, doc, state, log=lines.append)
    assert summary["errors"] == 1 and summary["created"] == 1
    assert any("ambiguous_item_id" in line for line in lines)


def test_batch_prunes_stale_presets_on_updated(sample_doc, state):
    doc = {"data": [next(t for t in sample_doc["data"]
                         if t["description"] == "mysterybit")],
           "version": 36}
    script = [[{"client_item_id": "f93aeaa8-a649-4abb-a1ce-d23f998e4dee",
                "id": "rec-1", "result": "updated", "asserts_applied": 0,
                "presets_contributed": 1, "presets_skipped": 0}]]
    client = FakeBatchClient(script=script)
    client.records["rec-1"] = {
        "internal": {"id": "rec-1"},
        "canonical": {"presets": {"value": [
            {"id": "stale", "origin": "fusion360", "label": "Old preset"},
        ]}}, "clients": {}}
    summary = sync.import_file(client, doc, state)
    assert summary["presets"]["pruned"] == 1
    assert "stale" in client.records["rec-1"]["canonical"]["presets"][
        "value"] == [] or True  # deletion path exercised via FakeClient
    assert client.records["rec-1"]["canonical"]["presets"]["value"] == []


def test_fallback_when_no_batch_door(sample_doc, state):
    client = FakeClient()          # no sync_tool_records verb
    lines = []
    summary = sync.import_file(client, sample_doc, state, log=lines.append)
    assert summary["created"] == 6
    assert any("per-record fallback" in line for line in lines)


def test_state_round_trip(state, tmp_path):
    state["records"]["g-1"] = "rec-1"
    sync.save_state(state)
    assert sync.load_state()["records"] == {"g-1": "rec-1"}
    raw = json.loads(sync.state_path().read_text())
    assert raw["records"]["g-1"] == "rec-1"
