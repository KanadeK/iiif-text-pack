import argparse
import json
import sys

from . import __version__
from .core import InputError, collect, load_documents
from .render import write_pack


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export local IIIF v3 supplementing text offline.")
    parser.add_argument("manifest")
    parser.add_argument(
        "--resource", action="append", default=[], help="saved resource JSON; repeatable"
    )
    parser.add_argument(
        "--language", default="en", help="preferred label language (text is not filtered)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", help="new output directory; its parent must exist")
    mode.add_argument("--check", action="store_true", help="report without writing files")
    parser.add_argument(
        "--allow-partial", action="store_true", help="write visibly marked partial output"
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        documents, sources = load_documents([args.manifest, *args.resource])
        report = collect(documents, sources, args.language)
        if args.output and (not report["omissions"] or args.allow_partial):
            write_pack(report, args.output, args.allow_partial)
    except InputError as exc:
        print(f"Input error: {ascii(str(exc))}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "omissions": report["omissions"],
                "written": bool(args.output and (not report["omissions"] or args.allow_partial)),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return int(bool(report["omissions"]))
