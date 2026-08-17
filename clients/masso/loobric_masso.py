#!/usr/bin/env python3
# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT

"""
Loobric MASSO client - sync a MASSO G3 controller's tool table with a Loobric
server, over the USB stick the controller itself reads.

SINGLE FILE, STANDARD LIBRARY ONLY, same contract as loobric-linuxcnc: this
script must run anywhere Python 3.6+ exists and must NEVER block or break a
machine workflow:

- Server unreachable / server error  -> log it, exit 0 (cron-safe)
- Bad usage or missing configuration -> log it, exit 2

MASSO has no network door for tool data: the controller saves its settings
(including the `.htg` tool table) to a USB stick (F1 Setup > Save & Load
Calibration Settings > Save to file), and loads them back the same way, then
reboots. This client reads and writes that file on the mounted stick:

    loobric-masso init [--force]         # write a starter config, then edit it
    loobric-masso doctor                 # check config, server, and USB stick
    loobric-masso push [machine-name]    # .htg -> server (harvest probed offsets)
    loobric-masso write [machine-name]   # server -> .htg (update the tool table)
    loobric-masso sync [machine-name]    # push, then write

Configuration: ~/.config/loobric/masso.conf (shell-style KEY="value"), created
by `init`. Overridable via environment variables and CLI:

    LOOBRIC_API_URL="http://nas.local:8000"
    LOOBRIC_API_KEY="your-api-key"     # not needed against a solo-mode server
    MACHINE_NAME="masso01"            # or pass as CLI argument
    MASSO_USB="/media/usb"            # mount point of the controller's stick
    UNITS="mm"                        # the controller's configured unit
    LOG_DIR="/tmp/loobric-sync"        # optional log file location

The `.htg` binary format was reverse-engineered on the MASSO community forum
(thread 4563) and validated by three independent decoders that agree
byte-for-byte: 105 records x 64 bytes; per record name @0, Z offset f32 LE @40,
Z wear @44, diameter wear @48, diameter @52, tool direction @56, slot (signed
byte, -1 = manual/unassigned) @57, CRC32 of bytes 0-59 @60. Record 0 is the
controller's reserved "Dry Run-Laser Pointer" entry; T101-T104 are
multi-spindle heads. Both are preserved verbatim, as is every record this
client does not modify (the controller sometimes writes a CRC variant of its
own - untouched records must round-trip byte-exact).

Entries are pushed UNBOUND; binding tool-table rows to ToolInstanceRecords is
the server's job (review inbox) or the user's (explicit assert). This client
never guesses identity (v2 decision G2). It only ever writes its own
`clients.masso` section plus the few canonical fields a machine may OBSERVE
(tool_number, offsets); the server stamps provenance `observed:masso@<machine>`
itself.
"""

import argparse
import glob
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/loobric/masso.conf")
HTTP_TIMEOUT = 10  # seconds
CLIENT_NAME = "masso"
CLIENT_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# .htg codec (see module docstring for provenance of the layout)
# ---------------------------------------------------------------------------

RECORD_SIZE = 64
NUM_RECORDS = 105
FILE_SIZE = RECORD_SIZE * NUM_RECORDS
MAX_TOOL = 100            # T101-T104 are multi-spindle heads; T0 is reserved
NAME_MAX = 29             # the controller UI caps tool names at 29 chars
EMPTY_SLOT = -1


class HtgError(Exception):
    """Error parsing or generating a MASSO .htg tool table."""


class ServerUnreachable(Exception):
    """The Loobric server could not be reached (benign for cron)."""


class ServerError(Exception):
    """The server returned an HTTP error (reachable, but the request failed)."""

    def __init__(self, code, message):
        super(ServerError, self).__init__(message)
        self.code = code


def parse_htg(data):
    """Parse .htg bytes into a list of NUM_RECORDS tool dicts.

    Every record keeps its `raw` 64 bytes; writing emits `raw` verbatim unless
    the record was modified (`raw` cleared) - that is what makes the round trip
    byte-exact even for the controller's own CRC variants and for record 0.
    """
    if len(data) != FILE_SIZE:
        raise HtgError("not a MASSO .htg tool table: expected %d bytes, got %d"
                       % (FILE_SIZE, len(data)))
    tools = []
    for i in range(NUM_RECORDS):
        raw = data[i * RECORD_SIZE:(i + 1) * RECORD_SIZE]
        name = raw[0:40].split(b"\x00")[0].decode("ascii", errors="replace")
        z_offset, z_wear, dia_wear, diameter = struct.unpack_from("<ffff", raw, 40)
        direction = raw[56]
        slot = struct.unpack_from("<b", raw, 57)[0]
        crc = struct.unpack_from("<I", raw, 60)[0]
        tools.append({
            "index": i, "name": name,
            "z_offset": z_offset, "z_wear": z_wear, "dia_wear": dia_wear,
            "diameter": diameter, "direction": direction, "slot": slot,
            "crc": crc, "crc_valid": crc == (zlib.crc32(raw[:60]) & 0xFFFFFFFF),
            "raw": raw,
        })
    return tools


def encode_record(tool):
    """Encode one modified tool dict to 64 bytes (fresh CRC over bytes 0-59)."""
    rec = bytearray(RECORD_SIZE)
    name = (tool.get("name") or "").encode("ascii", errors="replace")[:NAME_MAX]
    rec[0:len(name)] = name
    struct.pack_into("<ffff", rec, 40,
                     float(tool.get("z_offset") or 0.0),
                     float(tool.get("z_wear") or 0.0),
                     float(tool.get("dia_wear") or 0.0),
                     float(tool.get("diameter") or 0.0))
    rec[56] = int(tool.get("direction") or 0) & 0xFF
    struct.pack_into("<b", rec, 57, int(tool.get("slot", EMPTY_SLOT)))
    struct.pack_into("<I", rec, 60, zlib.crc32(bytes(rec[:60])) & 0xFFFFFFFF)
    return bytes(rec)


def generate_htg(tools):
    """Serialize the record list back to .htg bytes. Records that still carry
    their `raw` bytes are emitted verbatim; only modified records (raw=None)
    are re-encoded with a fresh CRC."""
    if len(tools) != NUM_RECORDS:
        raise HtgError("tool list must have exactly %d records" % NUM_RECORDS)
    parts = []
    for tool in tools:
        raw = tool.get("raw")
        parts.append(raw if raw is not None else encode_record(tool))
    data = b"".join(parts)
    assert len(data) == FILE_SIZE
    return data


def record_in_use(tool):
    """True when a record holds a real tool (a name, geometry, or a slot)."""
    return bool(tool["name"]) or tool["slot"] != EMPTY_SLOT \
        or tool["diameter"] != 0.0


# ---------------------------------------------------------------------------
# USB stick discovery + backup
# ---------------------------------------------------------------------------

SETTINGS_DIR = os.path.join("MASSO", "Machine Settings")
BACKUP_DIR = os.path.join("MASSO", "loobric-backups")


def find_htg(usb_root):
    """Locate the tool-table .htg under <usb>/MASSO/Machine Settings/.

    Firmware versions name the file differently (MASSO_Mill_Tools.htg,
    MASSO_Tools.htg, ...), so we scan rather than assume. Exactly one match is
    required - the file is created by the controller's own "Save to file", and
    we refuse to guess between candidates or fabricate one from nothing.
    """
    settings = os.path.join(usb_root, SETTINGS_DIR)
    if not os.path.isdir(settings):
        raise HtgError(
            "%s not found - save the controller settings to this USB stick "
            "first (F1 Setup > Save & Load Calibration Settings > Save to "
            "file)" % settings)
    candidates = [p for p in sorted(glob.glob(os.path.join(settings, "*.htg")))
                  if "tool" in os.path.basename(p).lower()
                  and os.path.getsize(p) == FILE_SIZE]
    if not candidates:
        candidates = [p for p in sorted(glob.glob(os.path.join(settings, "*.htg")))
                      if os.path.getsize(p) == FILE_SIZE]
    if not candidates:
        raise HtgError("no %d-byte .htg tool table found in %s"
                       % (FILE_SIZE, settings))
    if len(candidates) > 1:
        raise HtgError("multiple .htg tool tables in %s: %s - set the one to "
                       "use explicitly in MASSO_HTG" % (
                           settings,
                           ", ".join(os.path.basename(c) for c in candidates)))
    return candidates[0]


def backup_settings(usb_root):
    """Zip MASSO/Machine Settings into MASSO/loobric-backups/<ts>.zip before
    any write. Returns the zip path."""
    settings = os.path.join(usb_root, SETTINGS_DIR)
    dest_dir = os.path.join(usb_root, BACKUP_DIR)
    os.makedirs(dest_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    dest = os.path.join(dest_dir, "machine-settings-%s.zip" % stamp)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(settings):
            for fname in files:
                full = os.path.join(root, fname)
                zf.write(full, os.path.relpath(full, os.path.dirname(settings)))
    return dest


# ---------------------------------------------------------------------------
# Mapping to the Loobric API (v2 sectioned schema, /sync entries)
# ---------------------------------------------------------------------------

def tool_to_entry(tool, machine_name, units="mm"):
    """Map one in-use .htg record to an `entries` item for the /sync call.

    Offsets carry what the controller legitimately OBSERVES: the probed Z
    offset and the tool diameter (the server stamps observed:masso@<machine>).
    Wear registers and the ATC slot are MASSO-specific and ride in the
    client-owned `data` payload, losslessly.
    """
    offsets = {}
    for key, value in (("z", tool["z_offset"]), ("diameter", tool["diameter"])):
        if value:
            offsets[key] = value
            offsets[key + "_unit"] = units
    entry = {
        "tool_number": tool["index"],
        "offsets": offsets,
        "data": {
            "slot": tool["slot"],
            "z_wear": tool["z_wear"],
            "dia_wear": tool["dia_wear"],
            "direction": tool["direction"],
        },
        "client_item_id": "%s:T%d" % (machine_name, tool["index"]),
    }
    if tool["name"]:
        entry["description"] = tool["name"]
    return entry


def _entry_tool_number(entry):
    return entry["canonical"]["tool_number"]["value"]


def _entry_bound(entry):
    field = (entry.get("canonical") or {}).get("bound_instance_id") or {}
    return field.get("value") is not None


def _entry_description(entry):
    field = (entry.get("canonical") or {}).get("description") or {}
    return field.get("value")


def _entry_offset(entry, key):
    field = ((entry.get("canonical") or {}).get("offsets") or {}).get(key) or {}
    return field.get("value")


def _entry_client_data(entry):
    return ((entry.get("clients") or {}).get(CLIENT_NAME) or {}).get("data") or {}


def merge_entries_into_table(tools, entries, log=lambda msg: None):
    """Merge server entries into the parsed .htg table, in place.

    Additive and conservative - the controller is the operator's domain:
    - Only T1..T100 entries apply; records the server does not mention are
      left byte-verbatim (including T0 and the multi-spindle heads).
    - Names and diameters follow the server; the probed Z offset is
      PRESERVED unless the entry is bound and carries a server-side Z.
    - A name change at an occupied record keeps the old Z and warns: the
      physical tool changed, RE-PROBE before trusting the offset.
    Returns the number of records modified.
    """
    changed = 0
    for entry in entries:
        number = _entry_tool_number(entry)
        if not isinstance(number, int) or not 1 <= number <= MAX_TOOL:
            continue
        tool = tools[number]
        new_name = (_entry_description(entry) or tool["name"])[:NAME_MAX]
        new_dia = _entry_offset(entry, "diameter")
        new_z = _entry_offset(entry, "z") if _entry_bound(entry) else None
        client_slot = _entry_client_data(entry).get("slot")

        replaced = (record_in_use(tool) and tool["name"]
                    and new_name and tool["name"].lower() != new_name.lower())
        updates = {}
        if new_name and new_name != tool["name"]:
            updates["name"] = new_name
        if new_dia is not None and round(new_dia, 4) != round(tool["diameter"], 4):
            updates["diameter"] = new_dia
        if new_z is not None and round(new_z, 4) != round(tool["z_offset"], 4):
            updates["z_offset"] = new_z
        if client_slot is not None and client_slot != tool["slot"]:
            updates["slot"] = client_slot
        if not updates:
            continue

        if replaced and "z_offset" not in updates:
            log("T%d: '%s' -> '%s' - tool is physically different, RE-PROBE Z "
                "(old offset kept)" % (number, tool["name"], new_name))
        tool.update(updates)
        tool["raw"] = None            # re-encode with a fresh CRC
        changed += 1
    return changed


# ---------------------------------------------------------------------------
# Logging (mirrors loobric-linuxcnc: stderr + optional LOG_DIR file)
# ---------------------------------------------------------------------------

_LOG_FILE = None


def log(message):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message)
    print(line, file=sys.stderr)
    if _LOG_FILE:
        try:
            with open(_LOG_FILE, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass


def _init_log_file(config):
    global _LOG_FILE
    log_dir = config.get("LOG_DIR")
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            _LOG_FILE = os.path.join(log_dir, "loobric-masso.log")
        except OSError:
            _LOG_FILE = None


# ---------------------------------------------------------------------------
# Config + state (same shell-style KEY="value" format as the linuxcnc client)
# ---------------------------------------------------------------------------

_CONF_LINE = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*"?([^"\n]*)"?\s*$')

CONFIG_KEYS = ("LOOBRIC_API_URL", "LOOBRIC_API_KEY", "MACHINE_NAME",
               "MASSO_USB", "MASSO_HTG", "UNITS", "LOG_DIR")


def load_config(path=None):
    config = {}
    path = path or DEFAULT_CONFIG_PATH
    try:
        with open(path) as f:
            for line in f:
                if line.lstrip().startswith("#"):
                    continue
                m = _CONF_LINE.match(line)
                if m:
                    config[m.group(1)] = m.group(2).strip()
    except OSError:
        pass
    for key in CONFIG_KEYS:
        if os.environ.get(key):
            config[key] = os.environ[key]
    return config


def _state_path(config, machine_name):
    base = os.path.expanduser("~/.config/loobric")
    return os.path.join(base, "masso-state-%s.json"
                        % re.sub(r"[^\w.-]", "_", machine_name))


def _load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(path, state):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError as e:
        log("WARNING: cannot save state %s: %s" % (path, e))


# ---------------------------------------------------------------------------
# HTTP (stdlib only; same error split as the linuxcnc client)
# ---------------------------------------------------------------------------

def http_json(method, url, api_key, body=None, timeout=HTTP_TIMEOUT):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent",
                       "loobric-masso/%s" % CLIENT_VERSION)
    if api_key:
        request.add_header("Authorization", "Bearer %s" % api_key)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        raise ServerError(e.code, "HTTP %d from %s: %s" % (e.code, url, detail))
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise ServerUnreachable("cannot reach %s: %s" % (url, e))


def _ensure_machine(base_url, api_key, name, state, state_file):
    """Return this machine's server id, creating+naming a MachineRecord on
    first contact and persisting its id in the state file (v2 has no name
    lookup: the client owns the server->client back-reference)."""
    machine_id = state.get("machine_id")
    if machine_id:
        try:
            http_json("GET", "%s/api/v1/machine-records/%s"
                      % (base_url, machine_id), api_key)
            return machine_id
        except ServerError as e:
            if e.code != 404:
                raise
            log("Stored machine %s is gone from the server; re-registering."
                % machine_id)
            machine_id = None
    created = http_json("POST", base_url + "/api/v1/machine-records", api_key,
                        body={})
    machine_id = created["internal"]["id"]
    http_json("POST", "%s/api/v1/machine-records/%s/assert"
              % (base_url, machine_id), api_key,
              body={"path": "name", "value": name, "actor": CLIENT_NAME})
    state["machine_id"] = machine_id
    _save_state(state_file, state)
    log("Registered machine '%s' on server (id %s)" % (name, machine_id))
    return machine_id


def _sync_push(base_url, machine_id, machine_name, api_key, entries):
    """One snapshot /sync call: the .htg is the complete table, so the server
    reconciles away entries the operator cleared on the controller."""
    return http_json(
        "POST", "%s/api/v1/tool-table-entry-records/sync" % base_url, api_key,
        body={
            "machine_id": machine_id,
            "client": CLIENT_NAME,
            "machine_name": machine_name,
            "client_version": CLIENT_VERSION,
            "mode": "snapshot",
            "force": False,
            "entries": entries,
        })


def _fetch_entries(base_url, machine_id, api_key):
    return http_json(
        "GET", "%s/api/v1/tool-table-entry-records?machine_id=%s"
        % (base_url, machine_id), api_key).get("items", [])


# ---------------------------------------------------------------------------
# Verbs
# ---------------------------------------------------------------------------

def _resolve_inputs(config):
    """(base_url, machine_name, htg_path) or (None, None, None, exit_code)."""
    base_url = (config.get("LOOBRIC_API_URL") or "").rstrip("/")
    machine_name = config.get("MACHINE_NAME")
    if not base_url or not machine_name:
        log("ERROR: LOOBRIC_API_URL and MACHINE_NAME must be configured")
        return None, None, None, 2
    htg_path = config.get("MASSO_HTG")
    if not htg_path:
        usb = config.get("MASSO_USB")
        if not usb:
            log("ERROR: MASSO_USB (the stick's mount point) or MASSO_HTG "
                "(the tool file itself) must be configured")
            return None, None, None, 2
        try:
            htg_path = find_htg(usb)
        except HtgError as e:
            log("ERROR: %s" % e)
            return None, None, None, 2
    return base_url, machine_name, htg_path, None


def _read_table(htg_path):
    try:
        with open(htg_path, "rb") as f:
            return parse_htg(f.read())
    except OSError as e:
        raise HtgError("cannot read %s: %s" % (htg_path, e))


def push_tool_table(config):
    """.htg -> server: push every in-use record as an UNBOUND entry snapshot,
    harvesting the controller's probed Z offsets as observed values."""
    _init_log_file(config)
    base_url, machine_name, htg_path, err = _resolve_inputs(config)
    if err is not None:
        return err
    try:
        tools = _read_table(htg_path)
    except HtgError as e:
        log("ERROR: %s" % e)
        return 2

    units = config.get("UNITS", "mm")
    in_use = [t for t in tools[1:MAX_TOOL + 1] if record_in_use(t)]
    entries = [tool_to_entry(t, machine_name, units=units) for t in in_use]
    bad_crc = [t["index"] for t in in_use if not t["crc_valid"]]
    if bad_crc:
        log("NOTE: %d record(s) carry a non-standard CRC (T%s) - the "
            "controller's own variant; values pushed as read."
            % (len(bad_crc), ", T".join(str(n) for n in bad_crc)))

    state_file = _state_path(config, machine_name)
    state = _load_state(state_file)
    log("Pushing %d tools from %s as machine '%s'"
        % (len(entries), htg_path, machine_name))
    try:
        machine_id = _ensure_machine(base_url, config.get("LOOBRIC_API_KEY", ""),
                                     machine_name, state, state_file)
        result = _sync_push(base_url, machine_id, machine_name,
                            config.get("LOOBRIC_API_KEY", ""), entries)
    except ServerUnreachable as e:
        log("Server not reachable, will retry next sync: %s" % e)
        return 0
    except ServerError as e:
        log("ERROR: server rejected the push (HTTP %s): %s" % (e.code, e))
        return 0
    log("Pushed %d entries" % len(result.get("items", [])))
    removed = result.get("removed_tool_numbers") or []
    if removed:
        log("Reconciled %d entr%s cleared on the controller: T%s"
            % (len(removed), "ies" if len(removed) != 1 else "y",
               ", T".join(str(n) for n in removed)))
    for error in result.get("errors", []):
        log("Server rejected item %s: %s"
            % (error.get("index"), error.get("message")))
    return 0


def write_tool_table(config):
    """server -> .htg: merge the machine's entries into the tool table on the
    stick (backup first; untouched records stay byte-verbatim). The operator
    then loads the file on the controller and reboots."""
    _init_log_file(config)
    base_url, machine_name, htg_path, err = _resolve_inputs(config)
    if err is not None:
        return err
    try:
        tools = _read_table(htg_path)
    except HtgError as e:
        log("ERROR: %s" % e)
        return 2

    state_file = _state_path(config, machine_name)
    state = _load_state(state_file)
    try:
        machine_id = _ensure_machine(base_url, config.get("LOOBRIC_API_KEY", ""),
                                     machine_name, state, state_file)
        entries = _fetch_entries(base_url, machine_id,
                                 config.get("LOOBRIC_API_KEY", ""))
    except ServerUnreachable as e:
        log("Server not reachable, will retry next sync: %s" % e)
        return 0
    except ServerError as e:
        log("ERROR: server rejected the read (HTTP %s): %s" % (e.code, e))
        return 0

    changed = merge_entries_into_table(tools, entries, log=log)
    if not changed:
        log("Tool table already matches the server (%d entries) - nothing to "
            "write" % len(entries))
        return 0

    usb_root = config.get("MASSO_USB")
    if usb_root and os.path.isdir(os.path.join(usb_root, SETTINGS_DIR)):
        try:
            dest = backup_settings(usb_root)
            log("Backed up Machine Settings to %s" % dest)
        except OSError as e:
            log("ERROR: backup failed, refusing to write: %s" % e)
            return 2
    tmp = htg_path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(generate_htg(tools))
        os.replace(tmp, htg_path)
    except OSError as e:
        log("ERROR: cannot write %s: %s" % (htg_path, e))
        return 2
    log("Wrote %d change(s) to %s" % (changed, htg_path))
    log("Now load it on the controller: F1 Setup > Save & Load Calibration "
        "Settings > Load from file, then reboot.")
    return 0


def sync_tool_table(config):
    """Full cycle: harvest the controller's table, then write the server's
    view back to the stick."""
    code = push_tool_table(config)
    if code != 0:
        return code
    return write_tool_table(config)


# ---------------------------------------------------------------------------
# init / doctor
# ---------------------------------------------------------------------------

CONFIG_TEMPLATE = '''\
# Loobric MASSO client configuration.
# Edit the values below, then check them with:  loobric-masso doctor
#
# Environment variables of the same name override these. So does --url and a
# positional machine name on the command line.

LOOBRIC_API_URL="%(url)s"

# API key for a multi-user server. Leave blank against a solo-mode server.
LOOBRIC_API_KEY=""

# The name this controller appears under on the server.
MACHINE_NAME="masso01"

# Mount point of the USB stick the controller saved its settings to.
# The tool table is found automatically under MASSO/Machine Settings/;
# set MASSO_HTG to a file path instead to pin it explicitly.
MASSO_USB="/media/usb"
#MASSO_HTG=""

# The unit the controller is configured in (offsets are pushed as this).
UNITS="mm"

# Optional: where to write the sync log.
#LOG_DIR="/tmp/loobric-sync"
'''


def cmd_init(path, force=False, url=None):
    path = path or DEFAULT_CONFIG_PATH
    if os.path.exists(path) and not force:
        log("Config already exists at %s (use --force to overwrite)" % path)
        return 2
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(CONFIG_TEMPLATE % {"url": url or "http://localhost:8000"})
    log("Wrote starter config to %s - edit it, then run: loobric-masso doctor"
        % path)
    return 0


def cmd_doctor(config, config_path):
    ok = True
    print("Config: %s" % (config_path or DEFAULT_CONFIG_PATH))
    base_url = (config.get("LOOBRIC_API_URL") or "").rstrip("/")
    for key in ("LOOBRIC_API_URL", "MACHINE_NAME"):
        if config.get(key):
            print("  %s = %s" % (key, config[key]))
        else:
            print("  %s MISSING" % key)
            ok = False

    htg_path = config.get("MASSO_HTG")
    if htg_path:
        print("  MASSO_HTG = %s" % htg_path)
    elif config.get("MASSO_USB"):
        print("  MASSO_USB = %s" % config["MASSO_USB"])
        try:
            htg_path = find_htg(config["MASSO_USB"])
            print("  tool table: %s" % htg_path)
        except HtgError as e:
            print("  tool table: %s" % e)
            ok = False
    else:
        print("  MASSO_USB / MASSO_HTG MISSING")
        ok = False
    if htg_path and os.path.isfile(htg_path):
        try:
            tools = _read_table(htg_path)
            used = sum(1 for t in tools[1:MAX_TOOL + 1] if record_in_use(t))
            print("  tool table parses: %d tools in use" % used)
        except HtgError as e:
            print("  tool table UNREADABLE: %s" % e)
            ok = False

    if base_url:
        try:
            http_json("GET", "%s/api/health" % base_url, "")
            print("  server: reachable")
        except (ServerUnreachable, ServerError) as e:
            print("  server: %s" % e)
            ok = False
    print("OK" if ok else "PROBLEMS FOUND")
    return 0 if ok else 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="loobric-masso",
        description="Sync a MASSO G3 tool table (.htg on the controller's "
                    "USB stick) with a Loobric server.")
    parser.add_argument("--config", default=None,
                        help="config file (default: %s)" % DEFAULT_CONFIG_PATH)
    parser.add_argument("--url", default=None, help="server URL override")
    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="write a starter config file")
    init_p.add_argument("--force", action="store_true")
    sub.add_parser("doctor", help="check configuration, USB stick, and server")
    for name, helptext in (
            ("push", ".htg -> server (harvest probed offsets)"),
            ("write", "server -> .htg (update the tool table on the stick)"),
            ("sync", "push, then write")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("machine", nargs="?", default=None)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    if args.command == "init":
        return cmd_init(args.config, force=args.force, url=args.url)

    config = load_config(args.config)
    if args.url:
        config["LOOBRIC_API_URL"] = args.url
    if getattr(args, "machine", None):
        config["MACHINE_NAME"] = args.machine

    if args.command == "doctor":
        return cmd_doctor(config, args.config)
    if args.command == "push":
        return push_tool_table(config)
    if args.command == "write":
        return write_tool_table(config)
    if args.command == "sync":
        return sync_tool_table(config)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
