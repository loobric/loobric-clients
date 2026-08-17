# loobric-fusion

Loobric client for Autodesk Fusion tool libraries. File-based: it reads and
writes Fusion's `.tools` export (a zip wrapping a single `tools.json`) or the
bare `tools.json`, and syncs it bidirectionally with a
[Loobric](https://loobric.com) server — no Fusion add-in required, so it runs
anywhere the file does (including a Linux host with Fusion in a VM).

## What syncs

**Import (file → server).** Every cutting tool becomes a ToolInstanceRecord:

- The **whole tool dict rides verbatim** in `clients.fusion360.data.tool` —
  expressions, post-process, holder, start-values all survive losslessly.
- The well-understood facts are **asserted canonically** with provenance
  `asserted:fusion360`: name, `geometry.shape` (from the Fusion type),
  and the ISO-13399-coded dimensions DC/OAL/LCF/SFDM/NOF, each stamped with
  the tool's own unit system (mm/in). Unmapped codes are honestly absent.
- **Cutting data presets** (`start-values.presets`) are translated into the
  ratified normal form and contributed through the preset door:
  `v_c` → `vc` (m/min or ft/min by the tool's units), `f_z` → `fz` (mm or
  in), `v_f_plunge`/`v_f` → the vertical-feed ratio, the material statement
  verbatim, coolant/ramp-angle/guid in `extras`. Raw RPM and feeds are never
  persisted — they are derivations, not source data. A preset below the
  server's floor (no material statement, or no engineering values — e.g. a
  probe's approach feeds, or Fusion's all-zero defaults) stays in the client
  section, counted, never guessed.

**Export (server → file).** Each record regenerates from its verbatim client
copy; canonical values win only where they actually differ (parallel
`expressions` entries are updated in step so Fusion doesn't recompute the old
number). Other origins' preset recommendations — a manufacturer's, FreeCAD's,
an agent's — are **materialized as native Fusion presets** named
`<origin>: <label>`, with RPM and feed computed from the tool's own
diameter and flute count. Re-importing an exported file never forks another
origin's recommendation back as a fusion360 one; *editing* one in Fusion
does fork it into your own — changed numbers are your recipe.

`export --all` additionally synthesizes best-effort Fusion tools from records
other clients created (experimental — smoke-test the import in Fusion).

## Usage

```console
pip install loobric-fusion
export LOOBRIC_BASE_URL=https://api.loobric.com
export LOOBRIC_API_KEY=<a cam-preset key: read+sync+assert>

loobric-fusion doctor                       # check server, key, state
loobric-fusion import MyLibrary.tools       # Fusion -> Loobric
loobric-fusion import MyLibrary.tools --dry-run
loobric-fusion export FromLoobric.tools     # Loobric -> Fusion
loobric-fusion export FromLoobric.tools --all
```

In Fusion: CAM → Tool Library → right-click a library → **Export** to produce
the `.tools` file; **Import** to bring one back. Identity is the tool `guid`
(the server holds it as `client_item_id`; the local guid → record map lives
in `~/.config/loobric/fusion-state.json`), so repeat imports update instead
of duplicating and an unchanged library is a no-op.

## Development

```console
python -m pytest tests/
```

Pure translation lives in `mapping.py`/`presetsync.py` (no network, no
Fusion); the one dependency is the stdlib-only `loobric` client library from
[loobric-cli](https://github.com/loobric/loobric-cli) — client verbs are
added there first. See loobric-server's `docs/HOWTO_BUILD_A_CLIENT.md` for
the architecture this client follows.

## License

MIT
