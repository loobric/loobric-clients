# Client Landscape

A survey of software and hardware that produces or consumes CNC **tool data**
— tool geometry, feeds & speeds, tool tables, tool numbers/pockets/offsets,
tool life — and could therefore become a Smooth client (bidirectional sync) or
data source (one-way ingest).

**Status today.** Shipping clients: the reference CLI (`loobric-smooth`),
**FreeCAD CAM**, and **LinuxCNC**. Shipping importers: DIN 4000, STEP P21,
GTC/ISO 13399, SolidCAM, hyperMILL.

> Research compiled 2026-06-29. Ratings are point-in-time; closed/commercial
> systems change their integration surface without notice. Verify the
> highest-stakes facts (a vendor's format, a paywall, a community's activity)
> before committing engineering or recruiting effort.

## The one finding that drives everything

**The leverage is in formats, not vendor APIs.** Almost nothing in this space
exposes a public, writable REST API — every "API" is sales- or partner-gated
and undocumented publicly. But a handful of **open file formats each unlock
several candidates at once**, and the most important ones are SQLite databases
or documented JSON readable with the Python standard library Smooth already
restricts itself to. Build formats, not one-off integrations.

Three format investments cover most of the reachable surface:

1. **Fusion tool-library format** (`.json` / `.tools`, official published
   schema). One importer/exporter serves Fusion (hobby + pro), HSMWorks
   migrants, Harvey/Helical free vendor libraries, HSMAdvisor round-tripping,
   and ProvenCut's export path.
2. **SQLite tool databases.** The same `sqlite3` read pattern handles
   Mastercam `.tooldb`, Vectric `.vtdb`, and CAMWorks `.cwdb` — three heavy
   hitters sharing an open, inspectable container.
3. **MTConnect `CuttingTool` assets.** The only fully open, documented,
   *writable* standard, and the only one carrying live tool-life /
   pot-location / inventory — data ISO 13399 and GTC structurally cannot hold.

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
| **Tormach PathPilot** | Control | Good (it *is* LinuxCNC `tool.tbl`) | Strong | **HIGH** | **Reuse the LinuxCNC client** — cheapest win. Handle reload-on-restart. |
| **Heidenhain TNC** | Control | Good (plaintext `TOOL.T`, incl. tool-life columns) | Moderate (industrial) | **HIGH** | File via free TNCremo/LSV2; no SDK or option needed |
| **Haas NGC** | Control | Partial (`O999999` / Setting-157 offset file) | Strong (PM subforum, r/Haas) | **HIGH** | File over USB/Ethernet; no SDK |
| **Okuma OSP** (THINC) | Control | Good (free, write-capable .NET SDK) | Strong (PM subforum) | **HIGH** | On-machine THINC app → Smooth over network. Verify full-table coverage in the SDK `.chm`. |
| **Mach4** | Control | Partial (Lua API + user-definable custom fields) | Active | High | Lua plugin; custom fields fit Smooth provenance |
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
| **Mazak** (Mazatrol/SMOOTH) | Control | Closed binary | Active (industrial) | **AVOID** | Proprietary binary **and** brand collision (see below) |
| GRBL, UGS, Candle, bCNC, CNCjs, Marlin, Klipper | Ctrl/Sender | None (no persistent tool table) | Large | **Low** | Nothing canonical to sync — GRBL-class hardware re-probes a single runtime TLO per change |

## Tool management, presetters, catalogs, standards

Mostly **data sources** (one-way ingest of nominal geometry) rather than
bidirectional clients. Smooth already ingests GTC/ISO 13399 — the move is to
deepen that, not to chase gated vendor APIs.

| Candidate | Cat | Docs | Role | Desire | Route |
|---|---|---|---|---|---|
| **MachiningCloud** | Catalog | Partial (free GTC/ISO 13399 export) | Data source | **HIGH** | User-exported GTC import — works today, best demo target |
| **MTConnect** Part 4.1 | Standard | Good, open, writable assets | Source + publish | **HIGH** | `CuttingTool` asset client; fills the live tool-life gap |
| **ToolsUnited** (CIMSOURCE) | Catalog | Partial (DIN 4000/13399/GTC) | Data source | High (paywalled) | User GTC export; ToolsUnitedDirect = partnership |
| **HSMAdvisor / FSWizard** | F&S+mgmt | Partial (Fusion JSON + `.hsmlib`) | Bidirectional client | High | File round-trip; living, approachable dev |
| **Sandvik CoroPlus** | Catalog/lib | Partial (ISO 13399/GTC; API partner-gated) | Data source | High | Standard import; partnership for the live API |
| **Kennametal NOVO** | Catalog | Partial (ISO 13399 export; public API is e-commerce only) | Data source | Medium | Standard import (already a Smooth sample source) |
| **Harvey / Helical** | Catalog+F&S | Partial (free Fusion/Mastercam libraries) | Data source | High | Ingest via the Fusion-format importer |
| **Zoller / TDM / WinTool** | Mgmt | Closed (partner-gated WebService) | Peer TMS client | Med-High | Partnership only; GTC exchange where possible |
| **Haimer Microset** | Presetter | Partial (measured offsets out) | Data source | High (as-set geometry) | Per-control post-processor formats |
| **ProvenCut** | F&S | Closed (Fusion-export link) | Data source | Medium | Partnership; high-provenance, low-volume |
| **G-Wizard** | F&S | Partial CSV — EOL (sole dev died 2024) | Migration rescue | Low | One-way CSV import only |
| **Adveon** | Lib | Deprecated | — | **SKIP** | Subsumed by CoroPlus / ISO 13399 |
| **GTC / ISO 13399** | Standard | Good (GTC) / paywalled (13399) | Foundation | High | Already ingested — deepen coverage |

---

## Prioritization

### Sequence by schema-shape risk first, reach second

The dominant cost to minimize is **canonical-schema churn**: a change to the
`canonical` shape fans out to *every* client adapter, so a client that arrives
late and forces such a change reworks all the clients built before it.
Therefore sequence by **schema-shape risk**, not by build difficulty or reach.

Reading `smooth-core/docs/TOOL_SCHEMA.md`, the three-section model with per-field
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
  exports a GTC package → imports to Smooth" path. MachiningCloud's *free* GTC
  export makes it the best demo target today. Don't chase their gated APIs.

- **Two hard "avoid" calls.**
   - **Mazak** — proprietary binary *and* an in-domain brand collision:
     Mazak's control line is branded **"SMOOTH"** with competing "SMOOTH Tool
     Management" products in this exact space. "Smooth for SMOOTH" is
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
and **a Mastercam turning + assembly library** onto the `smooth/contract/`
Pydantic models *on paper*. Every field with no home is a canonical gap. Output:
the list of required canonical additions (tool life, sister tools, wear-offset
model, turning geometry) — found for ~zero build cost, before writing a client
against a still-moving schema.

**Wave 1 — gap-finders (lock the canonical shape):**
1. **Heidenhain `TOOL.T`** — densest gap-finder (wear deltas + tool life +
   sister tools), plaintext, free transfer tool. Build first.
2. **One turning CAM — Mastercam** (open SQLite `.tooldb`, rich, recruitable) —
   validates turning geometry + assembly behavior.
3. **MTConnect asset client** — validates live tool-life/location and the
   writable-asset path.

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
