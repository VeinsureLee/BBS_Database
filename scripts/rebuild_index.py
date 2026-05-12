"""CLI entry point: rebuild index.db."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bbs_database.builder.pipeline import build_index  # noqa: E402
from bbs_database.config import load_config  # noqa: E402

try:
    from dotenv import load_dotenv  # noqa: E402
    load_dotenv()
except ImportError:
    pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rebuild BBS_Database index.db")
    parser.add_argument("--full", action="store_true",
                        help="Drop and rebuild from scratch (P1+P2 default).")
    parser.add_argument("--incremental", action="store_true", help="Reserved for P3.")
    parser.add_argument("--boards", help="Reserved for P3.")
    parser.add_argument("--no-embed", action="store_true",
                        help="Skip vector embedding phases (classical only).")
    parser.add_argument(
        "--config",
        default=str((HERE.parent / "config" / "routing.yaml").resolve()),
        help="Path to routing.yaml",
    )
    args = parser.parse_args(argv)

    if args.incremental or args.boards:
        print("--incremental / --boards is not yet supported in P1.", file=sys.stderr)
        return 2

    cfg_path = Path(args.config).resolve()
    cfg = load_config(cfg_path, root=cfg_path.parent.parent)
    if args.no_embed:
        # Override cfg.embed.enabled = False
        from dataclasses import replace
        cfg = replace(cfg, embed=replace(cfg.embed, enabled=False))
        print("building index (classical only, --no-embed) →", cfg.index_db_path)
    else:
        print("building index →", cfg.index_db_path)
    build_index(cfg)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
