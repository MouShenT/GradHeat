"""Temporary SSH forwarding to the observed GradHeat MySQL container address."""
from contextlib import contextmanager
import ipaddress,os,socket,subprocess,time
from pathlib import Path
import pymysql
from .db import _load_env
from .vm_connection import ssh_connection

@contextmanager
def connect_vm(log_dir: Path):
    log_dir.mkdir(parents=True,exist_ok=True)
    ssh,target=ssh_connection()
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    observed=subprocess.run(ssh+[target,"sudo -n docker inspect gradheat-mysql --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'"],capture_output=True,text=True,timeout=15,check=True,creationflags=flags)
    address=str(ipaddress.ip_address(observed.stdout.strip()))
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    cfg=_load_env()
    if not cfg.get('GRADHEAT_DB_PASSWORD'):raise RuntimeError('Missing existing private database credential')
    connection=None
    with (log_dir/'ssh-forward.log').open('ab') as log:
        process=subprocess.Popen(ssh+['-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-N','-L',f'127.0.0.1:{port}:{address}:3306',target],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=log,creationflags=flags)
        try:
            for _ in range(40):
                if process.poll() is not None:raise RuntimeError('SSH forwarding failed; see private ssh-forward.log')
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.2):break
                except OSError:time.sleep(.2)
            else:raise TimeoutError('SSH forwarding startup timed out')
            connection=pymysql.connect(host='127.0.0.1',port=port,user=cfg.get('GRADHEAT_DB_USER','gradheat'),password=cfg['GRADHEAT_DB_PASSWORD'],database=cfg.get('GRADHEAT_DB_NAME','gradheat'),charset='utf8mb4',autocommit=False,connect_timeout=8,read_timeout=60,write_timeout=60)
            yield connection
        finally:
            if connection:connection.close()
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
