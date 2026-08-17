# loobric-clients

The client monorepo for **[Loobric](https://github.com/loobric/loobric-server)**
— the application-agnostic REST API and database for synchronizing CNC **tool
data** (geometry, feeds & speeds, tool tables, numbers/pockets/offsets, tool
life) across CAM software, CNC controls, and tool rooms.

One repo, one folder per client — so a brand-new client is an ordinary pull
request, not a request for a new repository. This is also where client work is
planned and tracked: [issues](https://github.com/loobric/loobric-clients/issues)
for build-ready integrations, [discussions](https://github.com/loobric/loobric-clients/discussions)
for ones still being researched.

## Clients in this repo

| Client | What it is | Status |
|---|---|---|
| [`clients/linuxcnc`](clients/linuxcnc) | LinuxCNC tool-table sync — single stdlib file, cron-safe, two-way | 0.7.0, [on PyPI](https://pypi.org/project/loobric-linuxcnc/) |
| [`clients/masso`](clients/masso) | MASSO G3 `.htg` tool table over the controller's USB stick — harvest probed offsets, write the table back | 0.1.0, new |
| [`clients/fusion`](clients/fusion) | Autodesk Fusion `.tools` library sync — batch-fast import, preset promotion, lossless export | 0.1.0, new |

Each folder is self-contained: its own `pyproject.toml`, tests, README, and
CHANGELOG. Install one directly from git with
`pip install "loobric-masso @ git+https://github.com/loobric/loobric-clients#subdirectory=clients/masso"`.

## Clients that live elsewhere (and why)

- [loobric-freecad](https://github.com/loobric/loobric-freecad) — FreeCAD CAM
  workbench addon. Standalone because the FreeCAD Addon Manager installs from a
  repository root.
- [loobric-cli](https://github.com/loobric/loobric-cli) — the reference Python
  client, the `loobric` CLI, the file importers (Vectric, SprutCam, CAMotics,
  DIN 4000, ISO 13399/GTC, SolidCAM, hyperMILL, CSV), and the MCP server.
  Standalone because it is the PyPI-published reference library with its own
  release cadence.

## Adding a new client

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: copy the shape of
`clients/masso`, keep it stdlib-only if it runs near a machine, never guess
identity, and open a PR. The
[compatibility matrix](https://loobric.com/compatibility) shows which
platforms are wanted — every **planned** badge is an open issue with the
format research already done.

## Start here for planning

- **[docs/CLIENT_LANDSCAPE.md](docs/CLIENT_LANDSCAPE.md)** — a survey of ~50
  candidate clients (CAM, CNC controls, tool-management/catalogs) rated on
  format documentation, recruitable community, desirability, and integration
  route, plus the prioritized build plan.

## The strategy in one paragraph

**Sequence by schema-shape risk, not by reach.** The cost to minimize is churn
to the Loobric canonical schema — a change there reworks *every* client adapter.
The canonical model already absorbs most axes (nominal/measured/as-set
geometry, media, and *allows* assemblies). The remaining rework risk lives in a
few **unhooked axes** — tool life, sister/redundant tools, a rich wear-offset
model, and turning geometry. So we build the handful of clients that *force*
those decisions **first** (Heidenhain `TOOL.T`, MTConnect, one turning CAM) to
lock the schema, then roll out the broad-reach clients against a stable
contract. See the landscape doc for the full reasoning and per-candidate
detail.
