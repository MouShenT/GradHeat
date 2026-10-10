from dataclasses import dataclass
import os
from pathlib import Path

from .bootstrap import ROOT


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    db_mode: str = 'direct'
    db_host: str = '127.0.0.1'
    db_port: int = 3306
    db_name: str = 'gradheat'
    db_user: str = 'gradheat'
    db_password: str = ''
    internal_token: str = ''
    publication_file: Path | None = None
    publication_sha: str | None = None
    rabbit_url: str = ''
    worker_id: str = 'win-primary'
    worker_queues: tuple[str, ...] = ('analyse.long', 'extract.documents', 'verify.information')
    lease_seconds: int = 120
    refresh_seconds: float = 5

    @classmethod
    def from_env(cls):
        values = dict(root=Path(os.getenv('GRADHEAT_ROOT', str(ROOT))).resolve(),
            db_mode=os.getenv('GRADHEAT_DB_MODE', 'direct'),
            db_host=os.getenv('GRADHEAT_DB_HOST', '127.0.0.1'),
            db_port=int(os.getenv('GRADHEAT_DB_PORT', '3306')),
            db_name=os.getenv('GRADHEAT_DB_NAME', 'gradheat'),
            db_user=os.getenv('GRADHEAT_DB_USER', 'gradheat'),
            db_password=os.getenv('GRADHEAT_DB_PASSWORD', ''),
            internal_token=os.getenv('GRADHEAT_INTERNAL_TOKEN', ''),
            rabbit_url=os.getenv('GRADHEAT_RABBIT_URL', ''),
            worker_id=os.getenv('GRADHEAT_WORKER_ID', 'win-primary'),
            worker_queues=tuple(x.strip() for x in os.getenv('GRADHEAT_WORKER_QUEUES', 'analyse.long,extract.documents,verify.information').split(',') if x.strip()))
        if os.getenv('GRADHEAT_PUBLICATION_FILE'):
            values.update(publication_file=Path(os.environ['GRADHEAT_PUBLICATION_FILE']).resolve(),
                publication_sha=os.getenv('GRADHEAT_PUBLICATION_SHA'))
        settings = cls(**values)
        if settings.db_mode not in ('direct', 'ssh'):
            raise ValueError('Unsupported database connection mode')
        if len(settings.internal_token) < 32:
            raise ValueError('GRADHEAT_INTERNAL_TOKEN must contain at least 32 characters')
        return settings
