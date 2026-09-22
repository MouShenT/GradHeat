"""Install reviewed local Codex MCP configuration and project research skill."""
import json
import shutil
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
codex_home = Path.home() / '.codex'
path = codex_home / 'config.toml'
text = path.read_text(encoding='utf-8-sig') if path.exists() else ''
existing = tomllib.loads(text)
keys = json.loads((ROOT / '.claude/settings.local.json').read_text(encoding='utf-8-sig')).get('env', {})
key = keys.get('FIRECRAWL_API_KEY')
if not key:
    raise SystemExit('Missing existing Firecrawl credential; no configuration changed.')
targets = {'gradheat_exa', 'gradheat_firecrawl'}
if targets.intersection(existing.get('mcp_servers', {})):
    raise SystemExit('GradHeat entries already exist; review before updating.')
skill_target = codex_home / 'skills' / 'gradheat-research'
if skill_target.exists():
    raise SystemExit('Skill already exists; review before updating.')
addition = '''

# GradHeat: official search services, installed 2026-09-22.
[mcp_servers.gradheat_exa]
url = "https://mcp.exa.ai/mcp"
enabled_tools = ["web_search_exa", "web_fetch_exa"]
startup_timeout_sec = 30
tool_timeout_sec = 120

[mcp_servers.gradheat_firecrawl]
url = "https://mcp.firecrawl.dev/v2/mcp"
enabled_tools = ["firecrawl_search", "firecrawl_scrape", "firecrawl_map", "firecrawl_research_search_papers", "firecrawl_research_inspect_paper", "firecrawl_research_related_papers", "firecrawl_research_read_paper", "firecrawl_developer_search", "firecrawl_credit_usage"]
startup_timeout_sec = 30
tool_timeout_sec = 120
http_headers = { Authorization = TOKEN }
'''.replace('TOKEN', json.dumps('Bearer ' + key))
combined = text + addition
tomllib.loads(combined)
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
if path.exists():
    shutil.copy2(path, path.with_name('config.toml.before-gradheat-' + stamp))
shutil.copytree(Path(__file__).parent / 'gradheat-research', skill_target)
path.write_text(combined, encoding='utf-8')
print('Installed: gradheat_exa (anonymous; legacy key invalid), gradheat_firecrawl, gradheat-research skill.')
print('Existing MCP settings preserved. Reload MCP servers / next turn to discover the skill.')
