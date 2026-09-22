"""Probe official research MCPs; credentials never enter arguments or reports."""
import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import requests

ROOT = Path(__file__).resolve().parents[2]
ENDPOINTS = {
    'exa': ('https://mcp.exa.ai/mcp', 'EXA_API_KEY'),
    'firecrawl': ('https://mcp.firecrawl.dev/v2/mcp', 'FIRECRAWL_API_KEY'),
    'papers': ('https://mcp.firecrawl.dev/v2/mcp-search', 'FIRECRAWL_API_KEY'),
}

def secrets():
    path = ROOT / '.claude/settings.local.json'
    legacy = json.loads(path.read_text(encoding='utf-8-sig')).get('env', {}) if path.exists() else {}
    return {name: os.environ.get(name) or legacy.get(name, '') for _, name in ENDPOINTS.values()}

def redact(value, keys):
    if isinstance(value, str):
        for key in keys.values():
            if key:
                value = value.replace(key, '[REDACTED]')
        return value
    if isinstance(value, list):
        return [redact(v, keys) for v in value]
    if isinstance(value, dict):
        return {k: redact(v, keys) for k, v in value.items()}
    return value

def rpc(session, url, payload):
    response = session.post(url, json=payload, timeout=(10, 90))
    response.raise_for_status()
    response.encoding = 'utf-8'  # SSE and JSON are UTF-8; Latin-1 breaks CJK lines.
    if response.headers.get('mcp-session-id'):
        session.headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
    if not response.content or 'id' not in payload:
        return {}
    if 'text/event-stream' in response.headers.get('Content-Type', ''):
        # MCP JSON-RPC responses are delivered as data events; ignore notifications.
        for event in response.text.replace('\r\n', '\n').split('\n\n'):
            data = '\n'.join(line[5:].lstrip() for line in event.splitlines() if line.startswith('data:'))
            if data and data != '[DONE]':
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if parsed.get('id') == payload['id']:
                    return parsed
        try:
            parsed = json.loads(response.text)
            if parsed.get('id') == payload['id']:
                return parsed
        except json.JSONDecodeError:
            pass
        raise ValueError('No matching JSON-RPC response: ' + response.text[:800])
    return response.json()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('provider', choices=ENDPOINTS)
    parser.add_argument('--tool')
    parser.add_argument('--anonymous', action='store_true')
    parser.add_argument('--args-file', type=Path)
    args = parser.parse_args()
    keys = secrets()
    url, key_name = ENDPOINTS[args.provider]
    session = requests.Session()
    session.headers.update({'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'})
    if keys[key_name] and not args.anonymous:
        session.headers['Authorization'] = 'Bearer ' + keys[key_name]
    report = {'provider': args.provider, 'checked_at': datetime.now(timezone.utc).isoformat()}
    try:
        init = rpc(session, url, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'gradheat-check', 'version': '1.0'}}})
        if 'error' in init:
            raise ValueError('MCP initialize rejected')
        session.headers['MCP-Protocol-Version'] = init['result']['protocolVersion']
        rpc(session, url, {'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        listing = rpc(session, url, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
        report['tools'] = listing.get('result', {}).get('tools', [])
        if not report['tools']:
            raise ValueError('No tools returned')
        if args.tool:
            arguments = json.loads(args.args_file.read_text(encoding='utf-8-sig')) if args.args_file else {}
            result = rpc(session, url, {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': args.tool, 'arguments': arguments}})
            report['call'] = result
            report['status'] = 'tool_error' if 'error' in result or result.get('result', {}).get('isError') else 'query_returned'
        else:
            report['status'] = 'initialized'
    except Exception as exc:
        report['status'] = 'failed'
        report['error_type'] = type(exc).__name__
        report['error_detail'] = redact(str(exc)[:900], keys)
        if isinstance(exc, requests.HTTPError):
            report['http_status'] = exc.response.status_code
    output = ROOT / '.research'
    output.mkdir(exist_ok=True)
    suffix = args.tool or 'tools'
    target = output / f'{args.provider}-{suffix}.json'
    target.write_text(json.dumps(redact(report, keys), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('call', 'tools')}, ensure_ascii=True))
    print('tools:', ', '.join(t['name'] for t in report.get('tools', [])))
    print('report:', target)
    return 1 if report['status'] in ('failed', 'tool_error') else 0

if __name__ == '__main__':
    raise SystemExit(main())
