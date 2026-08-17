# loobric-masso

Loobric client for **MASSO G3** CNC controllers. MASSO has no network door for
tool data — the controller saves its settings (including the `.htg` tool table)
to a USB stick and loads them back from it. This client reads and writes that
file on the mounted stick:

- **`push`** — harvest the controller's tool table into Loobric: every in-use
  tool becomes an *unbound* tool-table entry with its **probed Z offset** and
  diameter as observed values (`observed:masso@<machine>`). The offsets your
  probing produced stop dying on the USB stick.
- **`write`** — update the tool table from Loobric: names, diameters, and
  slots follow the server; the controller's probed Z offsets are **preserved**
  unless a bound tool carries a server-side Z. A different tool appearing at an
  occupied number keeps the old offset and warns **RE-PROBE**. Machine Settings
  are zipped to `MASSO/loobric-backups/` before every write, and untouched
  records round-trip **byte-exact** — including the controller's own CRC
  variants and the reserved records (T0, T101–T104).
- **`sync`** — push, then write.

Single file, standard library only, Python 3.6+. Server errors never block
anything (cron-safe exit 0); configuration errors exit 2.

## Quick start

```bash
pip install loobric-masso        # or just copy loobric_masso.py
loobric-masso init               # writes ~/.config/loobric/masso.conf — edit it
loobric-masso doctor             # checks config, USB stick, and server
loobric-masso sync
```

On the controller: **F1 Setup > Save & Load Calibration Settings** — *Save to
file* before syncing, *Load from file* + reboot after a `write`.

## The .htg format

Reverse-engineered on the [MASSO community forum (thread 4563)](https://forums.masso.com.au/threads/convert-cam-tool-libraries-into-masso-tool-file.4563/)
and validated by three independent decoders that agree byte-for-byte.
6720 bytes = 105 records × 64 bytes; record 0 is the controller's reserved
dry-run entry, T101–T104 are multi-spindle heads (100 usable tools).

| Offset | Type | Field |
|---|---|---|
| 0–39 | ASCII | Tool name (UI caps at 29 chars) |
| 40 | float32 LE | Z offset |
| 44 | float32 LE | Z wear |
| 48 | float32 LE | Diameter wear |
| 52 | float32 LE | Diameter |
| 56 | byte | Tool direction |
| 57 | int8 | Slot (−1 = manual/unassigned) |
| 60 | uint32 LE | CRC32 of bytes 0–59 |

The controller sometimes writes its own CRC variant; this client preserves the
stored bytes of every record it does not modify, so those survive verbatim.

## License

MIT.
