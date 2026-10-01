"""选择文件夹的对话框。

**为什么不用 tkinter**：本项目要求零第三方运行时依赖；而且实测本机 Python 3.11
**没有 tkinter**（ModuleNotFoundError），引入它还会让 exe 变大好几 MB。
所以这里直接用 Windows 自带的 IFileDialog（Vista+ 的现代选择文件夹窗口），
外观是系统原生的，体积几乎不增加。

非 Windows 平台上 pick_folder() 一律返回 None，调用方回退为手输路径 ——
Linux 用户照样能用，只是没有图形选择框。
"""
from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import POINTER, byref, c_uint32, c_void_p, c_wchar_p

#: IFileDialog 的 vtable 下标（IUnknown 0-2，IModalWindow 3，IFileDialog 从 4 起）
_VT_RELEASE = 2
_VT_SHOW = 3
_VT_SET_OPTIONS = 9
_VT_GET_OPTIONS = 10
_VT_SET_TITLE = 17
_VT_GET_RESULT = 20
#: IShellItem 的 GetDisplayName 下标（IUnknown 0-2，IBindToHandler 3，GetParent 4，GetDisplayName 5）
_VT_ITEM_GET_DISPLAY_NAME = 5

_CLSID_FILE_OPEN_DIALOG = "DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7"
_IID_IFILE_OPEN_DIALOG = "d57c7288-d4ad-4768-be02-9d969532d960"

_COINIT_APARTMENTTHREADED = 0x2
_CLSCTX_INPROC_SERVER = 0x1
_FOS_PICKFOLDERS = 0x00000020        # 只选文件夹
_FOS_FORCEFILESYSTEM = 0x00000040    # 必须返回文件系统路径（否则可能是虚拟项）
_FOS_PATHMUSTEXIST = 0x00000800      # 路径必须存在
_SIGDN_FILESYSPATH = 0x80058000


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    """由字符串生成 GUID（bytes_le 就是 Windows 要的内存布局）。"""
    return _GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


def _method(ptr: c_void_p, index: int, *argtypes):
    """取出 COM 对象的第 index 个虚函数（签名：HRESULT (this, *argtypes)）。

    COM 在 ctypes 里只能手工走 vtable —— 这是零依赖调用系统对话框的代价，
    所以每一步都包在 try 里，任何异常都退化成"没有选择框"，绝不崩。
    """
    vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)
    return proto(vtable[index])


def _release(ptr: c_void_p) -> None:
    try:
        _method(ptr, _VT_RELEASE)(ptr)
    except Exception:
        pass


def _pick_folder_windows(title: str) -> str | None:
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    dialog = c_void_p()
    try:
        clsid, iid = _guid(_CLSID_FILE_OPEN_DIALOG), _guid(_IID_IFILE_OPEN_DIALOG)
        hr = ole32.CoCreateInstance(byref(clsid), None, _CLSCTX_INPROC_SERVER,
                                    byref(iid), byref(dialog))
        if hr < 0 or not dialog:
            return None
        options = c_uint32()
        _method(dialog, _VT_GET_OPTIONS, POINTER(c_uint32))(dialog, byref(options))
        _method(dialog, _VT_SET_OPTIONS, c_uint32)(
            dialog, options.value | _FOS_PICKFOLDERS | _FOS_FORCEFILESYSTEM | _FOS_PATHMUSTEXIST)
        _method(dialog, _VT_SET_TITLE, c_wchar_p)(dialog, title)
        if _method(dialog, _VT_SHOW, c_void_p)(dialog, None) < 0:
            return None                      # 用户取消（ERROR_CANCELLED）也走这里
        item = c_void_p()
        if _method(dialog, _VT_GET_RESULT, POINTER(c_void_p))(dialog, byref(item)) < 0 or not item:
            return None
        try:
            raw = c_wchar_p()
            if _method(item, _VT_ITEM_GET_DISPLAY_NAME, c_uint32,
                       POINTER(c_wchar_p))(item, _SIGDN_FILESYSPATH, byref(raw)) < 0:
                return None
            try:
                return raw.value or None
            finally:
                ole32.CoTaskMemFree(raw)
        finally:
            _release(item)
    finally:
        if dialog:
            _release(dialog)
        ole32.CoUninitialize()


def pick_folder(title: str) -> str | None:
    """弹出系统"选择文件夹"窗口，返回绝对路径；取消或不可用返回 None。

    非 Windows、无 COM、用户取消 —— 三者都返回 None，调用方据此回退为手输。
    """
    if sys.platform != "win32":
        return None
    try:
        return _pick_folder_windows(title)
    except Exception:
        return None


__all__ = ["pick_folder"]
