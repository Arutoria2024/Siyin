"""Cross-process serialization for utterances and model changes."""
import contextlib, ctypes, os, threading
_lock=threading.Lock()
@contextlib.contextmanager
def hold():
    if os.name!='nt':
        with _lock:yield
        return
    k=ctypes.windll.kernel32
    k.CreateMutexW.restype=ctypes.c_void_p
    k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    k.ReleaseMutex.argtypes=[ctypes.c_void_p];k.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=k.CreateMutexW(None,False,'Local\\SiVoiceInference')
    if not handle:raise OSError('Cannot create inference mutex')
    try:
        result=k.WaitForSingleObject(handle,0xFFFFFFFF)
        if result not in (0,128):raise OSError('Cannot acquire inference mutex')
        try:yield
        finally:k.ReleaseMutex(handle)
    finally:k.CloseHandle(handle)
