# conftest.py — add fbot/ parent to sys.path so "from fbot.xxx import" works in tests.
import sys
from pathlib import Path

# services/feishu-bot/tests/ → services/feishu-bot/  (parent of fbot/)
_fbot_parent = Path(__file__).resolve().parent.parent
if _fbot_parent.exists() and str(_fbot_parent) not in sys.path:
    sys.path.insert(0, str(_fbot_parent))
