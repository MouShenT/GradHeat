"""Atomic private runtime receipts resilient to short Windows reader locks."""
import json
from pathlib import Path
import time
import uuid


def write_runtime(pointer, value):
    pointer = Path(pointer)
    temporary = pointer.with_name(pointer.name + '-' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        for attempt in range(20):
            try:
                temporary.replace(pointer)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(.05)
    finally:
        temporary.unlink(missing_ok=True)
