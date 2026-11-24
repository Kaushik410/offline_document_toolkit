"""Keep bundled Qt/Python libraries out of system-installed document engines."""
from contextlib import contextmanager
from pathlib import Path
import os
import subprocess
import sys
import threading

_DLL_LOCK=threading.RLock()


def system_environment(environment=None):
    env=dict(os.environ if environment is None else environment)
    if not getattr(sys,'frozen',False):return env
    root=Path(getattr(sys,'_MEIPASS',Path(sys.executable).parent)).resolve()
    def external_paths(value):
        paths=[]
        for item in value.split(os.pathsep):
            if not item:continue
            path=Path(item).resolve()
            if path==root or root in path.parents:continue
            paths.append(item)
        return os.pathsep.join(paths)
    if os.name=='posix':
        restored=external_paths(env.get('LD_LIBRARY_PATH_ORIG',''))
        if restored:env['LD_LIBRARY_PATH']=restored
        else:env.pop('LD_LIBRARY_PATH',None)
    if 'PATH' in env:env['PATH']=external_paths(env['PATH'])
    for key in ('QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH'):
        if key in env:
            cleaned=external_paths(env[key])
            if cleaned:env[key]=cleaned
            else:env.pop(key,None)
    return env


@contextmanager
def system_dll_search():
    if os.name!='nt' or not getattr(sys,'frozen',False):
        yield;return
    import ctypes
    from ctypes import wintypes
    with _DLL_LOCK:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetDllDirectoryW.argtypes=[wintypes.DWORD,wintypes.LPWSTR]
        kernel.GetDllDirectoryW.restype=wintypes.DWORD
        kernel.SetDllDirectoryW.argtypes=[wintypes.LPCWSTR]
        kernel.SetDllDirectoryW.restype=wintypes.BOOL
        length=kernel.GetDllDirectoryW(0,None)
        buffer=ctypes.create_unicode_buffer(length+1)
        if length:kernel.GetDllDirectoryW(len(buffer),buffer)
        previous=buffer.value or None
        if not kernel.SetDllDirectoryW(None):raise ctypes.WinError(ctypes.get_last_error())
        try:yield
        finally:
            if not kernel.SetDllDirectoryW(previous):raise ctypes.WinError(ctypes.get_last_error())


def run_external(command,**kwargs):
    env=system_environment(kwargs.pop('env',None))
    with system_dll_search():
        return subprocess.run(command,env=env,**kwargs)
