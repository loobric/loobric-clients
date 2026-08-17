# MIT License
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: MIT

"""The ``loobric-fusion`` command.

    loobric-fusion import LIBRARY.tools [--dry-run]
    loobric-fusion export LIBRARY.tools [--all]
    loobric-fusion doctor

Connection: ``--url``/``--api-key`` beat ``$LOOBRIC_BASE_URL``/
``$LOOBRIC_API_KEY``. A ``cam``-preset key (read+sync+assert) is the right
key: it can contribute and replace its own presets but never delete
anyone's. Exit codes: 0 success, 1 server/network failure, 2 usage error.
"""
import argparse
import os
import sys

from . import CLIENT_NAME, CLIENT_VERSION, sync, toolsfile


def _log(msg):
    # flush=True: progress must reach a redirected log file as it happens,
    # not sit in a block buffer that a killed run loses.
    print(msg, flush=True)


def _client(args):
    import loobric.transport
    from loobric import Client
    # Cloudflare rejects default Python UAs in front of api.loobric.com, and
    # the server should see WHICH client is talking.
    loobric.transport.USER_AGENT = "loobric-fusion/%s" % CLIENT_VERSION
    base_url = args.url or os.environ.get("LOOBRIC_BASE_URL")
    api_key = args.api_key or os.environ.get("LOOBRIC_API_KEY")
    if not base_url:
        raise SystemExit(
            "no server: pass --url or set LOOBRIC_BASE_URL "
            "(e.g. https://api.loobric.com)")
    return Client(base_url=base_url, api_key=api_key)


def cmd_import(args):
    doc = toolsfile.load(args.file)
    client = _client(args)
    state = sync.load_state()
    summary = sync.import_file(client, doc, state, log=_log,
                               dry_run=args.dry_run,
                               set_name=getattr(args, "set_name", None),
                               workers=getattr(args, "workers", 8))
    if not args.dry_run:
        sync.save_state(state)
    presets = summary["presets"]
    errors = summary.get("errors", 0)
    print("import%s: %d created, %d updated, %d unchanged, %d skipped%s | "
          "presets: %d promoted, %d skipped, %d pruned, %d blocked"
          % (" (dry run)" if args.dry_run else "", summary["created"],
             summary["updated"], summary["unchanged"], summary["skipped"],
             (", %d errors" % errors) if errors else "",
             presets["promoted"], presets["skipped"], presets["pruned"],
             presets["blocked"]))
    return 1 if errors else 0
    return 0


def cmd_export(args):
    client = _client(args)
    state = sync.load_state()
    doc, summary = sync.export_records(client, state,
                                       include_all=args.all, log=_log)
    toolsfile.save(doc, args.file)
    sync.save_state(state)
    print("export: %d regenerated, %d synthesized, %d skipped -> %s"
          % (summary["exported"], summary["synthesized"],
             summary["skipped"], args.file))
    if summary["synthesized"]:
        print("note: synthesized tools are best-effort — check them after "
              "importing into Fusion")
    return 0


def cmd_doctor(args):
    client = _client(args)
    version = client.server_version()
    print("server: %s (version %s)"
          % (args.url or os.environ.get("LOOBRIC_BASE_URL"),
             version.get("version", "?")))
    try:
        info = client.key_info()
        print("key: %s scopes=%s"
              % (info.get("name", "?"), ",".join(info.get("scopes") or [])))
    except Exception:
        print("key: none (solo mode or session auth)")
    print("client: loobric-fusion %s (as '%s')"
          % (CLIENT_VERSION, CLIENT_NAME))
    print("state: %s" % sync.state_path())
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="loobric-fusion",
        description="Sync Fusion tool libraries with a Loobric server.")
    parser.add_argument("--version", action="version",
                        version="loobric-fusion %s" % CLIENT_VERSION)
    parser.add_argument("--url", help="server URL (or $LOOBRIC_BASE_URL)")
    parser.add_argument("--api-key", help="API key (or $LOOBRIC_API_KEY)")
    commands = parser.add_subparsers(dest="command", required=True)

    p_import = commands.add_parser(
        "import", help="Fusion library file -> server")
    p_import.add_argument("file", help=".tools or tools.json file")
    p_import.add_argument("--dry-run", action="store_true",
                          help="report what would change, write nothing")
    p_import.add_argument("--set", dest="set_name", metavar="NAME",
                          help="gather the imported tools into this ToolSet "
                               "(created if missing; additive)")
    p_import.add_argument("--workers", type=int, default=8,
                          help="parallel upload workers (default 8)")
    p_import.set_defaults(func=cmd_import)

    p_export = commands.add_parser(
        "export", help="server -> Fusion library file")
    p_export.add_argument("file", help=".tools or .json path to write")
    p_export.add_argument("--all", action="store_true",
                          help="also synthesize tools from records other "
                               "clients created (experimental)")
    p_export.set_defaults(func=cmd_export)

    p_doctor = commands.add_parser(
        "doctor", help="check server, key and local state")
    p_doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except toolsfile.ToolsFileError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SystemExit:
        raise
    except Exception as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
