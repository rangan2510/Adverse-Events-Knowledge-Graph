#!/usr/bin/env python
"""Stage step 1: download raw data. Thin shim over kg_ae.etl.stage.stage_download."""

import argparse

from kg_ae.etl.stage import stage_download


def main() -> None:
    p = argparse.ArgumentParser(description="Download raw data for staging")
    p.add_argument("--license-tier", default="research", choices=["research", "commercial"])
    p.add_argument("--force", "-f", action="store_true")
    args = p.parse_args()
    stage_download(args.license_tier, force=args.force)


if __name__ == "__main__":
    main()
