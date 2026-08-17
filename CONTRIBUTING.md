# Contributing a client

A new Loobric client is a pull request adding one folder: `clients/<name>/`.
No repo to request, no org membership needed.

## The folder contract

```
clients/<name>/
  README.md          # what it does, get started, day-to-day usage
  CHANGELOG.md       # semver, per-client
  LICENSE            # MIT (clients are MIT; only the server is AGPL)
  pyproject.toml     # own package name (loobric-<name>), own version
  loobric_<name>.py  # or a package dir — single file preferred for
                     # anything that runs on/near a machine
  tests/             # offline tests: no server, no network
```

Look at [`clients/masso`](clients/masso) for the canonical small example and
[`clients/linuxcnc`](clients/linuxcnc) for the mature one.

## The rules that are not style preferences

These come from the Loobric contract (loobric-server `docs/TOOL_SCHEMA.md`)
and from machines being expensive:

1. **Never block the machine.** A client that runs on or near a controller
   exits 0 on server-unreachable (cron-safe) and 2 on config errors. Standard
   library only for those clients — control boxes run old Pythons and no one
   pip-installs onto them.
2. **Never guess identity.** Tool-table entries are pushed UNBOUND; binding an
   entry to a physical tool record is the server inbox's job or the user's
   explicit act. (v2 decision G2.)
3. **Never write provenance.** Send values through the doors; the server
   stamps `observed:<client>@<machine>` / `asserted:<actor>` itself. A client
   only ever writes its own `clients.<name>` section plus the canonical fields
   the platform legitimately states.
4. **Never invent a value.** A field the source doesn't state stays unknown —
   no "every imported tool is an endmill." Anything untranslatable is counted
   and logged, never guessed. Preserve the full source payload in your client
   section so the import is lossless.
5. **Round-trip byte-exact where the format allows it.** Untouched records in
   a binary or line-oriented format should survive verbatim (see the masso
   codec's raw-bytes pattern, or linuxcnc's line-surgical writes).
6. **Back up before you write.** Timestamped, adjacent to the thing written.

## Workflow

- Check the [issues](https://github.com/loobric/loobric-clients/issues) — a
  **planned** badge on the [compatibility matrix](https://loobric.com/compatibility)
  means the file-format research is already in the issue. Comment to claim it.
- Format still murky? Open or join a
  [discussion](https://github.com/loobric/loobric-clients/discussions) first
  (the **research** badges) — reverse-engineering findings, sample files, and
  node dumps are contributions too.
- Tests must run offline: `python -m pytest clients/<name>/tests/`. CI runs
  each client's tests when its folder changes.
- Releases are per-client tags: `<name>-v<version>` (e.g. `masso-v0.1.0`).
  Maintainers handle PyPI.

## New client verbs live in loobric-cli first

If your client needs a server capability the API lacks, the reference
implementation gets it first: propose it on
[loobric-cli](https://github.com/loobric/loobric-cli), then consume it here.
