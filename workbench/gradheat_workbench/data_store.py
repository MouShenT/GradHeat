"""Read the MySQL publication with replaceable Redis/local caches."""
import hashlib,json,sys,threading
from pathlib import Path
from .admissions import build_public


class AdmissionsStore:
    def __init__(self,root,repo,remote=False):
        self.root=root;self.payload=build_public(repo);self.version=None
        self.lock=threading.RLock();self.stop_event=threading.Event();self.remote=remote
        try:self.reload_local()
        except (OSError,ValueError,KeyError):pass

    def reload_local(self):
        pointer=self.root/'.research/admissions-data/latest.json'
        if not pointer.exists():return
        info=json.loads(pointer.read_text(encoding='utf-8'));version=info['version_id']
        with self.lock:
            if version==self.version:return
            path=Path(info['path']).resolve()
            if not path.is_relative_to(self.root/'.research/admissions-data'):raise ValueError('Invalid public mirror path')
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=version:raise ValueError('Invalid public mirror hash')
            self.payload=json.loads(raw);self.version=version

    def get(self):
        try:self.reload_local()
        except (OSError,ValueError,KeyError):pass
        with self.lock:return self.payload

    def start(self):
        if not self.remote:return
        def refresh():
            sys.path.insert(0,str(self.root/'crawler'))
            from gradheat.vm_db import connect_vm
            from gradheat.publication import load
            while not self.stop_event.is_set():
                try:
                    with connect_vm(self.root/'.research/admissions-data') as con:load(con,self.root)
                    self.reload_local()
                except Exception as error:
                    folder=self.root/'.research/admissions-data';folder.mkdir(parents=True,exist_ok=True)
                    (folder/'read-status.json').write_text(json.dumps({'state':'using-last-verified-data','error_type':type(error).__name__}),encoding='utf-8')
                if self.stop_event.wait(300):break
        self.thread=threading.Thread(target=refresh,daemon=True,name='admissions-cache-refresh');self.thread.start()

    def close(self):self.stop_event.set()
