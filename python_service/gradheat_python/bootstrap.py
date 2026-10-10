from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for folder in (ROOT / 'python_service', ROOT / 'crawler'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
