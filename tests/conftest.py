import sys
from pathlib import Path

RESTASH_DIR = Path(__file__).resolve().parent.parent / "restash"
if str(RESTASH_DIR) not in sys.path:
    sys.path.insert(0, str(RESTASH_DIR))
