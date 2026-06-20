#!/usr/bin/env python
"""Stage step 4: canary QA on the built graph. Exits non-zero on failure.

Thin shim over kg_ae.etl.stage.stage_verify; used as the ship gate.
"""

import sys

from kg_ae.etl.stage import stage_verify


def main() -> None:
    sys.exit(0 if stage_verify() else 1)


if __name__ == "__main__":
    main()
