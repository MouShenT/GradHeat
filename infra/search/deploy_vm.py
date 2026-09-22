"""Deploy only GradHeat search helper/resilience settings to the authorized VM."""
import base64
from pathlib import Path
import subprocess

payload=base64.b64encode(Path(__file__).with_name('gradheat_search.py').read_bytes()).decode()
remote=r'''
import base64,datetime,json,os,pathlib,pwd,shutil,subprocess,yaml
base=pathlib.Path('/opt/gradheat')
account=pwd.getpwnam('ms')
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup=base/'backups'/('search-'+stamp)
backup.mkdir(parents=True,exist_ok=False)
os.chmod(backup,0o700)
settings=base/'searxng-config/settings.yml'
shutil.copy2(settings,backup/'settings.yml')
config=yaml.safe_load(settings.read_text())
config.setdefault('outgoing',{})['request_timeout']=12.0
config['outgoing']['max_request_timeout']=20.0
for engine in config.get('engines',[]):
    if engine.get('name') in ['google cse','brave','bing']:
        engine['timeout']=12.0
    if engine.get('name')=='bing':
        engine['disabled']=False
settings.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
os.chown(settings,account.pw_uid,account.pw_gid)
os.chmod(settings,0o600)
target=base/'search/gradheat_search.py'
target.parent.mkdir(exist_ok=True)
if target.exists(): shutil.copy2(target,backup/'gradheat_search.py')
target.write_bytes(base64.b64decode('PAYLOAD'))
os.chmod(target,0o755)
for directory in [base/'evidence',base/'evidence/search']:
    directory.mkdir(exist_ok=True)
    os.chown(directory,account.pw_uid,account.pw_gid)
    os.chmod(directory,0o700)
drop=pathlib.Path('/etc/systemd/system/searxng.service.d/gradheat-resilience.conf')
drop.parent.mkdir(exist_ok=True)
if drop.exists(): shutil.copy2(drop,backup/'gradheat-resilience.conf')
drop.write_text('[Service]\nRestart=on-failure\nRestartSec=5s\nTimeoutStopSec=30s\nUMask=0077\n')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','restart','searxng'],check=True)
subprocess.run(['systemctl','is-active','searxng'],check=True)
print(json.dumps({'backup':str(backup),'helper':str(target),'evidence':str(base/'evidence/search'),'settings':'timeouts 12/20 seconds; bing enabled; original proxy and secrets preserved'}))
'''.replace('PAYLOAD',payload)
result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','ms@192.168.43.150','sudo -n /opt/gradheat/searxng/venv/bin/python -'],input=remote,text=True)
raise SystemExit(result.returncode)
