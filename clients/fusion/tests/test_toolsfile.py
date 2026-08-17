# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT
import json
import zipfile

import pytest

from loobric_fusion import toolsfile


def test_load_bare_json(tmp_path, sample_doc):
    path = tmp_path / "lib.json"
    path.write_text(json.dumps(sample_doc))
    doc = toolsfile.load(str(path))
    assert doc["version"] == sample_doc["version"]
    assert len(doc["data"]) == 6


def test_zip_round_trip(tmp_path, sample_doc):
    path = tmp_path / "lib.tools"
    toolsfile.save(sample_doc, str(path))
    assert zipfile.is_zipfile(path)
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist() == ["tools.json"]
    assert toolsfile.load(str(path)) == sample_doc


def test_json_round_trip(tmp_path, sample_doc):
    path = tmp_path / "out.json"
    toolsfile.save(sample_doc, str(path))
    assert not zipfile.is_zipfile(path)
    assert toolsfile.load(str(path)) == sample_doc


def test_save_defaults_version(tmp_path):
    path = tmp_path / "out.json"
    toolsfile.save({"data": []}, str(path))
    assert toolsfile.load(str(path))["version"] == toolsfile.LIBRARY_VERSION


def test_load_rejects_non_library(tmp_path):
    path = tmp_path / "not.json"
    path.write_text(json.dumps({"hello": 1}))
    with pytest.raises(toolsfile.ToolsFileError):
        toolsfile.load(str(path))
    path2 = tmp_path / "garbage.tools"
    path2.write_bytes(b"not a zip and not json")
    with pytest.raises(toolsfile.ToolsFileError):
        toolsfile.load(str(path2))
