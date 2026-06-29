# smooth-clients

The client-development hub for **[Smooth](https://github.com/loobric/smooth-core)**
— the application-agnostic REST API and database for synchronizing CNC **tool
data** (geometry, feeds & speeds, tool tables, numbers/pockets/offsets, tool
life) across CAM software, CNC controls, and tool rooms.

This repo is where we **plan, prioritize, and track new Smooth clients**. The
shipping clients live in their own repos:

- [smooth-freecad](https://github.com/loobric/smooth-freecad) — FreeCAD CAM
- [smooth-linuxcnc](https://github.com/loobric/smooth-linuxcnc) — LinuxCNC tool table
- [loobric-smooth](https://github.com/loobric/loobric-smooth) — reference Python client (`smooth` CLI) + importers

## Start here

- **[docs/CLIENT_LANDSCAPE.md](docs/CLIENT_LANDSCAPE.md)** — a survey of ~50
  candidate clients (CAM, CNC controls, tool-management/catalogs) rated on
  format documentation, recruitable community, desirability, and integration
  route, plus the prioritized build plan.

## The strategy in one paragraph

**Sequence by schema-shape risk, not by reach.** The cost to minimize is churn
to the Smooth canonical schema — a change there reworks *every* client adapter.
The canonical model already absorbs most axes (nominal/measured/as-set
geometry, media, and *allows* assemblies). The remaining rework risk lives in a
few **unhooked axes** — tool life, sister/redundant tools, a rich wear-offset
model, and turning geometry. So we build the handful of clients that *force*
those decisions **first** (Heidenhain `TOOL.T`, MTConnect, one turning CAM) to
lock the schema, then roll out the broad-reach clients (Fusion, Vectric,
Carbide, Haas, PathPilot, …) against a stable contract. The work is organized
into **Wave 0** (a cheap paper schema-gap spike), **Wave 1** (gap-finders), and
**Wave 2** (reach). See the landscape doc for the full reasoning and the
candidate-by-candidate detail.
