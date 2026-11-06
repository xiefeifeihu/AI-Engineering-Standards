#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module execution entrypoint for python -m tools.standards_sync."""

import sys
from tools.standards_sync.cli import main

if __name__ == "__main__":
    sys.exit(main())
