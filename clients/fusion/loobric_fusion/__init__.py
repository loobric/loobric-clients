# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT

"""Loobric client for Autodesk Fusion tool libraries.

File-based (Phase 1): reads and writes Fusion ``.tools`` libraries (a zip
wrapping a single ``tools.json``) or the bare ``tools.json`` payload, and syncs
them bidirectionally with a Loobric server — tools as ToolInstanceRecords,
``start-values`` presets through the cutting-data-preset contribution door.

Keep pyproject.toml `version` and CLIENT_VERSION in lockstep.
"""

CLIENT_NAME = "fusion360"
CLIENT_VERSION = "0.1.0"
