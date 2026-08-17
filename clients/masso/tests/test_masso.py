# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT
"""loobric-masso tests: .htg codec round-trip exactness, merge semantics,
entry mapping, USB discovery, and the push/write verbs against a stub server.
All offline."""
import json
import os
import struct
import sys
import zlib

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import loobric_masso as m  # noqa: E402


# -- synthetic .htg builder ---------------------------------------------------

def make_record(name="", z=0.0, z_wear=0.0, dia_wear=0.0, dia=0.0,
                slot=-1, direction=0, crc=None):
    rec = bytearray(m.RECORD_SIZE)
    nb = name.encode("ascii")
    rec[0:len(nb)] = nb
    struct.pack_into("<ffff", rec, 40, z, z_wear, dia_wear, dia)
    rec[56] = direction
    struct.pack_into("<b", rec, 57, slot)
    if crc is None:
        crc = zlib.crc32(bytes(rec[:60])) & 0xFFFFFFFF
    struct.pack_into("<I", rec, 60, crc)
    return bytes(rec)


def make_htg(records=None):
    """A full 105-record file. Record 0 mimics the controller's reserved
    dry-run entry with a CRC that does NOT match plain CRC32 (the controller's
    own variant) — round-tripping it byte-exact is the point."""
    recs = {0: make_record("Dry Run-Laser Pointer", crc=0xDEADBEEF)}
    recs.update(records or {})
    empty = make_record()
    return b"".join(recs.get(i, empty) for i in range(m.NUM_RECORDS))


# -- codec --------------------------------------------------------------------

def test_round_trip_byte_exact():
    data = make_htg({
        1: make_record("6mm endmill", z=-48.25, dia=6.0, slot=1),
        7: make_record("weird crc", z=1.0, dia=3.0, slot=7, crc=0x12345678),
    })
    tools = m.parse_htg(data)
    assert m.generate_htg(tools) == data          # untouched → verbatim


def test_parse_fields():
    data = make_htg({2: make_record("1/4in ball", z=-10.5, z_wear=0.1,
                                    dia_wear=0.02, dia=6.35, slot=2)})
    t = m.parse_htg(data)[2]
    assert t["name"] == "1/4in ball"
    assert t["z_offset"] == pytest.approx(-10.5)
    assert t["z_wear"] == pytest.approx(0.1)
    assert t["dia_wear"] == pytest.approx(0.02)
    assert t["diameter"] == pytest.approx(6.35)
    assert t["slot"] == 2
    assert t["crc_valid"]
    assert m.parse_htg(data)[0]["name"] == "Dry Run-Laser Pointer"
    assert not m.parse_htg(data)[0]["crc_valid"]  # controller CRC variant


def test_empty_record_shape():
    t = m.parse_htg(make_htg())[50]
    assert not m.record_in_use(t)
    assert t["slot"] == m.EMPTY_SLOT


def test_modified_record_gets_fresh_crc():
    tools = m.parse_htg(make_htg({1: make_record("old", dia=3.0, slot=1)}))
    tools[1]["name"] = "new name"
    tools[1]["raw"] = None
    out = m.parse_htg(m.generate_htg(tools))
    assert out[1]["name"] == "new name"
    assert out[1]["crc_valid"]
    assert out[0]["crc"] == 0xDEADBEEF            # record 0 untouched


def test_name_capped_to_ui_limit():
    tools = m.parse_htg(make_htg())
    tools[1].update({"name": "x" * 60, "raw": None, "slot": 1})
    assert len(m.parse_htg(m.generate_htg(tools))[1]["name"]) == m.NAME_MAX


def test_wrong_size_rejected():
    with pytest.raises(m.HtgError, match="6720"):
        m.parse_htg(b"\x00" * 100)


# -- entry mapping ------------------------------------------------------------

def test_tool_to_entry():
    t = m.parse_htg(make_htg({3: make_record("probe", z=-5.0, dia=2.0,
                                             slot=3, z_wear=0.05)}))[3]
    e = m.tool_to_entry(t, "masso01", units="mm")
    assert e["tool_number"] == 3
    assert e["offsets"] == {"z": pytest.approx(-5.0), "z_unit": "mm",
                            "diameter": pytest.approx(2.0),
                            "diameter_unit": "mm"}
    assert e["description"] == "probe"
    assert e["client_item_id"] == "masso01:T3"
    assert e["data"]["slot"] == 3
    assert e["data"]["z_wear"] == pytest.approx(0.05)


# -- merge (server -> table) --------------------------------------------------

def server_entry(number, description=None, z=None, diameter=None,
                 bound=False, slot=None):
    canonical = {"tool_number": {"value": number}, "offsets": {}}
    if description is not None:
        canonical["description"] = {"value": description}
    if z is not None:
        canonical["offsets"]["z"] = {"value": z}
    if diameter is not None:
        canonical["offsets"]["diameter"] = {"value": diameter}
    if bound:
        canonical["bound_instance_id"] = {"value": "inst-1"}
    entry = {"canonical": canonical}
    if slot is not None:
        entry["clients"] = {"masso": {"data": {"slot": slot}}}
    return entry


def test_merge_adds_new_tool():
    tools = m.parse_htg(make_htg())
    changed = m.merge_entries_into_table(
        tools, [server_entry(4, "new endmill", diameter=6.0, slot=4)])
    assert changed == 1
    assert tools[4]["name"] == "new endmill"
    assert tools[4]["diameter"] == 6.0
    assert tools[4]["slot"] == 4
    assert tools[4]["raw"] is None


def test_merge_preserves_probed_z_for_unbound():
    tools = m.parse_htg(make_htg({5: make_record("probed", z=-42.0, dia=6.0,
                                                 slot=5)}))
    m.merge_entries_into_table(
        tools, [server_entry(5, "probed", z=-1.0, diameter=6.0)])
    assert tools[5]["z_offset"] == pytest.approx(-42.0)   # unbound: kept


def test_merge_bound_z_applies():
    tools = m.parse_htg(make_htg({5: make_record("probed", z=-42.0, dia=6.0,
                                                 slot=5)}))
    changed = m.merge_entries_into_table(
        tools, [server_entry(5, "probed", z=-40.0, diameter=6.0, bound=True)])
    assert changed == 1
    assert tools[5]["z_offset"] == pytest.approx(-40.0)


def test_merge_replacement_warns_reprobe():
    tools = m.parse_htg(make_htg({6: make_record("old tool", z=-30.0, dia=6.0,
                                                 slot=6)}))
    warnings = []
    m.merge_entries_into_table(
        tools, [server_entry(6, "different tool", diameter=3.0)],
        log=warnings.append)
    assert tools[6]["name"] == "different tool"
    assert tools[6]["z_offset"] == pytest.approx(-30.0)   # kept, but flagged
    assert any("RE-PROBE" in w for w in warnings)


def test_merge_ignores_out_of_range_and_unmentioned():
    data = make_htg({101: make_record("spindle head", slot=-1, dia=1.0)})
    tools = m.parse_htg(data)
    changed = m.merge_entries_into_table(
        tools, [server_entry(0, "reserved"), server_entry(104, "head")])
    assert changed == 0
    assert m.generate_htg(tools) == data


def test_merge_unchanged_is_noop():
    data = make_htg({2: make_record("same", z=-1.0, dia=6.0, slot=2)})
    tools = m.parse_htg(data)
    changed = m.merge_entries_into_table(
        tools, [server_entry(2, "same", diameter=6.0, slot=2)])
    assert changed == 0
    assert m.generate_htg(tools) == data


# -- USB discovery + backup ---------------------------------------------------

def make_usb(tmp_path, filenames=("MASSO_Mill_Tools.htg",)):
    settings = tmp_path / "MASSO" / "Machine Settings"
    settings.mkdir(parents=True)
    for fname in filenames:
        (settings / fname).write_bytes(make_htg())
    return tmp_path


def test_find_htg(tmp_path):
    usb = make_usb(tmp_path)
    assert m.find_htg(str(usb)).endswith("MASSO_Mill_Tools.htg")


def test_find_htg_no_folder(tmp_path):
    with pytest.raises(m.HtgError, match="Save to file"):
        m.find_htg(str(tmp_path))


def test_find_htg_ambiguous(tmp_path):
    usb = make_usb(tmp_path, ("MASSO_Mill_Tools.htg", "MASSO_Tools_old.htg"))
    with pytest.raises(m.HtgError, match="multiple"):
        m.find_htg(str(usb))


def test_backup_settings(tmp_path):
    usb = make_usb(tmp_path)
    dest = m.backup_settings(str(usb))
    assert os.path.isfile(dest)
    assert dest.startswith(os.path.join(str(usb), "MASSO", "loobric-backups"))


# -- verbs against a stub server ---------------------------------------------

class StubServer:
    def __init__(self, entries=()):
        self.entries = list(entries)
        self.pushed = None

    def __call__(self, method, url, api_key, body=None, timeout=None):
        if url.endswith("/api/v1/machine-records") and method == "POST":
            return {"internal": {"id": "mach-1"}}
        if "/machine-records/mach-1/assert" in url:
            return {}
        if "/machine-records/mach-1" in url and method == "GET":
            return {"internal": {"id": "mach-1"}}
        if "/tool-table-entry-records/sync" in url:
            self.pushed = body
            return {"items": [{}] * len(body["entries"])}
        if "/tool-table-entry-records?machine_id=mach-1" in url:
            return {"items": self.entries}
        raise AssertionError("unexpected call: %s %s" % (method, url))


@pytest.fixture
def config(tmp_path, monkeypatch):
    usb = make_usb(tmp_path, ())
    htg = tmp_path / "MASSO" / "Machine Settings" / "MASSO_Mill_Tools.htg"
    htg.write_bytes(make_htg({1: make_record("6mm endmill", z=-48.25,
                                             dia=6.0, slot=1)}))
    monkeypatch.setenv("HOME", str(tmp_path))    # isolate the state file
    return {"LOOBRIC_API_URL": "http://test", "MACHINE_NAME": "masso01",
            "MASSO_USB": str(tmp_path)}


def test_push_verb(config, monkeypatch):
    stub = StubServer()
    monkeypatch.setattr(m, "http_json", stub)
    assert m.push_tool_table(config) == 0
    body = stub.pushed
    assert body["mode"] == "snapshot"
    assert body["client"] == "masso"
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["tool_number"] == 1
    assert entry["offsets"]["z"] == pytest.approx(-48.25)


def test_write_verb(config, monkeypatch, tmp_path):
    stub = StubServer(entries=[
        server_entry(2, "new drill", diameter=3.0, slot=2)])
    monkeypatch.setattr(m, "http_json", stub)
    assert m.write_tool_table(config) == 0
    htg = tmp_path / "MASSO" / "Machine Settings" / "MASSO_Mill_Tools.htg"
    tools = m.parse_htg(htg.read_bytes())
    assert tools[2]["name"] == "new drill"
    assert tools[1]["name"] == "6mm endmill"     # untouched
    backups = list((tmp_path / "MASSO" / "loobric-backups").iterdir())
    assert len(backups) == 1                      # backup before write


def test_write_verb_noop_writes_nothing(config, monkeypatch, tmp_path):
    htg = tmp_path / "MASSO" / "Machine Settings" / "MASSO_Mill_Tools.htg"
    before = htg.read_bytes()
    stub = StubServer(entries=[server_entry(1, "6mm endmill", diameter=6.0,
                                            slot=1)])
    monkeypatch.setattr(m, "http_json", stub)
    assert m.write_tool_table(config) == 0
    assert htg.read_bytes() == before
    assert not (tmp_path / "MASSO" / "loobric-backups").exists()


def test_push_unreachable_is_benign(config, monkeypatch):
    def boom(*a, **kw):
        raise m.ServerUnreachable("nope")
    monkeypatch.setattr(m, "http_json", boom)
    assert m.push_tool_table(config) == 0         # cron-safe

def test_missing_config_is_usage_error():
    assert m.push_tool_table({}) == 2
