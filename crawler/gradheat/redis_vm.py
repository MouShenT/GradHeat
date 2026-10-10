"""Private, short-lived SSH connection to the existing GradHeat Redis."""
from contextlib import contextmanager
import ipaddress,json,os,socket,subprocess,time
from pathlib import Path
import redis
from .vm_connection import ssh_connection


@contextmanager
def connect_redis(log_dir: Path):
    ssh,target=ssh_connection()
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    inspect=subprocess.run(ssh+[target,'sudo -n docker inspect gradheat-redis'],capture_output=True,text=True,timeout=15,check=True,creationflags=flags)
    config=json.loads(inspect.stdout)[0]
    address=str(ipaddress.ip_address(config['NetworkSettings']['Networks']['gradheat-net']['IPAddress']))
    env=dict(x.split('=',1) for x in config['Config']['Env'] if '=' in x)
    password=env.get('REDIS_PASSWORD')
    if not password: raise RuntimeError('Private Redis credential unavailable')
    with socket.socket() as s: s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    log_dir.mkdir(parents=True,exist_ok=True)
    with (log_dir/'redis-forward.log').open('ab') as log:
        process=subprocess.Popen(ssh+['-o','ExitOnForwardFailure=yes','-N','-L',f'127.0.0.1:{port}:{address}:6379',target],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=log,creationflags=flags)
        client=None
        try:
            for _ in range(40):
                if process.poll() is not None: raise RuntimeError('Redis forwarding failed')
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.2): break
                except OSError: time.sleep(.2)
            else: raise TimeoutError('Redis forwarding timed out')
            client=redis.Redis(host='127.0.0.1',port=port,password=password,decode_responses=True,socket_connect_timeout=5,socket_timeout=5,retry_on_timeout=False)
            client.ping()
            yield client
        finally:
            if client: client.close()
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
