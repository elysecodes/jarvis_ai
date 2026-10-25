"""
Pytest bootstrap.

Having a conftest.py in the project root makes Python treat this folder as the
import root, so tests can simply do `import config` and `from modules import ...`.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
