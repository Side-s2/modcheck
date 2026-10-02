"""选择文件夹 / 文件的系统对话框。

**为什么不用 tkinter**：本项目要求零第三方运行时依赖；而且实测本机 Python 3.11
**没有 tkinter**（ModuleNotFoundError），引入它还会让 exe 变大好几 MB。
所以这里直接用 Windows 自带的 IFileDialog（Vista+ 的现代选择文件夹窗口），
外观是系统原生的，体积几乎不增加。

非 Windows 平台上 pick_folder() / pick_file_ex() 一律返回"没有对话框"，调用方回退为手输
路径 —— Linux 用户照样能用，只是没有图形选择框。

选文件与选文件夹共用同一个对话框对象（IFileOpenDialog），区别只在选项位
（FOS_PICKFOLDERS 与 FOS_FILEMUSTEXIST）和一行类型过滤；两套壳子会让 COM 那些
vtable 下标出现第二份，出问题时无从对照。
"""
from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import POINTER, byref, c_uint32, c_void_p, c_wchar_p
from typing import Final

#: pick_folder_ex 的状态：拿到了路径 / 用户取消 / 这台机器没有对话框
FOLDER_OK: Final[str] = "ok"
FOLDER_CANCELLED: Final[str] = "cancelled"
FOLDER_UNAVAILABLE: Final[str] = "unavailable"

#: IFileDialog 的 vtable 下标（IUnknown 0-2，IModalWindow 3，IFileDialog 从 4 起）
_VT_RELEASE = 2
_VT_SHOW = 3
_VT_SET_FILE_TYPES = 4
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
_FOS_FILEMUSTEXIST = 0x00001000      # 必须选一个已经存在的文件
_FOS_PATHMUSTEXIST = 0x00000800      # 路径必须存在
_FOS_DONTADDTORECENT = 0x02000000    # 不写进"最近使用的文件"（别人的清单不必留痕）
_SIGDN_FILESYSPATH = 0x80058000


class _FILTERSPEC(ctypes.Structure):
    """COMDLG_FILTERSPEC：对话框里"文件类型"下拉框的一行（显示名 + 通配符）。"""

    _fields_ = [("pszName", c_wchar_p), ("pszSpec", c_wchar_p)]


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


def _pick_windows(title: str, *, folders: bool,
                  file_types: tuple[str, str] | None = None) -> str | None:
    """弹出系统选择窗口，返回绝对路径；取消返回 None。

    folders=True 选文件夹；False 选文件（可给一行类型过滤：显示名 + 通配符）。
    file_types 的显示名由调用方从 i18n 取 —— 本模块不写中文字面量。
    """
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
        flags = options.value | _FOS_FORCEFILESYSTEM | _FOS_PATHMUSTEXIST
        flags |= _FOS_PICKFOLDERS if folders else (_FOS_FILEMUSTEXIST | _FOS_DONTADDTORECENT)
        _method(dialog, _VT_SET_OPTIONS, c_uint32)(dialog, flags)
        if not folders and file_types is not None:
            try:
                label, pattern = file_types
                spec = _FILTERSPEC(c_wchar_p(label), c_wchar_p(pattern))
                _method(dialog, _VT_SET_FILE_TYPES, c_uint32,
                        POINTER(_FILTERSPEC))(dialog, 1, byref(spec))
            except Exception:
                pass          # 设不了过滤就退回"所有文件"，对话框照常弹
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
    """弹出系统"选择文件夹"窗口，返回绝对路径；取消或不可用返回 None。"""
    _status, path = pick_folder_ex(title)
    return path


def pick_file(title: str, *, filter_label: str, pattern: str = "*.json") -> str | None:
    """弹出系统"选择文件"窗口，返回绝对路径；取消或不可用返回 None。"""
    _status, path = pick_file_ex(title, filter_label=filter_label, pattern=pattern)
    return path


def pick_folder_ex(title: str) -> tuple[str, str | None]:
    """弹出选择文件夹窗口，返回 (状态, 路径)。

    与 pick_folder 的区别：把"用户按了取消"和"这台机器没有对话框"分开 ——
    PRD §14.4 要求前者视为"取消下载（不是错误）"，后者回退成手输路径。
    合成一个 None 就分不出来了：Windows 用户按取消会被当成"没有对话框"再问一遍。
    """
    return _show(lambda: _pick_windows(title, folders=True))


def pick_file_ex(title: str, *, filter_label: str,
                 pattern: str = "*.json") -> tuple[str, str | None]:
    """弹出选择文件窗口，返回 (状态, 路径)；状态与 pick_folder_ex 完全一致。

    filter_label 是"文件类型"下拉框里那一行的显示名（由调用方从 i18n 取），
    pattern 是通配符（默认 *.json）。取消 / 没有对话框的区分与选文件夹同理：
    取消是"用户不想导入了"（不是错误），没有对话框才回退手输路径。
    """
    return _show(lambda: _pick_windows(title, folders=False,
                                       file_types=(filter_label, pattern)))


def _show(open_dialog) -> tuple[str, str | None]:
    """跑一次对话框，把结果收敛成 (状态, 路径)（非 Windows / 任何异常都算"没有对话框"）。"""
    if sys.platform != "win32":
        return FOLDER_UNAVAILABLE, None
    try:
        path = open_dialog()
    except Exception:
        return FOLDER_UNAVAILABLE, None
    if path:
        return FOLDER_OK, path
    return FOLDER_CANCELLED, None


__all__ = ["pick_folder", "pick_folder_ex", "pick_file", "pick_file_ex",
           "FOLDER_OK", "FOLDER_CANCELLED", "FOLDER_UNAVAILABLE"]
