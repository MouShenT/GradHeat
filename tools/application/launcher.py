"""Run the local Java/Vue + Python app against an already trusted VM.

No collection job is scheduled by default. Own children are cleaned up on exit.
Credentials travel in child environments; runtime metadata never contains them.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'crawler'))
from gradheat.vm_connection import ssh_connection

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def env_file(path):
    return dict(line.strip().split('=', 1) for line in path.read_text(encoding='utf-8').splitlines()
                if line.strip() and not line.lstrip().startswith('#') and '=' in line)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def check_port(port):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))


@contextmanager
def exclusive_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'run.lock').open('a+b') as stream:
        stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def start(args, children, log, env=None):
    process = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
        stdout=log, stderr=log, creationflags=FLAGS)
    children.append(process)
    return process


def wait_http(url, processes, token=None, timeout=65, request_timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError('Application child exited; inspect private.log locally')
        try:
            request = urllib.request.Request(url, headers={'X-GradHeat-Internal-Token': token} if token else {})
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                if response.status == 200:
                    return json.load(response)
        except (OSError, ValueError, urllib.error.URLError):
            time.sleep(.5)
    raise TimeoutError('Application readiness timeout; inspect private.log locally')


def run(args):
    jar = Path(args.jar).resolve() if args.jar else ROOT / 'backend/target/gradheat-backend-0.1.0.jar'
    if not jar.is_file() or not (ROOT/'frontend/dist/index.html').is_file():
        raise ValueError('Build first: tools/build-application.ps1')
    java = args.java or shutil.which('java')
    if not java:
        raise ValueError('Java 21+ is required')
    if args.java_port == args.python_port:
        raise ValueError('Java and Python need distinct ports')
    check_port(args.java_port); check_port(args.python_port)
    private = env_file(ROOT/'infra/docker/.env')
    required = ('MYSQL_USER','MYSQL_PASSWORD','MYSQL_DATABASE','REDIS_PASSWORD','RABBITMQ_USER','RABBITMQ_PASSWORD')
    if any(not private.get(key) for key in required):
        raise ValueError('Existing private infrastructure credentials are required')
    folder = ROOT/'.research'/('application-runtime' if args.java_port == 18729 else f'application-runtime-{args.java_port}')
    children = []
    with exclusive_lock(folder), (folder/'private.log').open('ab') as log:
        runtime = {'state':'starting','pid':os.getpid(),'url':f'http://127.0.0.1:{args.java_port}/',
            'java_port':args.java_port,'python_port':args.python_port,'worker_queues':[] if args.no_worker else ['analyse.long','collect.autonomous.win-primary']}
        pointer = folder/'runtime.json'
        def save():
            temp = folder/'runtime.tmp';temp.write_text(json.dumps(runtime),encoding='utf-8');temp.replace(pointer)
        save()
        try:
            ssh, target = ssh_connection()
            addresses = {}
            import ipaddress
            for name in ('mysql','redis','rabbitmq'):
                observed = subprocess.run(ssh+[target,"sudo -n docker inspect gradheat-"+name+" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'"],
                    capture_output=True,text=True,timeout=15,check=True,creationflags=FLAGS)
                addresses[name] = str(ipaddress.ip_address(observed.stdout.strip()))
            ports = {name:free_port() for name in addresses}
            forward = ssh+['-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-N']
            for name,remote_port in [('mysql',3306),('redis',6379),('rabbitmq',5672)]:
                forward += ['-L',f'127.0.0.1:{ports[name]}:{addresses[name]}:{remote_port}']
            tunnel = start(forward+[target],children,log)
            for n in range(40):
                if tunnel.poll() is not None:
                    raise RuntimeError('Trusted SSH forwarding failed')
                try:
                    for port in ports.values():
                        with socket.create_connection(('127.0.0.1',port),timeout=.2): pass
                    break
                except OSError:
                    time.sleep(.2)
            else:
                raise TimeoutError('SSH forward startup failed')
            token = secrets.token_hex(32)
            common = dict(os.environ)
            common.update(GRADHEAT_ROOT=str(ROOT),GRADHEAT_INTERNAL_TOKEN=token,
                PYTHONPATH=str(ROOT/'python_service'),PYTHONUTF8='1',
                GRADHEAT_DB_MODE='direct',GRADHEAT_DB_HOST='127.0.0.1',GRADHEAT_DB_PORT=str(ports['mysql']),
                GRADHEAT_DB_USER=private['MYSQL_USER'],GRADHEAT_DB_PASSWORD=private['MYSQL_PASSWORD'],
                GRADHEAT_DB_NAME=private['MYSQL_DATABASE'])
            python_env=dict(common,GRADHEAT_BIND_HOST='127.0.0.1',GRADHEAT_PYTHON_PORT=str(args.python_port))
            api = start([sys.executable,'-X','utf8','-B','-m','gradheat_python.api'],children,log,python_env)
            ready = wait_http(f'http://127.0.0.1:{args.python_port}/internal/v1/ready',[tunnel,api],token,
                              timeout=args.startup_timeout,request_timeout=args.startup_request_timeout)
            java_env=dict(common,GRADHEAT_JAVA_PORT=str(args.java_port),GRADHEAT_BIND_ADDRESS='127.0.0.1',
                GRADHEAT_MYSQL_URL=f"jdbc:mysql://127.0.0.1:{ports['mysql']}/{private['MYSQL_DATABASE']}?connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true&characterEncoding=UTF-8",
                GRADHEAT_MYSQL_USER=private['MYSQL_USER'],GRADHEAT_MYSQL_PASSWORD=private['MYSQL_PASSWORD'],
                GRADHEAT_REDIS_HOST='127.0.0.1',GRADHEAT_REDIS_PORT=str(ports['redis']),GRADHEAT_REDIS_PASSWORD=private['REDIS_PASSWORD'],
                GRADHEAT_REDIS_ENABLED='true',GRADHEAT_RABBIT_HOST='127.0.0.1',GRADHEAT_RABBIT_PORT=str(ports['rabbitmq']),
                GRADHEAT_RABBIT_USER=private['RABBITMQ_USER'],GRADHEAT_RABBIT_PASSWORD=private['RABBITMQ_PASSWORD'],
                GRADHEAT_RABBIT_VHOST='/gradheat',GRADHEAT_MESSAGING_ENABLED='true',
                GRADHEAT_PYTHON_URL=f'http://127.0.0.1:{args.python_port}',GRADHEAT_PUBLIC_WRITE_ENABLED='true')
            business = start([java,'-jar',str(jar)],children,log,java_env)
            wait_http(f'http://127.0.0.1:{args.java_port}/api/v1/admissions',[tunnel,api,business],
                      timeout=args.startup_timeout,request_timeout=args.startup_request_timeout)
            if not args.no_worker:
                quote = urllib.parse.quote
                worker_env=dict(common,GRADHEAT_WORKER_ID='local-analysis',GRADHEAT_WORKER_QUEUES='analyse.long',
                    GRADHEAT_RABBIT_URL=f"amqp://{quote(private['RABBITMQ_USER'],safe='')}:{quote(private['RABBITMQ_PASSWORD'],safe='')}@127.0.0.1:{ports['rabbitmq']}/%2Fgradheat")
                start([sys.executable,'-X','utf8','-B','-m','gradheat_python.worker'],children,log,worker_env)
                collector_env=dict(worker_env,GRADHEAT_WORKER_ID='win-primary',GRADHEAT_WORKER_QUEUES='collect.autonomous.win-primary')
                start([sys.executable,'-X','utf8','-B','-m','gradheat_python.worker'],children,log,collector_env)
            runtime.update(state='ready',data_version=ready['data_version'],child_pids=[p.pid for p in children])
            save()
            print(json.dumps({'state':'ready','url':runtime['url'],'worker_queues':runtime['worker_queues']},ensure_ascii=False),flush=True)
            end = time.monotonic()+args.run_seconds if args.run_seconds else None
            while (end is None or time.monotonic()<end) and not (args.stop_file and Path(args.stop_file).exists()):
                if any(p.poll() is not None for p in children):
                    raise RuntimeError('Application child exited; inspect private.log locally')
                time.sleep(.5)
        finally:
            for process in reversed(children):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=6)
                    except subprocess.TimeoutExpired: process.kill();process.wait(timeout=6)
            runtime.update(state='stopped',child_pids=[]);save()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--java',help='Java executable; otherwise locate it on PATH')
    parser.add_argument('--jar',help='Alternate verified build to run beside an active collector')
    parser.add_argument('--java-port',type=int,default=18729)
    parser.add_argument('--python-port',type=int,default=18730)
    parser.add_argument('--no-worker',action='store_true',help='Only run public Java/UI and internal Python API')
    parser.add_argument('--stop-file',help='Graceful shutdown marker for the independent development supervisor')
    parser.add_argument('--startup-timeout',type=int,default=65,help='Readiness budget per service, including cold JVM startup')
    parser.add_argument('--startup-request-timeout',type=int,default=3,help='Individual readiness HTTP request timeout')
    parser.add_argument('--run-seconds',type=int,default=0,help='Bounded acceptance lifetime; zero stays foreground until Ctrl+C')
    args=parser.parse_args()
    if (not all(1024<=port<=65535 for port in (args.java_port,args.python_port)) or args.run_seconds<0
            or not 5<=args.startup_timeout<=600 or not 1<=args.startup_request_timeout<=60):
        parser.error('Invalid local port or lifetime')
    try: run(args)
    except KeyboardInterrupt: pass
    except Exception as error:
        # Avoid a child exception carrying private credentials into user-visible output.
        print('Application launch failed: '+type(error).__name__+'; inspect local private.log/configuration.',file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__': main()
