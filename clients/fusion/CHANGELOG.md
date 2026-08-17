# Changelog

All notable changes to loobric-fusion are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Changed
- **Import goes through the batch sync door** (loobric-server 0.15.0,
  docs/BATCH_SYNC.md) when the server has it: the whole library — client
  data, canonical asserts, preset contributions — rides
  `client.sync_tool_records()` in 200-item chunks, one transaction each.
  Measured: the 327-tool Amana import dropped from ~11 min (per-record
  doors, 8 workers) to ~4 s / 3 requests. Stale own-origin presets are
  still pruned per-record, but only for tools the server reports
  `updated`. A pre-0.15 server (or a client library without the verb)
  falls back to the per-record path automatically; `--dry-run` always
  uses it. Batch item errors are counted (`errors`) and exit 1.

## [0.1.0] - 2026-08-17

First client. Pairs with loobric-server ≥ 0.13.0 (the preset door) and
loobric-cli ≥ 1.7.0.

### Added
- `.tools`/`tools.json` reader-writer (one stdlib parser: zipfile + json;
  library schema version 36 preserved verbatim on round trip).
- `import`: Fusion tools → ToolInstanceRecords. Verbatim passthrough in
  `clients.fusion360.data.tool`; canonical asserts for name, shape
  (conservative Fusion-type → shape map, honest absence on unknowns) and
  DC/OAL/LCF/SFDM/NOF with per-tool units; tool `guid` as `client_item_id`
  with a local state file (`~/.config/loobric/fusion-state.json`) and
  re-adoption by item id when state is lost; unchanged tools are a no-op
  (zero assert churn); holders skipped; `--dry-run`.
- Preset promotion through the contribution door, origin `fusion360`,
  replace-own on `(origin, label)` with per-tool label dedup: `v_c`→`vc`
  (m/min | ft/min by the tool's unit system), `f_z`→`fz` (mm | in),
  `v_f_plunge/v_f`→`ratio`, material statement verbatim (including Fusion's
  `"all"`), coolant/ramp-angle/preset-guid in `extras`; below-floor presets
  counted and left in the client section; prune of fusion360-origin entries
  whose preset vanished locally; preset failures never fail the sync.
- `export`: records → a Fusion library. Lossless regeneration (canonical
  wins only on real differences, `expressions` updated in step, mm↔in
  conversion when canonical and file disagree on units); other origins'
  presets materialized as `"<origin>: <label>"` natives carrying Fusion's
  full preset field set (missing fields make the library UI flag the tool),
  with n/v_f computed from the tool's own DC/NOF and v_c derived back from
  the stored (rounded) n — Fusion treats n as authoritative and recomputes
  v_c on save, so the file must be self-consistent under its arithmetic;
  marked `loobric_external` with a name-pattern fallback (Fusion's editor
  strips unknown keys on save — confirmed against a real round trip) so an
  unedited round trip never forks a foreign recommendation; deterministic
  guids so re-exports never churn. `--all` synthesizes
  best-effort tools from canonical-only records (experimental); a unitless
  canonical leaf is read as millimeters — the ecosystem convention (the
  FreeCAD client asserts bare mm values), found on the first live sandbox
  run where every FreeCAD record skipped. Synthesized tools emit the full
  geometry ladder Fusion validates — OAL > LB >= shoulder-length >= LCF,
  probes on Fusion's reduced probe schema — plus the per-type required
  fields its editor writes when repairing a tool: CSP/HAND everywhere but
  probes, SFDM defaulting to DC, SIG on drills (no shoulder-diameter),
  TA/tip-diameter on chamfer mills. A tool with zero presets is itself
  flagged, so tools without materialized presets get Fusion's own stock
  preset reproduced exactly (n=5000, v_f=1000, derived v_c/f_z/f_n;
  drills plunge/retract-only; probes lead-in/link/measure) — and
  unnamed (name "") presets are never promoted back as fusion360
  recommendations, since that is Fusion's repair-template signature.
  Materialized presets default a missing vertical-feed ratio to 0.33
  (the FreeCAD client's display default) so plunge/ramp/f_n are
  non-zero. There is NO published Fusion schema (Autodesk's API docs say
  only "the JSON should fully define the tool"); all of these rules are
  reconstructed from Fusion's validation messages, the geometry of real
  exports it accepts, and diffs of what its editor writes when it
  "fixes" a flagged tool.
- `doctor`, explicit `loobric-fusion/<version>` User-Agent (Cloudflare),
  39-test suite over a real six-tool Fusion export fixture.

[0.1.0]: https://github.com/loobric/loobric-fusion/releases/tag/v0.1.0
