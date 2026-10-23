#!/usr/bin/env python3
"""Compatibility entry for the installed offline code-plugin builder."""
from __future__ import annotations

import sys

from mathtutor.extensions.developer import build, main as developer_main


def main(argv=None) -> int:
    return developer_main(["build", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    raise SystemExit(main())
