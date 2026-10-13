import os
import sys
from pathlib import Path

# OpenMP libraries from numpy/OCC/sklearn can collide on Windows and hard-crash
# a spawned worker; allow the duplicate load (must be set before those imports).
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "4")

# ensure the project root is importable in spawned worker processes too
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
