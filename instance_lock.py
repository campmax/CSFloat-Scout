"""One requesting process per scout folder; OS releases lock after a crash."""
import os


class InstanceLock:
    def __init__(self,path):
        self.file=open(path,'a+b')
        if self.file.seek(0,2)==0:
            self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('Another scout command is already running in this folder. Stop it before starting another.') from None

    def close(self):
        if not self.file.closed:self.file.close()
