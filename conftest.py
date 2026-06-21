"""Root conftest.

Its mere presence makes this directory pytest's rootdir, so the top-level
packages (game, config, models, ...) are importable from tests without any
install step or PYTHONPATH fiddling.
"""

import os
import sys

# Belt-and-suspenders: ensure the project root is importable for both
# `pytest` and `python scripts/...` invocations.
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
