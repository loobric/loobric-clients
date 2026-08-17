# Client Landscape

A survey of software and hardware that produces or consumes CNC **tool data**
— tool geometry, feeds & speeds, tool tables, tool numbers/pockets/offsets,
tool life — and could therefore become a Loobric client (bidirectional sync) or
data source (one-way ingest).

**Status today.** Shipping clients: the reference CLI (`loobric-cli`),
**FreeCAD CAM**, and **LinuxCNC**. Shipping importers: DIN 4000, STEP P21,
GTC/ISO 13399, SolidCAM, hyperMILL.

**A client class this survey predates: AI agents.** The **Loobric MCP
server** (`loobric-mcp`, shipped from the loobric-cli repo — see the
top-level `MCP_PLAN.md`) lets any MCP host (Claude Code, Claude Desktop, …)
read and write tool data through the public API's audited doors: every agent
write is stamped `asserted:<agent>@mcp`, agents assert but never observe, and
they cannot delete, confirm bindings, or overwrite machine-measured values.
Strategically it also bends this document's central finding: agents collapse
the marginal cost of format mapping, so the format-first investments below
get cheaper to multiply — while the canonical schema and provenance ledger
become the part that matters most.

> Research compiled 2026-06-29. Ratings are point-in-time; closed/commercial
> systems change their integration surface without notice. Verify the
> highest-stakes facts (a vendor's format, a paywall, a community's activity)
> before committing engineering or recruiting effort.

## The one finding that drives everything

**The leverage is in formats, not vendor APIs.** Almost nothing in this space
exposes a public, writable REST API — every "API" is sales- or partner-gated
and undocumented publicly. But a handful of **open file formats each unlock
several candidates at once**, and the most important ones are SQLite databases
or documented JSON readable with the Python standard library Loobric already
restricts itself to. Build formats, not one-off integrations.

Three format investments cover most of the reachable surface:

1. **Fusion tool-library format** (`.json` / `.tools`, official published
   schema). One importer/exporter serves Fusion (hobby + pro), HSMWorks
   migrants, Harvey/Helical free vendor libraries, HSMAdvisor round-tripping,
   and ProvenCut's export path.
2. **SQLite tool databases.** The same `sqlite3` read pattern handles
   Mastercam `.tooldb`, Vectric `.vtdb`, and CAMWorks `.cwdb` — three heavy
   hitters sharing an open, inspectable container.
3. **MTConnect `CuttingTool` assets.** The open cross-vendor route for the live
   tool-life / pot-location / inventory axis that ISO 13399 and GTC structurally
   cannot hold. **Read-only to the control** (writing an asset populates the
   *agent's* buffer for read-back, never the machine) — so it's an *observe*
   route, not a write-back one. See [Protocol leverage](#protocol-leverage).

## How to read the ratings

- **Docs** — format/API documentation: *Good* / *Partial* / *RE-needed*
  (reverse engineering) / *Closed* / *None* (no tool store exists).
- **Comm** — recruitable tester community.
- **Desire** — value of building the client, value × feasibility × recruitability.
- **Cat** — CAM / Control / Mgmt / Catalog / Standard.

---

## CAM software

| Client | Cat | Docs | Comm | Desire | Integration route |
|---|---|---|---|---|---|
| **Autodesk Fusion** (hobby+pro) | CAM | Good (official JSON schema @ cam.autodesk.com/hsmtools) | Very high | **HIGH** | File `.json`/`.tools`. CAM API is effectively read-only for tools — sync via file. |
| **Mastercam** | CAM | Partial (SQLite `.tooldb`; vendor calls it "non-proprietary") | High (eMastercam dev subforum) | **HIGH** | SQLite read + NET-Hook SDK write |
| **Vectric** (Aspire/VCarve/Cut2D) | CAM | Partial (SQLite `.vtdb`, community-mapped schema) | High (forum.vectric.com) | **HIGH** | Read/write `.vtdb` directly |
| **Carbide Create** | CAM | Partial (open CSV since v440) | High (Discourse + r/Shapeoko) | Med-High | Trivial CSV read/write. Becoming a de-facto interchange format. |
| **HSMWorks** | CAM | Partial (`.hsmlib` XML = Fusion's) | Fading (EOL Mar 2028) | Low | Covered for free by the Fusion client |
| **SolidWorks CAM / CAMWorks** | CAM | Partial (SQLite `.cwdb` 2018+; Access before) | Moderate/scattered | Medium | `sqlite3` read + COM add-in write |
| **Siemens NX CAM** | CAM | Partial (ASCII `.dat` + NX Open Python API) | Moderate (enterprise) | Medium | NX Open for numbers/offsets + `.dat` for geometry |
| **Solid Edge CAM** | CAM | Partial (NX `.dat` *or* CAMWorks `.cwdb`, depends on product) | Fragmented | Low-Med | Inherit NX or CAMWorks client; don't assume one covers both |
| **Hexagon ESPRIT** | CAM | Partial (`.ETL` lib + COM/.NET API) | Moderate (Practical Machinist) | Med-High | .NET add-in on the Cutting Tool KB; `.ETL` fallback |
| **EDGECAM** (Hexagon) | CAM | Partial (ToolStore on MS SQL Server) | Moderate | Medium | Direct DB integration |
| **BobCAD-CAM** | CAM | Good (plain XML import/export) | Medium (Facebook groups) | Medium | XML round-trip |
| **GibbsCAM** (Sandvik) | CAM | Closed (`.vnc`); ISO 13399 via CoroPlus | Moderate | Medium | Standards play, not a true client |
| **PowerMill** | CAM | RE (Access `.mdb`) + official OSS .NET API | Moderate (high-end) | Medium | .NET plugin via the official API |
| **SheetCam** (plasma/laser/router) | CAM | Good (plaintext `.tools` + Lua/DLL API) | Active (first-party forum) | High | File + Lua plugin |
| **Estlcam** | CAM/Ctrl | RE (v12+ semicolon CSV; v11 gzip binary) | Niche (V1 Engineering) | Medium | CSV, v12+ only |
| **Kiri:Moto** | CAM | Partial (base64-JSON `.km`; open source) | Med (Discord ~1.4k) | Medium | `.km` round-trip |
| **CAMotics** | CAM/sim | Partial (JSON `tools.json`; GPL source) | Small (GitHub) | Medium | File; geometry-only subset maps |
| **OpenBuilds CAM** | CAM | RE (open-source JS) | Large free ecosystem | Med-High | Read format from source |
| **Easel** (Inventables) | CAM | Closed (cloud-only, no local file/API) | Moderate | Low | None feasible without Inventables |

## CNC controls, firmware, senders

| Client | Cat | Docs | Comm | Desire | Integration route |
|---|---|---|---|---|---|
| **Tormach PathPilot** | Control | Good (it *is* LinuxCNC `tool.tbl`) | Strong | **HIGH** | Parser reuse from LinuxCNC client; **write path is NOT free** — PathPilot's authoritative tool state lives in local Redis (`dump.rdb`), external `tool.tbl` edits revert on restart, descriptions are Redis-only (2026-08-17 research, issue #9). Read/harvest works as-is. |
| **Heidenhain TNC** | Control | Good (plaintext `TOOL.T`, incl. tool-life columns) | Moderate (industrial) | **HIGH** | File via free TNCremo/LSV2; no SDK or option needed |
| **Haas NGC** | Control | Partial (`O999999` / Setting-157 offset file) | Strong (PM subforum, r/Haas) | **HIGH** | File over USB/Ethernet; no SDK |
| **Okuma OSP** (THINC) | Control | Good (free, write-capable .NET SDK) | Strong (PM subforum) | **HIGH** | On-machine THINC app → Loobric over network. Verify full-table coverage in the SDK `.chm`. |
| **Mach4** | Control | Partial (Lua API + user-definable custom fields) | Active | High | Lua plugin; custom fields fit Loobric provenance |
| **Mach3** | Control | RE (binary `.dat`, layout published) | Large | High | File sync of `.dat`; corruption-prone, version-sensitive |
| **RepRapFirmware / Duet** | Control | Good (`M563`/`G10`, Object Model `tools[]`) | Active/technical | Med-High | HTTP object-model API; no native diameter register |
| **grblHAL** | Control | Partial (opt-in tool table, ≤32 tools) | Active/technical (Discord) | Med (High for ATC) | Serial `$`-cmd or C plugin. Verify NVS persistence (core#494). |
| **Centroid** (Acorn/Oak) | Control | Partial (`.tl`/`.ol`; internals RE) | Active/hobbyist | Medium | File read/write on the control PC |
| **Masso** G3 | Control | RE (`.htg` binary, already cracked) | Good | Medium | File; thin data model (name/dia/Z/slot) |
| **Fanuc** | Control | Good API (FOCAS `cnc_wrtofs*`) but option- and SDK-gated | Large/industrial | Med-High | FOCAS API for true sync; G10 file fallback |
| **gSender** (Sienci) | Sender | RE (tool table new in v1.6; JSON config) | High (Sienci forum, FB) | Medium | Config import/export; thin, unstable schema |
| **Brother** Speedio | Control | RE (USB tool-list/CSV export) | Medium (g53.io) | Medium | File/CSV over Ethernet share |
| **Mitsubishi** M8 | Control | Partial (CNC Open API socket/DLL) | Medium | Medium | EZSocket over TCP 683; tool-data specifics unverified |
| **Fagor** | Control | Partial (ASCII export + free simulator) | Low-Med | Low-Med | ASCII file export/import |
| **Siemens Sinumerik** | Control | Good spec, every path license-gated | Weakest (no hobbyists) | Medium | OPC UA tool nodes (paid) or `%TOA` file. Partner-gated. |
| **Mazak** (Mazatrol/LOOBRIC) | Control | Closed binary | Active (industrial) | **AVOID** | Proprietary binary **and** brand collision (see below) |
| GRBL, UGS, Candle, bCNC, CNCjs, Marlin, Klipper | Ctrl/Sender | None (no persistent tool table) | Large | **Low** | Nothing canonical to sync — GRBL-class hardware re-probes a single runtime TLO per change |

## Tool management, presetters, catalogs, standards

Mostly **data sources** (one-way ingest of nominal geometry) rather than
bidirectional clients. Loobric already ingests GTC/ISO 13399 — the move is to
deepen that, not to chase gated vendor APIs.

| Candidate | Cat | Docs | Role | Desire | Route |
|---|---|---|---|---|---|
| **MachiningCloud** | Catalog | Partial (free GTC/ISO 13399 export) | Data source | **HIGH** | User-exported GTC import — works today, best demo target |
| **MTConnect** Part 4.1 | Standard | Good, open; **read-only to control** | Live-state ingest | **HIGH** | `CuttingTool` asset client; cross-vendor *observe* of tool-life/location (not write-back) |
| **ToolsUnited** (CIMSOURCE) | Catalog | Partial (DIN 4000/13399/GTC) | Data source | High (paywalled) | User GTC export; ToolsUnitedDirect = partnership |
| **HSMAdvisor / FSWizard** | F&S+mgmt | Partial (Fusion JSON + `.hsmlib`) | Bidirectional client | High | File round-trip; living, approachable dev |
| **Sandvik CoroPlus** | Catalog/lib | Partial (ISO 13399/GTC; API partner-gated) | Data source | High | Standard import; partnership for the live API |
| **Kennametal NOVO** | Catalog | Partial (ISO 13399 export; public API is e-commerce only) | Data source | Medium | Standard import (already a Loobric sample source) |
| **Harvey / Helical** | Catalog+F&S | Partial (free Fusion/Mastercam libraries) | Data source | High | Ingest via the Fusion-format importer |
| **Zoller / TDM / WinTool** | Mgmt | Closed (partner-gated WebService) | Peer TMS client | Med-High | Partnership only; GTC exchange where possible |
| **Haimer Microset** | Presetter | Partial (measured offsets out) | Data source | High (as-set geometry) | Per-control post-processor formats |
| **ProvenCut** | F&S | Closed (Fusion-export link) | Data source | Medium | Partnership; high-provenance, low-volume |
| **G-Wizard** | F&S | Partial CSV — EOL (sole dev died 2024) | Migration rescue | Low | One-way CSV import only |
| **Adveon** | Lib | Deprecated | — | **SKIP** | Subsumed by CoroPlus / ISO 13399 |
| **GTC / ISO 13399** | Standard | Good (GTC) / paywalled (13399) | Foundation | High | Already ingested — deepen coverage |

---

## Integration depth

Two systems can both "have a Loobric client" and deliver completely different
value. LinuxCNC taught this: the cron CLI (`loobric_linuxcnc.py sync`) keeps the
tool table consistent, but it is *blind* — it cannot tell the operator "mount
T5 now." Surfacing that required a second, deeper piece: the GladeVCP panel
embedded in the LinuxCNC UI. **Data-format openness and integration depth are
independent axes** — Vectric has wide-open SQLite yet cannot host an ambient
panel; Carbide Create's data is reachable only by editing files with the app
closed.

Classify each integration two ways: the **ceiling** (deepest rung the host's
extension surface *permits*) and the **status** (deepest rung we have *built*).
The gap between them is the real backlog.

### The depth ladder

| Rung | Name | What it delivers | LinuxCNC analog |
|---|---|---|---|
| **D0** | None | No programmatic surface (closed cloud / opaque binary, no file) | — |
| **D1** | Manual exchange | User hand-exports/imports a file; one-shot | — |
| **D2** | Unattended sync | Headless/CLI/cron syncs data both ways; blind to prompts | `loobric_linuxcnc.py sync` |
| **D3** | In-app, user-invoked | Code runs inside the host; user clicks to sync; inline feedback | FreeCAD "Loobric" button |
| **D4** | Ambient panel | Persistent/dockable UI that **surfaces server-driven state** — mount requests, conflicts, requested tools, bind status | **GladeVCP panel** |
| **D5** | Event-driven/live | Reacts to host runtime events (tool change, touch-off) and/or server push; closes the loop automatically | — |

The "mount request" need is specifically **D4+**: a persistent UI that polls or
subscribes and alerts the operator *in context*. D2 sync alone can never do it.

### Two ceilings, not one

A host can have a high *UI/event* ceiling but a low *data-write* ceiling — rate
both. **Fusion is the canonical case:** UI ceiling **D5** (documented dockable
HTML palettes + a resident add-in subscribing to runtime events + a
worker-thread→`fireCustomEvent` bridge for async polling — *exactly* the
mount-request panel pattern), but its CAM tool-*write* API is effectively
read-only, so tool writes go through `.json`/`.tools` files. The right Fusion
design is a D4/D5 palette that **surfaces** server state while **writing** tools
by file.

A second cross-cutting finding: **a high UI ceiling is worthless without tool
data to sync.** CNCjs and UGS can both host a deep out-of-tree panel (D5), but
neither has a tool table — so their depth ceiling is high and their data value
is ~zero. Both axes gate value.

### CAM hosts — ceiling & status

| Host | UI/event ceiling | Async mount-request panel? | Data-write surface | Status today |
|---|---|---|---|---|
| **FreeCAD** | **D5** (`addDockWidget` + Document/Selection observers + `QTimer`) | Yes | Full (own model) | **D3 shipped** (button + prefs) → gap is D4 panel |
| **Fusion** | **D5** (HTML palette + resident add-in events + worker→`fireCustomEvent`) | **Yes — documented for this exact use** | Low (CAM tool API read-only → file) | none |
| **SolidWorks CAM / CAMWorks** | **D5** (`ITaskpaneView` dockable + SldWorks events + TechDB tool API) | Yes — cleanest desktop fit | TechDB via COM | none |
| **NX CAM** | **D5** (docked Block dialog + UF/NXOpen callbacks) | Yes | NX Open | none |
| **ESPRIT** | **D5** (COM/.NET add-in window + event sinks) | Yes (verify TNG specifics) | KB API | none |
| **Kiri:Moto** | **D5 (web)** (web panel / Onshape tab + engine listeners) | Yes (you host/embed) | JSON | none |
| **PowerMill** | **D4** (plugin dockable pane, poll-only) | Yes by polling | COM / `.mdb` | none |
| **Mastercam** | **D3** (ribbon button + modal/floating form) | No (clean) | SQLite + NET-Hook | none |
| **Vectric** | **D3** (Gadgets, Lua, modal only) | No | SQLite (file) | none |
| **BobCAD** | **D3** (Lua, user-invoked) | No (public; deeper is partner-gated) | XML | none |
| **Carbide Create** | **D1** (no plugin runtime) | No | CSV (file, app closed) | none |
| **Estlcam** | **D1** | No | CSV | none |
| **CAMotics** | **D2** (headless TPL only) | No (fork to add UI) | JSON | none |

### CNC controls — ceiling & status

| Control | UI/event ceiling (on-control) | Async mount-request panel ON control? | Data exchange | Status today |
|---|---|---|---|---|
| **LinuxCNC** | **D5** (GladeVCP + HAL) | **Yes — the reference** | `.tbl` | **D2 + D4 shipped** |
| **Tormach PathPilot** | **D5** (it *is* LinuxCNC) | Yes — but unsupported, update-fragile (`ui_hooks` survives) | `.tbl` | none → **can inherit both LinuxCNC pieces** |
| **Okuma OSP (THINC)** | **D5** (public SDK + App Store + Startup Service) | **Yes — best industrial panel target** | THINC API r/w | none |
| **Centroid Acorn** | **D5/D4** (VCP + PLC async messages; sidecar for server) | Yes — vendor-sanctioned | `.tl`/`.ol` | none |
| **Mach4** | **D5** (screen tab + PLC script + signal scripts) | Yes — fully open | Lua API | none |
| **Mach3** | **D4** (screenset + macropump; D5 needs C++ plugin) | Yes | binary `.dat` | none |
| **Duet / DWC** | **D5** (out-of-tree ZIP plugin + object model) | Yes — cleanest open target | object-model API | none |
| **CNCjs** | **D5** (mounted widget) | Yes — *but no tool table to sync* | none | none |
| **UGS** | **D5** (ship a build) | Yes — *but no tool table to sync* | none | none |
| **gSender** | **D5 fork-only** | Fork, or separate sidecar window | thin JSON | none |
| **grblHAL** | firmware events only | No (no screen; routes to sender) | opt-in table | none |
| **Heidenhain TNC** | **D3** on-control / D5 *external companion* | **No on-control** (OEM wall) — external companion only | `TOOL.T` file | none |
| **Haas NGC** | **D3** (program-triggered messages) | No (external PC display only) | offset file | none |
| **Fanuc** | **D2** + D3 macro messages (deeper = OEM-licensed) | No (for a typical third party) | FOCAS / G10 | none |

### What depth changes about priorities

- **PathPilot is even stronger than first scored.** It's not just a cheap D2
  reuse — because it *is* LinuxCNC, it can inherit the **GladeVCP D4 panel too**.
  It's the only candidate where the full mount-request experience is nearly free.
- **Fusion's D4 palette is the flagship demo:** surfacing "mount T5" *inside
  Fusion* is a wow moment, and the architecture is documented. Build it as a
  second slice on top of the file-based importer (sync core + surface, the
  LinuxCNC split).
- **Raise the existing FreeCAD addon D3→D4.** The ceiling is already D5; the
  request-surfacing panel is the highest-value deepening of a client we already
  ship, and it proves the pattern the other D4 hosts will copy.
- **For walled controls (Heidenhain, Haas, Fanuc), D2 is the ceiling-bound
  deliverable.** An on-control ambient panel is impossible for a third party;
  don't burn effort chasing it. Surfacing for these shops, if needed, is an
  *external companion* app, not an on-control panel.
- **Principle:** *target the rung the need requires, capped by the ceiling.*
  Build the host-agnostic sync core first; add the surface only where the
  ceiling permits it and the operator need justifies it.

---

## Protocol leverage

A third axis, alongside extension-surface ceiling and data-format openness:
**what standards a platform already speaks.** A standard supported across N
platforms can be a force multiplier — one adapter, many platforms — *but only
when the standard covers the data **and the direction** you need.* The decisive
finding (researched 2026-06-30):

> **There is no released, standardized, cross-vendor route to *write* tool data
> into a CNC control.** Every genuinely cross-vendor standard (OPC UA 40501-1
> "umati", MTConnect) is **read-only** for tool data. Every route that can write
> is either single-vendor (FOCAS, THINC, Heidenhain RemoTools, Siemens' licensed
> OPC UA) or a file-exchange format. So "platform supports MTConnect/OPC UA"
> buys the **observe half** across many platforms — never the write-back.

### Split each integration into three data-axes, each with its own route

Don't model an integration as one monolithic per-vendor client. Mux three routes:

| Data axis | Best route | Direction | Multiplier? |
|---|---|---|---|
| **Catalog / nominal geometry / assemblies** | GTC / ISO 13399 / STEP-P21 | read+write (file) | **Yes — Loobric already parses it** |
| **Live state** (tool life, pot/magazine location, measured geometry) | MTConnect + OPC UA 40501-1 | **read-only** | **Yes, but observe-only** |
| **Write-back** (offsets, tool table) | per-vendor SDK (FOCAS / Siemens-UA / RemoTools / THINC) | read+write | **No — single-vendor** |

A Fanuc integration is therefore *GTC-catalog + MTConnect/OPC-UA-observe +
FOCAS-write* — composed, not monolithic. Provenance falls out of the route:
GTC → `asserted:catalog-import`; MTConnect/OPC-UA → `observed:…@machine`;
SDK write → `asserted`/`observed` per node.

### The standards landscape for tool data

| Standard | Tool-data R/W | Platforms exposing tool data via it | Multiplier? |
|---|---|---|---|
| **GTC / ISO 13399 / STEP-P21** | **read+write (file)** | Fusion, Mastercam, NX (read); **MachiningCloud, TDM** (read+write hubs); Sandvik CoroPlus (produces); all vendor catalogs | **YES — the real one; already parsed** |
| **OPC UA 40501-1 (umati)** | **read-only** | Siemens, Heidenhain, Okuma, Mazak, most umati controls (monitoring) | Cross-vendor but observe-only |
| **MTConnect (+ MQTT)** | **read-only** (asset PUT writes *agent*, not control) | Okuma emits `CuttingTool` assets; most others status-only | Cross-vendor but observe-only |
| **DIN 4000** | read+write (file) | Zoller, TDM, WinTool, Haimer (German TMS tier; CAM ignores it) | Partial (TMS tier) |
| **Siemens Sinumerik OPC UA tool mgmt** | **read+write** | Siemens 840D sl / 828D / ONE | No — single-vendor, licensed |
| **FANUC FOCAS** | **read+write** (`cnc_wrtofs`, tool life) | Fanuc (largest base) | No — single-vendor |
| **Okuma THINC API** | **read+write** | Okuma OSP-P | No — single-vendor |
| **Heidenhain RemoTools / OPC UA FileSystem** | **read+write** (`setToolTableRow` / whole-file) | Heidenhain TNC | No — single-vendor, licensed |
| **STEP-NC (ISO 14649)** | read+write (file) | ~none in production (demos only) | Cross-vendor in theory, dead in practice |
| **QIF** | n/a (no cutting-tool data) | — | No |

### What this changes about priorities

- **Deepening GTC/ISO 13399 ingest is the highest-leverage standards play** — it
  is the *only* genuine cross-vendor multiplier, and Loobric already parses it.
  **MachiningCloud and TDM are the two bidirectional hubs** worth targeting; a
  subscribed user there exports GTC for the whole catalog tier.
- **A single cross-vendor read-ingest adapter** (MTConnect + OPC UA 40501-1)
  covers *observability* — live tool-life / location — across the whole control
  fleet cheaply. That's the control-side multiplier, and it's observe-only.
  (This is why the MTConnect client is a Wave 1 gap-finder, #8.)
- **Write-back to controls is irreducibly per-vendor.** Scope it as a small set
  of deliberate single-vendor SDK bets ranked by installed base: **FOCAS
  (Fanuc) → Siemens OPC UA → Heidenhain RemoTools → Okuma THINC.** Don't wait
  for a standard that isn't coming.
- **Don't double-build the observe half.** Where a control speaks MTConnect/OPC
  UA, get live state from the standard; spend bespoke effort only on its write
  path. (e.g. Heidenhain `TOOL.T` file write + MTConnect observe, not two reads.)

---

## Prioritization

### Sequence by schema-shape risk first, reach second

The dominant cost to minimize is **canonical-schema churn**: a change to the
`canonical` shape fans out to *every* client adapter, so a client that arrives
late and forces such a change reworks all the clients built before it.
Therefore sequence by **schema-shape risk**, not by build difficulty or reach.

Reading `loobric-server/docs/TOOL_SCHEMA.md`, the three-section model with per-field
provenance is well-factored, and it already absorbs several axes: nominal vs
measured vs as-set geometry, media/3D models, and — critically —
**composition/assemblies are *allowed* in the schema** (`item_type`,
`components`, `derived:components` gauge length) with the *behavior* explicitly
deferred ("they layer on without further schema change"). That design bet —
*the schema allows it; behavior layers on later* — means the rework risk is
concentrated **only in axes the schema has no hooks for yet:**

| Axis | Hook today? | Client that forces it |
|---|---|---|
| Tool life (cumulative/remaining time, count) | **Absent** | MTConnect, Heidenhain `TIME1/2/CUR.TIME` |
| Sister / redundant tools | **Absent** | Heidenhain `TL/RT`, magazine controls |
| Rich wear-offset model (geometry vs wear, length+dia) | Underspecified | Heidenhain `DL/DR/DR2`, Fanuc registers |
| Turning geometry / orientation / multi-edge items | Role exists, geometry thin | Mastercam / NX / Esprit turning |
| Assemblies / holders | **Hooks exist**, behavior unbuilt | Fusion, Mastercam, GTC |

This re-sorts every candidate by *learning value to the core*:

- **Tier A — force canonical-schema decisions not yet hooked (build FIRST):**
  Heidenhain, MTConnect, one turning CAM. These are the rework-causers; building
  them early is what locks the canonical shape.
- **Tier B — exercise existing hooks, force behavior not schema:** Fusion /
  Mastercam assemblies, GTC deepening. Real work, but low schema risk.
- **Tier C — pure reach, teach the model nothing new:** PathPilot, Carbide,
  Vectric, Masso, gSender. Safe to build anytime, against a stable contract.

**Best single gap-finder: Heidenhain `TOOL.T`** — it hits three unhooked axes
at once (wear deltas, tool life, sister tools) and is a documented plaintext
file with a free transfer tool: maximum conceptual stress, minimum build
friction. (This inverts a naive "PathPilot first" call — PathPilot is LinuxCNC
again and teaches the model nothing, so it's a momentum side-quest, not the lead.)

### The format investments still hold (within Tier B/C)

Fusion tool-library import/export, the SQLite tool-DB reader (Mastercam +
Vectric + CAMWorks), and the MTConnect `CuttingTool` asset client each unlock a
whole column of the tables above, and all three fit the stdlib-only constraint.
MTConnect is special — it's both a format investment *and* a Tier-A gap-finder
(live tool-life/location), so it earns an early slot.

### Other standing calls

- **Skip the GRBL universe almost entirely.** GRBL-class hardware stores no
   tool table, so senders on top of it (UGS, Candle, bCNC, CNCjs, classic
   GRBL) have nothing canonical to sync. The exceptions with real data are full
   controls (Mach, PathPilot, Masso, Centroid) and the two firmwares with
   first-class tool objects (Duet, grblHAL-ATC).

- **Treat catalogs as ingest, not clients.** MachiningCloud, ToolsUnited,
  Sandvik, Kennametal, Harvey are nominal-geometry sources. Polish the "user
  exports a GTC package → imports to Loobric" path. MachiningCloud's *free* GTC
  export makes it the best demo target today. Don't chase their gated APIs.

- **Two hard "avoid" calls.**
   - **Mazak** — proprietary binary *and* an in-domain brand collision:
     Mazak's control line is branded **"LOOBRIC"** with competing "LOOBRIC Tool
     Management" products in this exact space. "Loobric for LOOBRIC" is
     unmarketable and carries trademark/SEO risk.
   - **Siemens Sinumerik** — technically clean (writable OPC UA tool nodes) but
     triple-license-gated with zero recruitable testers. Partner-gated only.

- **Recruiting reality (a Wave-2 concern).** Hobbyist/prosumer communities
  (Vectric, Carbide Discourse, r/Fusion360, r/Haas, V1 Engineering, Sienci) are
  far easier to recruit testers from than industrial ones. This argues for the
  *reach* wave being community-led (Fusion + Vectric + Carbide + Haas +
  PathPilot, where forum posts yield testers the same week) — but it does NOT
  set the gap-finding order. The Tier-A gap-finders (Heidenhain, MTConnect) have
  slower, relationship-based recruiting; accept that, because their job is to
  stabilize the schema, not to win testers. Mitigation: Heidenhain is
  mechanically easy despite being conceptually hard, and PathPilot can run as a
  single parallel momentum win.

### Suggested build order (schema-first)

**Wave 0 — schema gap spike (cheap, parallelizable, do before any Wave-1 code).**
Map the full field sets of **Heidenhain `TOOL.T`**, **MTConnect `CuttingTool`**,
and **a Mastercam turning + assembly library** onto the `loobric/contract/`
Pydantic models *on paper*. Every field with no home is a canonical gap. Output:
the list of required canonical additions (tool life, sister tools, wear-offset
model, turning geometry) — found for ~zero build cost, before writing a client
against a still-moving schema.

**Wave 1 — gap-finders (lock the canonical shape):**
1. **Heidenhain `TOOL.T`** — densest gap-finder (wear deltas + tool life +
   sister tools), plaintext, free transfer tool. Build first.
2. **One turning CAM — Mastercam** (open SQLite `.tooldb`, rich, recruitable) —
   validates turning geometry + assembly behavior.
3. **MTConnect asset client** — validates live tool-life/location ingest
   (observe-only; see [Protocol leverage](#protocol-leverage)).

**Wave 2 — reach, against a now-stable contract:**
4. **PathPilot** (reuse LinuxCNC client) — momentum win, can run in parallel
5. **Fusion importer/exporter** — biggest reach, published schema
6. **Vectric + CAMWorks** (extend the SQLite reader pattern from Mastercam)
7. **Carbide Create CSV** — trivial, large community, interchange-format bonus
8. **Haas** offset file — industrial file-based reach
9. **MachiningCloud GTC** demo polish — showcase catalog ingest
10. Opportunistic: Mach3/4, Okuma THINC, Duet, grblHAL-ATC, SheetCam, HSMAdvisor

### Avoid / defer

- **Avoid:** Mazak (binary + brand collision), Siemens Sinumerik (triple
  license gate), Easel (closed cloud), classic GRBL / UGS / Candle / bCNC /
  CNCjs / Marlin / Klipper (no tool store), Adveon (deprecated), G-Wizard (EOL).
- **Defer (gated or narrow):** Fanuc FOCAS, NX CAM, ESPRIT, BobCAD, PowerMill,
  GibbsCAM, Estlcam, Kiri:Moto, CAMotics, gSender.
