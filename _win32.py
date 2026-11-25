"""ctypes bindings for the few Windows APIs compat.py needs. Imported on Windows only."""
import ctypes
from ctypes import wintypes as W
import os

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
user32 = ctypes.WinDLL('user32', use_last_error=True)

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
_JOB_BASIC_PROCESS_ID_LIST = 3
_WM_CLOSE = 0x0010
_GW_OWNER = 4
_FILE_SHARE_READ_WRITE = 0x1 | 0x2
_OPEN_EXISTING = 3
_IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
_STORAGE_DEVICE_SEEK_PENALTY_PROPERTY = 7
_INVALID_HANDLE = ctypes.c_void_p(-1).value

kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, W.LPCWSTR]
kernel32.CreateJobObjectW.restype = W.HANDLE
kernel32.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
kernel32.AssignProcessToJobObject.restype = W.BOOL
kernel32.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
kernel32.TerminateJobObject.restype = W.BOOL
kernel32.QueryInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD,
                                               ctypes.POINTER(W.DWORD)]
kernel32.QueryInformationJobObject.restype = W.BOOL
kernel32.CloseHandle.argtypes = [W.HANDLE]
kernel32.CloseHandle.restype = W.BOOL
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.OpenProcess.restype = W.HANDLE
kernel32.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
kernel32.GetExitCodeProcess.restype = W.BOOL
kernel32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, ctypes.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
kernel32.CreateFileW.restype = W.HANDLE
kernel32.DeviceIoControl.argtypes = [W.HANDLE, W.DWORD, ctypes.c_void_p, W.DWORD, ctypes.c_void_p, W.DWORD,
                                     ctypes.POINTER(W.DWORD), ctypes.c_void_p]
kernel32.DeviceIoControl.restype = W.BOOL

_ENUM_WINDOWS = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
user32.EnumWindows.argtypes = [_ENUM_WINDOWS, W.LPARAM]
user32.EnumWindows.restype = W.BOOL
user32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
user32.GetWindowThreadProcessId.restype = W.DWORD
user32.IsWindowVisible.argtypes = [W.HWND]
user32.IsWindowVisible.restype = W.BOOL
user32.GetWindow.argtypes = [W.HWND, W.UINT]
user32.GetWindow.restype = W.HWND
user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
user32.PostMessageW.restype = W.BOOL


def _check(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def close(handle):
    kernel32.CloseHandle(handle)


# ----- Job objects ----------------------------------------------------------

def create_job():
    return _check(kernel32.CreateJobObjectW(None, None))


def assign(job, process):
    _check(kernel32.AssignProcessToJobObject(job, int(process._handle)))


def terminate_job(job, code):
    _check(kernel32.TerminateJobObject(job, code))


def job_pids(job):
    class Pids(ctypes.Structure):
        _fields_ = [('assigned', W.DWORD), ('listed', W.DWORD), ('ids', ctypes.c_size_t * 512)]
    pids = Pids()
    _check(kernel32.QueryInformationJobObject(job, _JOB_BASIC_PROCESS_ID_LIST, ctypes.byref(pids),
                                              ctypes.sizeof(pids), None))
    return {int(pid) for pid in pids.ids[:pids.listed]}


def close_windows(pids):
    """Post WM_CLOSE to the visible top-level windows of ``pids``; returns how many."""
    windows = []

    @_ENUM_WINDOWS
    def visit(hwnd, _):
        owner = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if (owner.value in pids and user32.IsWindowVisible(hwnd)
                and not user32.GetWindow(hwnd, _GW_OWNER)):
            windows.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    for hwnd in windows:
        user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
    return len(windows)


def process_alive(pid):
    if pid <= 0:
        return False
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means the process exists but belongs to someone else.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = W.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == _STILL_ACTIVE
    finally:
        close(handle)


# ----- Disks, controllers, display ------------------------------------------

class _PropertyQuery(ctypes.Structure):
    _fields_ = [('PropertyId', W.DWORD), ('QueryType', W.DWORD), ('AdditionalParameters', W.BYTE * 1)]


class _SeekPenalty(ctypes.Structure):
    _fields_ = [('Version', W.DWORD), ('Size', W.DWORD), ('IncursSeekPenalty', ctypes.c_ubyte)]


def seek_penalty(path):
    """True if the volume holding ``path`` is on a spinning disk; False if solid state or unknown."""
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if len(drive) != 2 or drive[1] != ':':
        return False  # Network share or unusual mount: unknown.
    # No access rights are needed to query the storage properties.
    handle = kernel32.CreateFileW(f'\\\\.\\{drive}', 0, _FILE_SHARE_READ_WRITE, None, _OPEN_EXISTING, 0, None)
    if not handle or handle == _INVALID_HANDLE:
        return False
    try:
        query = _PropertyQuery(_STORAGE_DEVICE_SEEK_PENALTY_PROPERTY, 0)
        result, returned = _SeekPenalty(), W.DWORD()
        ok = kernel32.DeviceIoControl(handle, _IOCTL_STORAGE_QUERY_PROPERTY, ctypes.byref(query),
                                      ctypes.sizeof(query), ctypes.byref(result), ctypes.sizeof(result),
                                      ctypes.byref(returned), None)
        return bool(ok) and returned.value >= ctypes.sizeof(result) and bool(result.IncursSeekPenalty)
    finally:
        close(handle)


class _JoyInfo(ctypes.Structure):
    _fields_ = [(name, W.DWORD) for name in (
        'dwSize', 'dwFlags', 'dwXpos', 'dwYpos', 'dwZpos', 'dwRpos', 'dwUpos', 'dwVpos',
        'dwButtons', 'dwButtonNumber', 'dwPOV', 'dwReserved1', 'dwReserved2')]


def joystick_connected():
    """Any game controller, XInput or DirectInput, as the joystick API sees it."""
    try:
        winmm = ctypes.WinDLL('winmm')
        winmm.joyGetNumDevs.restype = W.UINT
        winmm.joyGetPosEx.argtypes = [W.UINT, ctypes.POINTER(_JoyInfo)]
        winmm.joyGetPosEx.restype = W.UINT
        count = winmm.joyGetNumDevs()
    except OSError:
        return False
    for index in range(min(count, 16)):
        info = _JoyInfo(dwSize=ctypes.sizeof(_JoyInfo), dwFlags=0xFF)  # JOY_RETURNALL
        if winmm.joyGetPosEx(index, ctypes.byref(info)) == 0:  # JOYERR_NOERROR
            return True
    return False


def system_scale():
    try:
        return max(1, user32.GetDpiForSystem()) / 96
    except (AttributeError, OSError):
        return 1.0
