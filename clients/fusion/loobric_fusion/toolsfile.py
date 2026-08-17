# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT

"""Read/write Fusion tool libraries.

Two containers, one payload: ``.tools`` is a zip wrapping a single
``tools.json``; a bare ``.json`` file is the same payload directly. The
payload is ``{"data": [<tool>, ...], "version": <int>}`` (version 36 as of
Fusion 2026). One stdlib parser — zipfile + json (SCHEMA_GAP_SPIKE.md §6).
"""
import json
import zipfile

# The library schema version we write when synthesizing a fresh file. Matches
# the version Fusion currently exports; on load the file's own version is
# preserved verbatim so round trips never churn it.
LIBRARY_VERSION = 36

INNER_NAME = "tools.json"


class ToolsFileError(Exception):
    """The file is not a Fusion tool library we can read."""


def load(path):
    """Load a ``.tools`` zip or bare ``tools.json`` -> the payload dict."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                inner = INNER_NAME if INNER_NAME in names else (
                    names[0] if len(names) == 1 else None)
                if inner is None:
                    raise ToolsFileError(
                        "%s: zip does not contain a single tools.json" % path)
                raw = zf.read(inner)
        else:
            with open(path, "rb") as fh:
                raw = fh.read()
        doc = json.loads(raw.decode("utf-8"))
    except ToolsFileError:
        raise
    except Exception as exc:
        raise ToolsFileError("%s: not a Fusion tool library (%s)" % (path, exc))
    if not isinstance(doc, dict) or not isinstance(doc.get("data"), list):
        raise ToolsFileError(
            "%s: payload has no 'data' list — not a Fusion tool library" % path)
    return doc


def save(doc, path):
    """Write the payload to ``path`` — zip container for ``.tools``, bare
    JSON otherwise. Content is identical either way."""
    doc.setdefault("version", LIBRARY_VERSION)
    payload = json.dumps(doc, indent=4, sort_keys=True)
    if str(path).lower().endswith(".tools"):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(INNER_NAME, payload)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(payload)
