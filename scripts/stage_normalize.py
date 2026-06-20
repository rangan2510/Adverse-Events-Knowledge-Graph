#!/usr/bin/env python
"""Stage step 2: parse + normalize to silver. Thin shim over kg_ae.etl.stage.stage_normalize."""

import argparse

from kg_ae.etl.stage import stage_normalize


def main() -> None:
    p = argparse.ArgumentParser(description="Parse + normalize raw data into silver Parquet")
    p.add_argument("--license-tier", default="research", choices=["research", "commercial"])
    p.add_argument("--force", "-f", action="store_true")
    args = p.parse_args()
    stage_normalize(args.license_tier, force=args.force)


if __name__ == "__main__":
    main()
