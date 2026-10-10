"""Persistent Vite + API development service, owned by Windows rather than Codex.

Run through tools/start-frontend.ps1. Each component owns an anonymous Windows
job so a crash or shutdown also cleans up its SSH/API descendants. No collectors
are launched here. Credentials remain in the existing backend launcher.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

from launcher import ROOT, FLAGS, exclusive_lock


class WindowsJob:
    def __init__(self):
        self.handle = None
        if os.name != 'nt':
            return

        class Limits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
                        ('max_working_set', ctypes.c_size_t), ('active_processes', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('read_operations', 'write_operations', 'other_operations', 'read_bytes', 'write_bytes', 'other_bytes')]

        class Extended(ctypes.Structure):
            _fields_ = [('limits', Limits), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process_memory', ctypes.c_size_t),
                        ('peak_job_memory', ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.limits.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            code = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(code)

    def attach(self, process):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def start(command, log, cwd, env=None):
    job = WindowsJob()
    process = None
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, creationflags=FLAGS)
        job.attach(process)
        return process, job
    except BaseException:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        job.close()
        raise


def stop(component, marker=None):
    if component is None:
        return
    process, job = component
    try:
        if marker is not None and process.poll() is None:
            marker.touch()
            try:
                process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                process.terminate()
        elif process.poll() is None:
            process.terminate()
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    finally:
        job.close()
        process.wait(timeout=10)


def reachable(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def save(folder, value):
    value['updated_at'] = datetime.now(timezone.utc).isoformat()
    temporary = folder / 'runtime.tmp'
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(folder / 'runtime.json')


def run(config):
    folder = Path(config['runtime_dir'])
    stop_file, backend_stop = folder / 'stop', folder / 'backend.stop'
    loaded_source = hashlib.sha256(Path(__file__).read_bytes()).digest()
    with exclusive_lock(folder), (folder / 'service.log').open('ab', buffering=0) as log:
        # A task starts after the control script clears the stop marker.
        if stop_file.exists():
            return
        backend_stop.unlink(missing_ok=True)
        components = {'frontend': None, 'backend': None}
        attempts = dict.fromkeys(components, 0)
        retry_at = dict.fromkeys(components, 0.0)
        metadata = dict(state='starting', pid=os.getpid(), manager='Windows Task Scheduler',
                        task_name=config['task_name'], url='http://127.0.0.1:5173/',
                        backend_url='http://127.0.0.1:18731/', components={})
        browser_opened = False
        sync_component = None
        next_sync = time.monotonic() + 60
        observed_request = None
        frontend_env = dict(os.environ, GRADHEAT_DEV_API_URL=metadata['backend_url'].rstrip('/'))
        # pythonw owns the supervisor; the launcher needs python.exe for useful logs.
        commands = {
            'frontend': [config['node'], str(ROOT / 'frontend/node_modules/vite/bin/vite.js')],
            'backend': [config['python'], '-X', 'utf8', '-B', str(ROOT / 'tools/application/launcher.py'),
                        '--java', config['java'], '--jar', config['jar'], '--java-port', '18731',
                        '--python-port', '18732', '--no-worker', '--stop-file', str(backend_stop)],
        }
        commands['backend'] += ['--startup-timeout', '180', '--startup-request-timeout', '15']
        backend_runtime = ROOT / '.research/application-runtime-18731/runtime.json'
        try:
            while not stop_file.exists():
                for name, marker in [('frontend', folder/'frontend.restart'), ('backend', folder/'backend.restart')]:
                    if marker.exists():
                        stop(components[name], backend_stop if name == 'backend' else None)
                        components[name] = None
                        retry_at[name] = 0
                        marker.unlink(missing_ok=True)
                for name, component in list(components.items()):
                    if component is not None and component[0].poll() is not None:
                        code = component[0].returncode
                        stop(component)
                        components[name] = None
                        attempts[name] += 1
                        retry_at[name] = time.monotonic() + min(60, 2 ** min(attempts[name], 6))
                        metadata['components'][name] = dict(state='retrying', exit_code=code)
                    if components[name] is None and time.monotonic() >= retry_at[name]:
                        if name == 'backend':
                            backend_stop.unlink(missing_ok=True)
                            build_pointer = folder/'backend-build.json'
                            if build_pointer.is_file():
                                build = json.loads(build_pointer.read_text(encoding='utf-8'))
                                jar = Path(build['jar']).resolve()
                                if not jar.is_file() or jar.suffix != '.jar':
                                    raise ValueError('Verified backend build is missing')
                                if hashlib.sha256(jar.read_bytes()).hexdigest() != build['jar_sha256']:
                                    raise ValueError('Verified backend build changed')
                                commands[name][commands[name].index('--jar')+1] = str(jar)
                                metadata['backend_source_sha'] = build['source_sha']
                        components[name] = start(commands[name], log,
                                                 ROOT / 'frontend' if name == 'frontend' else ROOT,
                                                 frontend_env if name == 'frontend' else None)
                        metadata['components'][name] = dict(state='starting', pid=components[name][0].pid)
                front_ready = (components['frontend'] is not None and components['frontend'][0].poll() is None
                               and reachable(metadata['url'] + '@vite/client'))
                try:
                    api_state = json.loads(backend_runtime.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    api_state = {}
                back_ready = (components['backend'] is not None and components['backend'][0].poll() is None
                              and api_state.get('state') == 'ready' and api_state.get('pid') == components['backend'][0].pid
                              and reachable(metadata['backend_url'] + 'api/v1/admissions'))
                for name, ready in [('frontend', front_ready), ('backend', back_ready)]:
                    if components[name] is not None and ready:
                        metadata['components'][name]['state'] = 'ready'
                        attempts[name] = 0
                metadata['state'] = 'ready' if front_ready and back_ready else 'starting'
                save(folder, metadata)
                if front_ready and back_ready and config.get('open_browser') and not browser_opened:
                    webbrowser.open(metadata['url'], new=2)
                    browser_opened = True
                if sync_component is not None and sync_component[0].poll() is not None:
                    stop(sync_component)
                    sync_component = None
                    next_sync = time.monotonic() + max(60, int(config.get('sync_interval_seconds', 900)))
                if sync_component is None and hashlib.sha256(Path(__file__).read_bytes()).digest() != loaded_source:
                    # Scheduler restarts a changed manager after its update finishes.
                    raise RuntimeError('Development manager source updated')
                request = ROOT/'.research/repo-sync/deploy-request'
                if request.is_file():
                    pending = request.read_text(encoding='utf-8').strip()
                    if pending != observed_request:
                        observed_request = pending
                        next_sync = time.monotonic()
                if config.get('repository_sync') and sync_component is None and front_ready and back_ready and time.monotonic() >= next_sync:
                    sync_component = start([config['python'], '-X', 'utf8', '-B',
                                            str(ROOT/'tools/release/sync_repository.py'), 'pull', '--deploy'], log, ROOT)
                for _ in range(10):
                    if stop_file.exists():
                        break
                    time.sleep(.5)
        finally:
            metadata['state'] = 'stopping'
            save(folder, metadata)
            try:
                stop(sync_component)
                stop(components['frontend'])
            finally:
                stop(components['backend'], backend_stop)
                metadata.update(state='stopped', components={})
                save(folder, metadata)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    try:
        run(config)
    except Exception as error:
        # Keep all infrastructure exception detail out of public runtime metadata.
        save(Path(config['runtime_dir']), dict(state='failed', pid=os.getpid(), error_type=type(error).__name__))
        raise SystemExit(1)
