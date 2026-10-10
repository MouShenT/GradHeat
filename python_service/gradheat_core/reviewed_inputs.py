"""Use the frozen, reviewed UI inputs only when their actual bytes still match."""
import hashlib
import json
from pathlib import Path


def read_reviewed_json(root, relative_path):
    root=Path(root).resolve()
    try:
        manifest=json.loads((root/'.research/agent-integration-20261009/dashboard-input-manifest.json').read_text(encoding='utf-8'))
        item=next(x for x in manifest['files'] if x['relative_path']==relative_path)
        path=(root/relative_path).resolve()
        if not path.is_relative_to(root):return None
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:return None
        return json.loads(raw)
    except (OSError,ValueError,KeyError,StopIteration):return None
