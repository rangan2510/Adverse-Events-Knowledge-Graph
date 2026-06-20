#!/usr/bin/env python
"""Stage step 3: build + validate the JSON graph. Thin shim over kg_ae.etl.stage.stage_build."""

from kg_ae.etl.stage import stage_build


def main() -> None:
    stage_build()


if __name__ == "__main__":
    main()
