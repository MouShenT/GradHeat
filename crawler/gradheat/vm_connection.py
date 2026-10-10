"""One VM endpoint, with strict verification of its previously trusted host key."""
import ipaddress
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def ssh_connection(root=ROOT):
    config = json.loads((root / 'contracts/runtime-connections.json').read_text(encoding='utf-8'))
    host = str(ipaddress.ip_address(config['vm_host']))
    alias = str(ipaddress.ip_address(config['host_key_alias']))
    user = config['vm_user']
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*', user):
        raise ValueError('Invalid VM SSH user')
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
        '-o', 'StrictHostKeyChecking=yes', '-o', f'HostKeyAlias={alias}'], f'{user}@{host}'
