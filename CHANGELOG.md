# Changelog

All notable changes to **loobric-masso** are recorded here. This project
adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-08-17

### Added
- Initial release (loobric-clients #20, #21): `.htg` codec (byte-exact
  round-trip of untouched records, including the controller's CRC variants
  and the reserved T0/T101–T104 records), USB-stick discovery of the
  firmware-version-dependent tool-table filename under
  `MASSO/Machine Settings/`, timestamped settings backup before every
  write, and the `init` / `doctor` / `push` / `write` / `sync` verbs.
  `push` snapshots the table as unbound entries carrying the probed Z
  offsets as observed values; `write` merges server entries into the
  table, preserving probed Z for unbound tools and warning RE-PROBE when
  a different tool lands on an occupied number. Codec cross-validated
  against two independent community decoders of the format.
