#!/usr/bin/env python3
"""
Record the golden English transcript from a directory holding the UNTOUCHED upstream
scripts (laid out as ig-reel/, ig-caption/, ig-human/, ig-viral/).

    python3 -I -B make_golden.py /path/to/pristine > golden/en.json

The pristine scripts are the ones in commit a6fb7a4 of this repository (the import of
Jakeschincariol/instagram-agent-skill, main at d03c56b). Never point this at edited
scripts: the point of the file is to prove that English behaves exactly as upstream.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import en_battery  # noqa: E402

if len(sys.argv) != 2:
    sys.exit(__doc__)
print(json.dumps(en_battery.transcript(sys.argv[1]), indent=1, ensure_ascii=False, sort_keys=True))
