from contextlib import contextmanager


class Database:
    def __init__(self, settings):
        self.settings = settings

    @contextmanager
    def connect(self):
        if self.settings.db_mode == 'ssh':
            # Existing strict HostKeyAlias and private credential loader are reused.
            from gradheat.vm_db import connect_vm
            with connect_vm(self.settings.root / '.research/python-service/private') as con:
                yield con
            return
        import pymysql
        con = pymysql.connect(host=self.settings.db_host, port=self.settings.db_port,
            database=self.settings.db_name, user=self.settings.db_user,
            password=self.settings.db_password, charset='utf8mb4', autocommit=False,
            connect_timeout=8, read_timeout=60, write_timeout=60)
        try:
            yield con
        finally:
            con.rollback()
            con.close()
