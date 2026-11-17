# -*- coding: utf-8 -*-
"""
CopyPad - 悬浮粘贴板 / Floating Clipboard Pad
单文件 Windows 桌面应用。

核心思路：保留「常用文本片段库」（手动维护、点一下即复制），
再叠加高星剪贴板项目（CopyQ / EcoPaste / Ditto）的优点：
全局热键唤起、托盘常驻、即时搜索、收藏置顶、键盘导航、
自动记录最近复制、敏感内容过滤、本地存储、开机自启。
"""
import os
import sys
import json
import time
import re
import uuid
import queue
import threading
import traceback
import ctypes
from ctypes import wintypes

import tkinter as tk
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, simpledialog

import win32api
import win32con
import win32event
import win32gui
import win32clipboard
import winerror
import winreg

APP = "CopyPad"
WND_CLASS = "CopyPadNativeWindow_v2"
MUTEX_NAME = "CopyPadSingleton_v2"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

WM_TRAY = win32con.WM_USER + 20
WM_SHOW_APP = win32con.WM_USER + 21
WM_CLIPBOARDUPDATE = 0x031D
HOTKEY_TOGGLE = 1
HOTKEY_NUM_BASE = 100

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
CS_DROPSHADOW = 0x00020000
GA_ROOT = 2

_user32 = ctypes.windll.user32
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetClipboardSequenceNumber.argtypes = []
_user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
try:
    _user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    _user32.SetWindowRgn.restype = ctypes.c_int
except Exception:
    pass
try:
    _user32.AddClipboardFormatListener.argtypes = [wintypes.HWND]
    _user32.AddClipboardFormatListener.restype = wintypes.BOOL
except Exception:
    pass


# ---------------------------------------------------------------- 基础工具
def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    p = os.path.join(base, "CopyPad")
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass
    return p


DATA_DIR = data_dir()
DATA_FILE = os.path.join(DATA_DIR, "data.json")
LEGACY_FILE = os.path.join(DATA_DIR, "items.txt")
LOG_FILE = os.path.join(DATA_DIR, "error.log")


def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except Exception:
        pass


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)


def enable_dpi():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def tk_hwnd(root):
    try:
        return int(_user32.GetAncestor(root.winfo_id(), GA_ROOT))
    except Exception:
        return int(root.winfo_id())


THEMES = {
    "dark": {
        "bg": "#171a22", "top": "#1c202a", "footer": "#1c202a",
        "card": "#222735", "card_hover": "#2b3242", "card_sel": "#2d3a55",
        "border": "#39435a", "text": "#e9edf6", "muted": "#8995a9",
        "accent": "#6d8cff", "accent_soft": "#2f3a61",
        "star": "#ffc857", "danger": "#ff7a85", "ok": "#63d6a4",
        "entry": "#12151c", "scroll": "#4a556b", "handle": "#4a556b",
    },
    "light": {
        "bg": "#f4f6fa", "top": "#ffffff", "footer": "#ffffff",
        "card": "#ffffff", "card_hover": "#eef2fb", "card_sel": "#e4ebff",
        "border": "#d7deeb", "text": "#1c2331", "muted": "#77839a",
        "accent": "#3f62e0", "accent_soft": "#e1e9ff",
        "star": "#e8a417", "danger": "#d94f5c", "ok": "#189b6b",
        "entry": "#f1f4f9", "scroll": "#b9c3d6", "handle": "#b9c3d6",
    },
}

SENSITIVE = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk-|ghp_|gho_|ghu_|ghs_|xox[baprs]-)[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key)\s*[:=]\s*\S{6,}"),
]


def is_sensitive(t):
    if not t or len(t) > 20000:
        return True
    return any(p.search(t) for p in SENSITIVE)


def clip_set(text):
    for _ in range(6):
        try:
            win32clipboard.OpenClipboard(None)
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            win32clipboard.CloseClipboard()
            return True
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            time.sleep(0.05)
    return False


def clip_get():
    for _ in range(3):
        try:
            win32clipboard.OpenClipboard(None)
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                val = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            else:
                val = None
            win32clipboard.CloseClipboard()
            return val
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            time.sleep(0.05)
    return None


def autostart_on():
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(k, APP)
            return True
        finally:
            winreg.CloseKey(k)
    except Exception:
        return False


def set_autostart(on):
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if on:
            if getattr(sys, "frozen", False):
                cmd = '"%s"' % sys.executable
            else:
                cmd = '"%s" "%s"' % (sys.executable, os.path.abspath(__file__))
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, APP)
            except Exception:
                pass
        winreg.CloseKey(k)
        return True
    except Exception as e:
        log("set_autostart: %r" % (e,))
        return False


def new_item(text, star=False, tag=""):
    return {"id": uuid.uuid4().hex[:12], "text": text, "star": bool(star),
            "tag": tag, "ts": int(time.time()), "use": 0}


def normalize(raw, default_star=False):
    if isinstance(raw, str):
        return new_item(raw, default_star)
    if not isinstance(raw, dict):
        return None
    text = raw.get("text")
    if not isinstance(text, str) or not text:
        return None
    return {
        "id": raw.get("id") or uuid.uuid4().hex[:12],
        "text": text,
        "star": bool(raw.get("star", default_star)),
        "tag": raw.get("tag", "") or "",
        "ts": int(raw.get("ts") or time.time()),
        "use": int(raw.get("use") or 0),
    }


DEFAULT_SETTINGS = {
    "theme": "dark", "topmost": True, "capture": True,
    "max_history": 200, "geom": None, "tab": "all",
}


class Store:
    def __init__(self):
        self.items = []
        self.history = []
        self.settings = dict(DEFAULT_SETTINGS)
        self.loaded = False
        self.load()

    def load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self.items = [x for x in (normalize(i) for i in d.get("items", [])) if x]
                self.history = [x for x in (normalize(i) for i in d.get("history", [])) if x]
                s = d.get("settings") or {}
                if isinstance(s, dict):
                    self.settings.update(s)
                self.loaded = True
            except Exception as e:
                log("load data.json: %r" % (e,))
        if not self.loaded:
            self.import_legacy()
            self.loaded = True
        if self.settings.get("theme") not in THEMES:
            self.settings["theme"] = "dark"

    def import_legacy(self):
        """兼容旧版 CopyPad.ps1 的 UTF-8 一行一条 items.txt"""
        if not os.path.exists(LEGACY_FILE):
            return 0
        n = 0
        try:
            with open(LEGACY_FILE, "r", encoding="utf-8-sig") as f:
                for line in f:
                    t = line.rstrip("\r\n")
                    if t.strip():
                        self.items.append(new_item(t))
                        n += 1
        except Exception as e:
            log("import_legacy: %r" % (e,))
        return n

    def save(self):
        if not self.loaded:
            return
        try:
            tmp = DATA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 2, "items": self.items,
                           "history": self.history, "settings": self.settings},
                          f, ensure_ascii=False, indent=1)
            os.replace(tmp, DATA_FILE)
        except Exception as e:
            log("save: %r" % (e,))


# ---------------------------------------------------------------- 原生桥（热键 / 托盘 / 单实例消息）
class NativeBridge(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self.hwnd = None
        self.nid = None
        self.hicon = None
        self.hotkey_ok = True
        self.tray_ok = False

    def run(self):
        try:
            hinst = win32api.GetModuleHandle(None)
            wc = win32gui.WNDCLASS()
            wc.lpszClassName = WND_CLASS
            wc.hInstance = hinst
            wc.lpfnWndProc = {
                win32con.WM_HOTKEY: self._on_hotkey,
                WM_TRAY: self._on_tray,
                win32con.WM_COMMAND: self._on_command,
                WM_SHOW_APP: self._on_show,
                win32con.WM_QUERYENDSESSION: self._on_end,
            }
            try:
                win32gui.RegisterClass(wc)
            except win32gui.error:
                pass
            self.hwnd = win32gui.CreateWindow(WND_CLASS, "CopyPad", 0,
                                              0, 0, 0, 0, 0, 0, hinst, None)
            try:
                win32gui.RegisterHotKey(self.hwnd, HOTKEY_TOGGLE,
                                        MOD_CONTROL | MOD_SHIFT, win32con.VK_SPACE)
                for i in range(1, 10):
                    win32gui.RegisterHotKey(self.hwnd, HOTKEY_NUM_BASE + i,
                                            MOD_CONTROL | MOD_ALT, ord(str(i)))
            except Exception as e:
                self.hotkey_ok = False
                log("RegisterHotKey: %r" % (e,))
                self.app.post(self.app.on_hotkey_fail)
            self._tray_add()
            win32gui.PumpMessages()
        except Exception:
            log("NativeBridge:\n" + traceback.format_exc())

    def _load_icon(self):
        p = resource_path("app.ico")
        try:
            return win32gui.LoadImage(0, p, win32con.IMAGE_ICON, 0, 0,
                                     win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
        except Exception as e:
            log("LoadImage: %r" % (e,))
            try:
                return win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            except Exception:
                return 0

    def _tray_add(self):
        try:
            self.hicon = self._load_icon()
            flags = NIF_ICON | NIF_MESSAGE | NIF_TIP
            self.nid = (self.hwnd, 0, flags, WM_TRAY, self.hicon,
                        "CopyPad 悬浮粘贴板  |  Ctrl+Shift+Space")
            win32gui.Shell_NotifyIcon(NIM_ADD, self.nid)
            self.tray_ok = True
        except Exception as e:
            log("tray_add: %r" % (e,))

    def tray_remove(self):
        if self.tray_ok and self.nid:
            try:
                win32gui.Shell_NotifyIcon(NIM_DELETE, self.nid)
            except Exception:
                pass
            self.tray_ok = False

    def stop(self):
        if self.hwnd:
            try:
                win32gui.PostMessage(self.hwnd, win32con.WM_QUIT, 0, 0)
            except Exception:
                pass

    def _on_hotkey(self, hwnd, msg, wp, lp):
        hid = int(wp)
        if hid == HOTKEY_TOGGLE:
            self.app.post(self.app.toggle)
        elif HOTKEY_NUM_BASE < hid <= HOTKEY_NUM_BASE + 9:
            self.app.post(self.app.copy_by_index, hid - HOTKEY_NUM_BASE - 1)
        return 0

    def _on_show(self, hwnd, msg, wp, lp):
        self.app.post(self.app.show)
        return 0

    def _on_end(self, hwnd, msg, wp, lp):
        self.app.post(self.app.save_all)
        return 1

    def _on_tray(self, hwnd, msg, wp, lp):
        ev = win32api.LOWORD(lp)
        if ev == win32con.WM_LBUTTONUP or ev == win32con.WM_LBUTTONDBLCLK:
            self.app.post(self.app.toggle)
        elif ev in (win32con.WM_RBUTTONUP, win32con.WM_CONTEXTMENU):
            self._menu()
        return 0

    def _menu(self):
        try:
            s = self.app.store.settings

            def mark(label, val):
                return label + ("   [开]" if val else "   [关]")

            m = win32gui.CreatePopupMenu()
            win32gui.AppendMenu(m, win32con.MF_STRING, 1001, "显示 / 隐藏    Ctrl+Shift+Space")
            win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(m, win32con.MF_STRING, 1002, mark("窗口总在最前", s.get("topmost")))
            win32gui.AppendMenu(m, win32con.MF_STRING, 1003, mark("自动记录复制历史", s.get("capture")))
            win32gui.AppendMenu(m, win32con.MF_STRING, 1004, "切换深色 / 浅色主题")
            win32gui.AppendMenu(m, win32con.MF_STRING, 1005, mark("开机自动启动", autostart_on()))
            win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(m, win32con.MF_STRING, 1006, "导出片段 (.txt)")
            win32gui.AppendMenu(m, win32con.MF_STRING, 1007, "导入片段 (.txt)")
            win32gui.AppendMenu(m, win32con.MF_STRING, 1010, "清空复制历史")
            win32gui.AppendMenu(m, win32con.MF_STRING, 1008, "快捷键说明")
            win32gui.AppendMenu(m, win32con.MF_STRING, 1009, "退出")
            pos = win32api.GetCursorPos()
            try:
                win32gui.SetForegroundWindow(self.hwnd)
            except Exception:
                pass
            win32gui.TrackPopupMenu(m, win32con.TPM_LEFTALIGN,
                                    pos[0], pos[1], 0, self.hwnd, None)
            win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
            win32gui.DestroyMenu(m)
        except Exception as e:
            log("tray menu: %r" % (e,))

    def _on_command(self, hwnd, msg, wp, lp):
        cid = win32api.LOWORD(wp)
        a = self.app
        actions = {
            1001: a.toggle, 1002: a.toggle_topmost, 1003: a.toggle_capture,
            1004: a.toggle_theme, 1005: a.toggle_autostart,
            1006: a.export_items, 1007: a.import_items,
            1008: a.show_help, 1009: a.quit, 1010: a.clear_history,
        }
        fn = actions.get(cid)
        if fn:
            a.post(fn)
        return 0


# ---------------------------------------------------------------- 绘图小工具
def round_rect(c, x1, y1, x2, y2, r=9, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=1, **kw)


def wrap_text(text, f, maxw, maxlines=2):
    s = text.replace("\r", " ").replace("\n", " / ").replace("\t", "  ")
    if not s:
        return [""]
    # 大多数片段很短：一次测量就能确定单行，不必逐字符累加
    if f.measure(s) <= maxw:
        return [s]
    lines, cur, i = [], "", 0
    while i < len(s) and len(lines) < maxlines:
        ch = s[i]
        if cur and f.measure(cur + ch) > maxw:
            lines.append(cur)
            cur = ""
            continue
        cur += ch
        i += 1
    if cur and len(lines) < maxlines:
        lines.append(cur)
    if i < len(s):
        last = lines[-1] if lines else ""
        while last and f.measure(last + "...") > maxw:
            last = last[:-1]
        if lines:
            lines[-1] = last + "..."
        else:
            lines = [last + "..."]
    return lines or [""]


# ---------------------------------------------------------------- 主应用
class App:
    def __init__(self):
        self.store = Store()
        self.c = THEMES[self.store.settings["theme"]]
        self.q = queue.Queue()
        self.bridge = None
        self.query = ""
        self.tab = self.store.settings.get("tab", "all")
        self.visible = []
        self.layout = []
        self.row_bounds = []
        self.content_h = 0
        self.scroll = 0
        self.sel = -1
        self.hover = -1
        self.edit_id = None
        self.drag_from = None
        self.drag_to = None
        self.pending_copy = None
        self.last_clip_seq = 0
        self.own_text = None
        self.own_ts = 0
        self.prev_hwnd = None
        self._style_rules = []
        self._toast_job = None
        self._mv = None
        self._rs = None
        self._resize_job = None
        self._pending_size = None
        self._build_ui()
        self._apply_theme()
        self._load_geometry()
        self.refresh()
        self.root.after(40, self._drain)
        self.root.after(600, self._poll_clipboard)
        self.root.after(300, self.apply_region)
        self.root.after(120, self._update_minsize)

    # ---- 跨线程调度 ----
    def post(self, fn, *args):
        self.q.put((fn, args))

    def _drain(self):
        try:
            while True:
                fn, args = self.q.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    log("dispatch:\n" + traceback.format_exc())
        except queue.Empty:
            pass
        self.root.after(40, self._drain)

    # ---- 样式 ----
    def style(self, w, **kw):
        self._style_rules.append((w, kw))
        self._apply_rule(w, kw)

    def _apply_rule(self, w, kw):
        real = {k: (self.c[v] if isinstance(v, str) and v in self.c else v)
                for k, v in kw.items()}
        try:
            w.configure(**real)
        except Exception:
            pass

    def _apply_theme(self):
        self.c = THEMES[self.store.settings["theme"]]
        for w, kw in self._style_rules:
            self._apply_rule(w, kw)
        self.root.configure(bg=self.c["bg"])
        self._refresh_buttons()
        self.draw()

    # ---- UI 构建 ----
    def _build_ui(self):
        r = tk.Tk()
        self.root = r
        r.title(APP + " - 悬浮粘贴板")
        r.overrideredirect(True)
        r.attributes("-topmost", bool(self.store.settings.get("topmost")))
        try:
            r.iconbitmap(resource_path("app.ico"))
        except Exception:
            pass
        r.protocol("WM_DELETE_WINDOW", self.hide)
        r.minsize(330, 240)

        fam = set(tkfont.families())
        family = "Microsoft YaHei UI" if "Microsoft YaHei UI" in fam else (
            "Microsoft YaHei" if "Microsoft YaHei" in fam else "Segoe UI")
        self.font_title = tkfont.Font(family=family, size=11, weight="bold")
        self.font_row = tkfont.Font(family=family, size=10)
        self.font_small = tkfont.Font(family=family, size=9)
        self.font_num = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.font_icon = tkfont.Font(family="Segoe UI Symbol", size=13)
        self.font_empty = tkfont.Font(family=family, size=11)
        self.font_tab = tkfont.Font(family=family, size=9, weight="bold")

        outer = tk.Frame(r)
        self.style(outer, bg="bg")
        outer.pack(fill="both", expand=True)

        # -------- 顶部 --------
        head = tk.Frame(outer, padx=12, pady=10)
        self.style(head, bg="top")
        head.pack(fill="x")

        row1 = tk.Frame(head)
        self.style(row1, bg="top")
        row1.pack(fill="x")

        self.logo = tk.Canvas(row1, width=20, height=20, highlightthickness=0, bd=0)
        self.style(self.logo, bg="top")
        self.logo.pack(side="left", padx=(0, 7))
        self._draw_logo()

        lbl = tk.Label(row1, text="悬浮粘贴板", font=self.font_title, cursor="fleur")
        self.style(lbl, bg="top", fg="text")
        lbl.pack(side="left")
        lbl.bind("<ButtonPress-1>", self._start_move)
        lbl.bind("<B1-Motion>", self._on_move)
        lbl.bind("<ButtonRelease-1>", self._end_move)
        row1.bind("<ButtonPress-1>", self._start_move)
        row1.bind("<B1-Motion>", self._on_move)
        row1.bind("<ButtonRelease-1>", self._end_move)

        self.btn_top = self._mkbtn(row1, "置顶", self.toggle_topmost, padx=7)
        self.btn_theme = self._mkbtn(row1, "主题", self.toggle_theme, padx=7)
        self.btn_min = self._mkbtn(row1, "-", self.hide, padx=9)
        self.btn_close = self._mkbtn(row1, "x", self.quit, padx=9, danger=True)
        for b in (self.btn_close, self.btn_min, self.btn_theme, self.btn_top):
            b.pack(side="right")

        row2 = tk.Frame(head, pady=0)
        self.style(row2, bg="top")
        row2.pack(fill="x", pady=(10, 0))

        search_box = tk.Frame(row2, padx=7, pady=4)
        self.style(search_box, bg="entry")
        search_box.pack(side="left", fill="x", expand=True)
        mag = tk.Canvas(search_box, width=15, height=15, highlightthickness=0, bd=0)
        self.style(mag, bg="entry")
        mag.pack(side="left", padx=(0, 5))
        self._mag_canvas = mag

        self.search_var = tk.StringVar()
        self.search = tk.Entry(search_box, textvariable=self.search_var,
                               relief="flat", bd=0, highlightthickness=0,
                               font=self.font_row, width=10)
        self.style(self.search, bg="entry", fg="text")
        self.search.configure(insertbackground=self.c["accent"])
        self.search.pack(side="left", fill="x", expand=True)
        self.search_var.trace_add("write", self._on_search)
        self.search.bind("<Up>", lambda e: (self.move_sel(-1), "break")[1])
        self.search.bind("<Down>", lambda e: (self.move_sel(1), "break")[1])
        self.search.bind("<Return>", self._search_enter)
        self.search.bind("<Escape>", lambda e: (self.hide(), "break")[1])
        self.search.bind("<Control-Return>", lambda e: (self.copy_item(self.sel, True), "break")[1])

        tabs = tk.Frame(row2)
        self.style(tabs, bg="top")
        tabs.pack(side="right", padx=(9, 0))
        self.tab_buttons = {}
        for key, txt in (("all", "全部"), ("star", "收藏"), ("history", "历史")):
            b = tk.Label(tabs, text=txt, font=self.font_tab, padx=8, pady=4, cursor="hand2")
            self.style(b, bg="top", fg="muted")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, k=key: self.set_tab(k))
            self.tab_buttons[key] = b

        # -------- 列表 --------
        self.canvas = tk.Canvas(outer, highlightthickness=0, bd=0)
        self.style(self.canvas, bg="bg")
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._context)
        self.canvas.bind("<Motion>", self._on_hover_motion)
        self.canvas.bind("<Configure>", self._on_configure)

        # -------- 底部 --------
        foot = tk.Frame(outer, padx=12, pady=10)
        self.style(foot, bg="footer")
        foot.pack(fill="x")

        add_row = tk.Frame(foot)
        self.style(add_row, bg="footer")
        add_row.pack(fill="x")

        input_box = tk.Frame(add_row, padx=8, pady=5)
        self.style(input_box, bg="entry")
        input_box.pack(side="left", fill="x", expand=True)
        self.input_var = tk.StringVar()
        self.input = tk.Entry(input_box, textvariable=self.input_var,
                              relief="flat", bd=0, highlightthickness=0,
                              font=self.font_row, width=10)
        self.style(self.input, bg="entry", fg="text")
        self.input.configure(insertbackground=self.c["accent"])
        self.input.pack(fill="x")
        self.input.bind("<Return>", lambda e: self.add_or_save())
        self.input.bind("<Escape>", lambda e: self.cancel_edit())
        self.input.bind("<FocusIn>", lambda e: self._sync_ph())
        self.input.bind("<FocusOut>", lambda e: self._sync_ph())
        self.input_var.trace_add("write", self._sync_ph)
        self.ph = tk.Label(input_box, text="输入内容，回车添加（可粘贴多行）",
                           font=self.font_small, anchor="w", cursor="xterm")
        self.style(self.ph, bg="entry", fg="muted")
        self.ph.place(x=1, y=0, relwidth=1, relheight=1)
        self.ph.bind("<Button-1>", self._focus_input)

        self.add_btn = self._mkbtn(add_row, "添加", self.add_or_save, padx=14, primary=True)
        self.add_btn.pack(side="left", padx=(8, 0))

        status_row = tk.Frame(foot)
        self.style(status_row, bg="footer")
        status_row.pack(fill="x", pady=(8, 0))
        self.status = tk.Label(status_row, text="", font=self.font_small, anchor="w")
        self.style(self.status, bg="footer", fg="muted")
        self.status.pack(side="left", fill="x", expand=True)
        self.grip = tk.Canvas(status_row, width=13, height=13,
                              highlightthickness=0, bd=0, cursor="sizing")
        self.style(self.grip, bg="footer")
        self.grip.pack(side="right")
        self.grip.bind("<ButtonPress-1>", self._start_resize)
        self.grip.bind("<B1-Motion>", self._on_resize)
        self.grip.bind("<ButtonRelease-1>", self._end_resize)

        # Footer must be allocated BEFORE the expanding canvas, otherwise
        # a small window pushes the input box out of view entirely.
        foot.pack(fill="x", side="bottom")
        self.canvas.pack(fill="both", expand=True, side="top")
        self.head, self.foot = head, foot

        # ---- 全局键盘 ----
        r.bind("<Up>", lambda e: None if self._in_entry() else self.move_sel(-1))
        r.bind("<Down>", lambda e: None if self._in_entry() else self.move_sel(1))
        r.bind("<Return>", lambda e: None if self._in_entry() else self.copy_item(self.sel))
        r.bind("<Control-Return>", lambda e: self.copy_item(self.sel, True))
        r.bind("<Escape>", lambda e: self.hide())
        r.bind("<Control-f>", lambda e: (self.search.focus_set(), "break")[1])
        r.bind("<F2>", lambda e: self.start_edit(self.sel))
        r.bind("<Delete>", lambda e: self.delete_row(self.sel))
        r.bind("<Control-n>", lambda e: self.input.focus_set())

    def _mkbtn(self, parent, text, cmd, padx=8, primary=False, danger=False):
        b = tk.Label(parent, text=text, font=self.font_small,
                     padx=padx, pady=3, cursor="hand2")
        self.style(b, bg="top", fg=("accent" if primary else "muted"))
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg=self.c["card_hover"]))
        b.bind("<Leave>", lambda e: self._refresh_buttons())
        b._cp_primary = primary
        b._cp_danger = danger
        return b

    def _refresh_buttons(self):
        c = self.c
        on = bool(self.store.settings.get("topmost"))
        try:
            self.btn_top.configure(fg=c["accent"] if on else c["muted"], bg=c["top"])
            self.btn_theme.configure(bg=c["top"])
            self.btn_min.configure(bg=c["top"])
            self.btn_close.configure(bg=c["top"], fg=c["danger"])
            self.add_btn.configure(bg=c["accent_soft"], fg=c["accent"])
            self.search.configure(insertbackground=c["accent"])
            self.input.configure(insertbackground=c["accent"])
            self._draw_logo()
            self._draw_mag()
            self._draw_grip()
            self._sync_ph()
            for key, b in self.tab_buttons.items():
                if key == self.tab:
                    b.configure(bg=c["accent_soft"], fg=c["accent"])
                else:
                    b.configure(bg=c["top"], fg=c["muted"])
        except Exception:
            pass

    def _draw_logo(self):
        c = self.c
        cv = self.logo
        cv.delete("all")
        round_rect(cv, 1, 1, 19, 19, 5, fill=c["accent"], outline="")
        cv.create_rectangle(6, 5, 14, 7, fill="#ffffff", outline="")
        cv.create_rectangle(6, 10, 14, 12, fill="#ffffff", outline="")
        cv.create_rectangle(6, 15, 11, 17, fill="#ffffff", outline="")

    def _draw_mag(self):
        cv = getattr(self, "_mag_canvas", None)
        if cv is None:
            return
        cv.delete("all")
        col = self.c["muted"]
        cv.create_oval(2, 2, 11, 11, outline=col, width=1)
        cv.create_line(10, 10, 14, 14, fill=col, width=2)

    def _draw_grip(self):
        cv = getattr(self, "grip", None)
        if cv is None:
            return
        cv.delete("all")
        for i in (0, 1, 2):
            cv.create_line(2 + i * 4, 12, 12, 2 + i * 4,
                           fill=self.c["handle"], width=2)

    def _sync_ph(self, *a):
        ph = getattr(self, "ph", None)
        if ph is None:
            return
        try:
            if self.input_var.get():
                ph.place_forget()
                return
            focused = False
            try:
                focused = self.root.focus_get() is self.input
            except Exception:
                pass
            if focused:
                ph.place_forget()
            else:
                ph.place(x=1, y=0, relwidth=1, relheight=1)
        except Exception:
            pass

    def _focus_input(self, e):
        self.ph.place_forget()
        self.input.focus_set()

    def _in_entry(self):
        try:
            return self.root.focus_get() in (self.input, self.search)
        except Exception:
            return False

    # ---- 窗口几何 ----
    def _update_minsize(self):
        """最小高度按“列表区约 1.5 行”算，而不是固定值。

        head/foot 的实际高度随字体与 DPI 变化，实测一次再定最小尺寸，
        这样把窗口拖到最小时停在同一位置，不会因机器不同而多显示或少显示。
        """
        try:
            self.root.update_idletasks()
            head_h = self.head.winfo_height() or 82
            foot_h = self.foot.winfo_height() or 74
            # 列表内容从 y=8 开始，单行 44px + 行距 6px，1.5 行约 80px
            self._min_h = max(210, head_h + foot_h + 82)
            self.root.minsize(330, self._min_h)
            w = max(330, self.root.winfo_width())
            h = max(self._min_h, self.root.winfo_height())
            if (w, h) != (self.root.winfo_width(), self.root.winfo_height()):
                self.root.geometry("%dx%d" % (w, h))
                self.apply_region()
        except Exception as e:
            log("update_minsize: %r" % (e,))

    def _load_geometry(self):
        g = self.store.settings.get("geom")
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        try:
            if isinstance(g, (list, tuple)) and len(g) == 4:
                x, y, w, h = [int(v) for v in g]
                w = max(330, min(w, sw - 20))
                h = max(getattr(self, "_min_h", 240), min(h, sh - 40))
                x = max(0, min(x, sw - w))
                y = max(0, min(y, sh - h))
            else:
                w, h = 390, 520
                x, y = sw - w - 24, 26
        except Exception:
            w, h = 390, 520
            x, y = sw - w - 24, 26
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def save_geometry(self):
        try:
            self.store.settings["geom"] = [self.root.winfo_x(), self.root.winfo_y(),
                                           self.root.winfo_width(), self.root.winfo_height()]
            self.store.settings["tab"] = self.tab
            self.store.save()
        except Exception:
            pass

    def save_all(self):
        self.save_geometry()

    def apply_region(self):
        try:
            h = tk_hwnd(self.root)
            w = self.root.winfo_width()
            hh = self.root.winfo_height()
            rgn = win32gui.CreateRoundRectRgn(0, 0, w + 1, hh + 1, 13, 13)
            win32gui.SetWindowRgn(h, rgn, True)
            try:
                st = win32gui.GetClassLong(h, win32con.GCL_STYLE)
                win32gui.SetClassLong(h, win32con.GCL_STYLE, st | CS_DROPSHADOW)
            except Exception:
                pass
        except Exception as e:
            log("apply_region: %r" % (e,))

    def _start_move(self, e):
        self._mv = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _on_move(self, e):
        if self._mv:
            self.root.geometry("+%d+%d" % (e.x_root - self._mv[0], e.y_root - self._mv[1]))

    def _end_move(self, e):
        self._mv = None
        self.save_geometry()

    def _start_resize(self, e):
        self._rs = (e.x_root, e.y_root, self.root.winfo_width(), self.root.winfo_height())
        # 拖动期间临时取消圆角裁剪：SetWindowRgn 会触发整窗重绘，
        # 每个 mousemove 都调一次就会闪。松手时再恢复圆角。
        self._clear_region()

    def _clear_region(self):
        try:
            _user32.SetWindowRgn(wintypes.HWND(tk_hwnd(self.root)), None, True)
        except Exception as e:
            log("clear_region: %r" % (e,))

    def _on_resize(self, e):
        if not self._rs:
            return
        mn = getattr(self, "_min_h", 240)
        w = max(330, self._rs[2] + e.x_root - self._rs[0])
        h = max(mn, self._rs[3] + e.y_root - self._rs[1])
        self._pending_size = (w, h)
        # 合并高频 mousemove：一帧最多重排一次
        if self._resize_job is None:
            self._resize_job = self.root.after(16, self._apply_resize)

    def _apply_resize(self):
        self._resize_job = None
        size, self._pending_size = self._pending_size, None
        if not size:
            return
        self.root.geometry("%dx%d" % size)
        self.refresh()

    def _end_resize(self, e):
        self._rs = None
        if self._resize_job is not None:
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
            self._resize_job = None
        size, self._pending_size = self._pending_size, None
        if size:
            self.root.geometry("%dx%d" % size)
        self.apply_region()
        self.refresh()
        self.save_geometry()

    # ---- 显示 / 隐藏 ----
    def show(self):
        try:
            fg = win32gui.GetForegroundWindow()
            own = tk_hwnd(self.root)
            self.prev_hwnd = fg if (fg and fg != own) else None
        except Exception:
            self.prev_hwnd = None
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", bool(self.store.settings.get("topmost")))
        try:
            win32gui.SetForegroundWindow(tk_hwnd(self.root))
        except Exception:
            pass
        self.apply_region()
        self.refresh()
        try:
            self.search.focus_set()
        except Exception:
            pass

    def hide(self):
        self.save_geometry()
        try:
            self.root.withdraw()
        except Exception:
            pass

    def toggle(self):
        try:
            if self.root.state() == "withdrawn":
                self.show()
            else:
                self.hide()
        except Exception:
            self.show()

    def quit(self):
        try:
            self.save_geometry()
            self.store.save()
        except Exception:
            pass
        if self.bridge:
            self.bridge.tray_remove()
            self.bridge.stop()
        try:
            self.root.destroy()
        except Exception:
            pass

    def on_hotkey_fail(self):
        self.toast("全局热键被占用，请用托盘图标打开")

    # ---- 数据视图 ----
    def _compute_visible(self):
        if self.tab == "history":
            src = list(self.store.history)
        else:
            src = [x for x in self.store.items
                   if self.tab != "star" or x.get("star")]
            src.sort(key=lambda x: (not x.get("star"), 0))
        if self.query:
            q = self.query.lower()
            src = [x for x in src
                   if q in x["text"].lower() or q in (x.get("tag") or "").lower()]
        return src

    def refresh(self):
        self.visible = self._compute_visible()
        self.layout = []
        try:
            avail = max(90, self.canvas.winfo_width() - 48 - 86)
        except Exception:
            avail = 240
        for it in self.visible:
            lines = wrap_text(it["text"], self.font_row, avail, 2)
            rh = 44 + (len(lines) - 1) * 17
            self.layout.append((it, lines, rh))
        self.content_h = sum(rh + 6 for _, _, rh in self.layout) + 10
        if self.sel >= len(self.visible):
            self.sel = len(self.visible) - 1
        self.clamp_scroll()
        self.draw()
        self.update_status()

    def clamp_scroll(self):
        h = self.canvas.winfo_height()
        mx = max(0, self.content_h - h)
        self.scroll = max(0, min(self.scroll, mx))

    def update_status(self):
        n = len(self.store.items)
        hn = len(self.store.history)
        base = "%d 条片段 · %d 条历史" % (n, hn)
        self._status_base = base
        if self._toast_job is None:
            try:
                if self.status.cget("text") != base:
                    self.status.configure(text=base)
            except Exception:
                pass

    def toast(self, msg):
        try:
            self.status.configure(text=msg, fg=self.c["ok"])
        except Exception:
            return
        if self._toast_job:
            try:
                self.root.after_cancel(self._toast_job)
            except Exception:
                pass
        self._toast_job = self.root.after(2200, self._clear_toast)

    def _clear_toast(self):
        self._toast_job = None
        try:
            self.status.configure(text=getattr(self, "_status_base", ""), fg=self.c["muted"])
        except Exception:
            pass

    # ---- 绘制 ----
    def draw(self):
        cv = self.canvas
        if cv is None:
            return
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 60 or H < 40:
            return
        col = self.c
        y = 8 - self.scroll
        self.row_bounds = []
        for idx, (it, lines, rh) in enumerate(self.layout):
            if y + rh >= 0 and y <= H:
                self._draw_row(cv, idx, it, lines, y, W, rh)
                self.row_bounds.append((y, y + rh, idx))
            y += rh + 6
        if not self.layout:
            msg = ("这里还没有内容\n在下方输入并回车添加，或复制任意文字自动记录"
                   if self.tab != "star" else "还没有收藏，点击条目右侧的星标即可收藏")
            cv.create_text(W / 2, H / 2 - 12, text=msg, fill=col["muted"],
                           font=self.font_empty, justify="center")
        if self.content_h > H + 2:
            th = max(30, H * H / max(1, self.content_h))
            top = (H - th) * self.scroll / max(1, self.content_h - H)
            cv.create_line(W - 3, top + 4, W - 3, top + th - 4,
                           width=3, fill=col["scroll"])
        if self.drag_from is not None and self.drag_to is not None:
            pos = 8 - self.scroll + sum(rh + 6 for _, _, rh in self.layout[:self.drag_to])
            cv.create_line(12, pos - 3, W - 12, pos - 3, fill=col["accent"], width=2)

    def _draw_row(self, cv, idx, it, lines, y, W, rh):
        col = self.c
        x0, x1 = 10, W - 10
        sel = (idx == self.sel)
        hov = (idx == self.hover)
        bg = col["card_sel"] if sel else (col["card_hover"] if hov else col["card"])
        round_rect(cv, x0, y, x1, y + rh, 9, fill=bg,
                   outline=col["border"] if (sel or hov) else "")
        if sel:
            cv.create_rectangle(x0 + 2, y + 11, x0 + 4, y + rh - 11,
                                fill=col["accent"], outline="")
        bxc = x0 + 21
        round_rect(cv, bxc - 11, y + rh / 2 - 11, bxc + 11, y + rh / 2 + 11, 6,
                   fill=col["accent_soft"] if idx < 9 else col["entry"], outline="")
        num = str(idx + 1) if idx < 9 else "-"
        cv.create_text(bxc, y + rh / 2, text=num,
                       fill=col["accent"] if idx < 9 else col["muted"], font=self.font_num)
        tx = x0 + 40
        for li, line in enumerate(lines):
            cv.create_text(tx, y + 9 + li * 17, text=line, anchor="nw",
                           fill=col["text"] if li == 0 else col["muted"],
                           font=self.font_row)
        sx, ex, dx = x1 - 64, x1 - 40, x1 - 16
        star_on = bool(it.get("star"))
        cv.create_text(sx, y + rh / 2, text="★" if star_on else "☆",
                       fill=col["star"] if star_on else col["muted"], font=self.font_icon)
        cv.create_text(ex, y + rh / 2, text="✎", fill=col["muted"], font=self.font_icon)
        cv.create_text(dx, y + rh / 2, text="×", fill=col["danger"], font=self.font_icon)
        if it.get("tag"):
            cv.create_text(x1 - 80, y + rh - 9, text=it["tag"], anchor="e",
                           fill=col["muted"], font=self.font_small)

    def _on_configure(self, e):
        # 拖动缩放时由 _apply_resize 统一重排，避免一次拖动触发两遍
        if self._rs is not None:
            return
        self.refresh()

    # ---- 命中测试 ----
    def hit_test(self, y):
        for y0, y1, idx in self.row_bounds:
            if y0 <= y <= y1:
                return idx
        return -1

    def hit_action(self, x):
        x1 = self.canvas.winfo_width() - 10
        if x >= x1 - 74 and x <= x1 - 54:
            return "star"
        if x >= x1 - 50 and x <= x1 - 30:
            return "edit"
        if x >= x1 - 26 and x <= x1 - 6:
            return "del"
        if x <= 42:
            return "handle"
        return "row"

    # ---- 交互 ----
    def _on_search(self, *a):
        self.query = self.search_var.get().strip()
        self.sel = -1
        self.scroll = 0
        self.refresh()

    def _search_enter(self, e):
        if self.visible:
            self.copy_item(0 if self.sel < 0 else self.sel)
        return "break"

    def set_tab(self, key):
        self.tab = key
        self.sel = -1
        self.scroll = 0
        self.store.settings["tab"] = key
        self.store.save()
        self._refresh_buttons()
        self.refresh()

    def _on_wheel(self, e):
        self.scroll -= int(e.delta / 120) * 62
        self.clamp_scroll()
        self.draw()
        return "break"

    def _on_hover_motion(self, e):
        if self.drag_from is not None:
            return
        idx = self.hit_test(e.y)
        if idx != self.hover:
            self.hover = idx
            self.draw()

    def _on_press(self, e):
        idx = self.hit_test(e.y)
        if idx < 0:
            return
        self.sel = idx
        act = self.hit_action(e.x)
        if act == "star":
            self.toggle_star(idx)
            self.draw()
            return
        if act == "del":
            self.delete_row(idx)
            return
        if act == "edit":
            self.start_edit(idx)
            self.draw()
            return
        if act == "handle" and self.tab != "history":
            self.drag_from, self.drag_to = idx, idx
            self.draw()
            return
        if self.pending_copy:
            try:
                self.root.after_cancel(self.pending_copy)
            except Exception:
                pass
        self.pending_copy = self.root.after(170, lambda i=idx: self._delayed_copy(i))
        self.draw()

    def _delayed_copy(self, idx):
        self.pending_copy = None
        self.copy_item(idx)

    def _on_double(self, e):
        if self.pending_copy:
            try:
                self.root.after_cancel(self.pending_copy)
            except Exception:
                pass
            self.pending_copy = None
        idx = self.hit_test(e.y)
        if idx >= 0 and self.hit_action(e.x) == "row":
            self.copy_item(idx, True)

    def _on_motion(self, e):
        if self.drag_from is not None:
            idx = self.hit_test(e.y)
            if idx >= 0 and idx != self.drag_to:
                self.drag_to = idx
                self.draw()
            return
        idx = self.hit_test(e.y)
        if idx != self.hover:
            self.hover = idx
            self.draw()

    def _on_release(self, e):
        if self.drag_from is not None:
            a, b = self.drag_from, self.drag_to
            self.drag_from = self.drag_to = None
            if b is not None and b != a:
                self.reorder(a, b)
            self.draw()

    def _context(self, e):
        idx = self.hit_test(e.y)
        if idx < 0:
            return
        self.sel = idx
        self.draw()
        c = self.c
        m = tk.Menu(self.root, tearoff=0, bg=c["card"], fg=c["text"],
                    activebackground=c["accent"], activeforeground="#ffffff",
                    borderwidth=0, font=self.font_small)
        m.add_command(label="复制", command=lambda: self.copy_item(idx))
        m.add_command(label="复制并粘贴  Ctrl+Enter", command=lambda: self.copy_item(idx, True))
        m.add_separator()
        m.add_command(label="编辑  F2", command=lambda: self.start_edit(idx))
        m.add_command(label="收藏 / 取消收藏", command=lambda: self.toggle_star(idx))
        m.add_command(label="设置标签...", command=lambda: self.set_tag(idx))
        m.add_command(label="上移", command=lambda: self.move_row(idx, -1))
        m.add_command(label="下移", command=lambda: self.move_row(idx, 1))
        m.add_separator()
        m.add_command(label="删除  Delete", command=lambda: self.delete_row(idx))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def move_sel(self, delta):
        if not self.visible:
            return
        n = len(self.visible)
        self.sel = 0 if self.sel < 0 else max(0, min(n - 1, self.sel + delta))
        self.ensure_visible(self.sel)
        self.draw()

    def ensure_visible(self, idx):
        if idx < 0 or idx >= len(self.layout):
            return
        top = 8 + sum(rh + 6 for _, _, rh in self.layout[:idx]) - self.scroll
        rh = self.layout[idx][2]
        H = self.canvas.winfo_height()
        if top < 8:
            self.scroll += top - 8
        elif top + rh > H - 8:
            self.scroll += top + rh - H + 8
        self.clamp_scroll()

    # ---- 操作 ----
    def copy_item(self, idx, paste=False):
        if idx is None or idx < 0 or idx >= len(self.visible):
            return
        it = self.visible[idx]
        text = it["text"]
        if not clip_set(text):
            self.toast("复制失败，剪贴板被占用")
            return
        self.own_text = text
        self.own_ts = time.time()
        it["use"] = int(it.get("use") or 0) + 1
        self.store.save()
        if paste:
            self.hide()
            self._paste_next()
            preview = (text[:18] + "...") if len(text) > 18 else text
            self.toast("已粘贴: " + preview)
        else:
            preview = (text[:22] + "...") if len(text) > 22 else text
            self.toast("已复制: " + preview.replace("\n", " "))

    def copy_by_index(self, idx):
        """Ctrl+Alt+1..9：直接复制当前列表第 N 条，不弹窗"""
        if not self.visible:
            self.refresh()
        if 0 <= idx < len(self.visible):
            self.copy_item(idx)

    def _paste_next(self):
        hwnd = self.prev_hwnd
        try:
            own = tk_hwnd(self.root)
        except Exception:
            own = None
        if hwnd and hwnd == own:
            return

        def go():
            if hwnd and win32gui.IsWindow(hwnd) and hwnd != own:
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    pass
            time.sleep(0.16)
            try:
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord("V"), 0, 0, 0)
                win32api.keybd_event(ord("V"), 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception as e:
                log("paste: %r" % (e,))

        threading.Thread(target=go, daemon=True).start()

    def add_or_save(self):
        raw = self.input_var.get()
        t = raw.strip()
        if not t:
            return
        if self.edit_id:
            found = False
            for coll in (self.store.items, self.store.history):
                for x in coll:
                    if x["id"] == self.edit_id:
                        x["text"] = t
                        found = True
                        break
                if found:
                    break
            self.cancel_edit()
            self.store.save()
            self.refresh()
            self.toast("已保存修改")
            return
        parts = [p.strip() for p in t.split("\n") if p.strip()]
        if len(parts) > 1:
            for p in parts:
                self.store.items.insert(0, new_item(p))
            self.toast("已添加 %d 条" % len(parts))
        else:
            self.store.items.insert(0, new_item(t))
            self.toast("已添加")
        self.input_var.set("")
        self.store.save()
        self.query = ""
        self.search_var.set("")
        self.refresh()
        self.input.focus_set()

    def start_edit(self, idx):
        if idx is None or idx < 0 or idx >= len(self.visible):
            return
        it = self.visible[idx]
        self.edit_id = it["id"]
        self.input_var.set(it["text"])
        self.add_btn.configure(text="保存")
        self.input.focus_set()
        self.input.icursor("end")

    def cancel_edit(self):
        self.edit_id = None
        self.input_var.set("")
        try:
            self.add_btn.configure(text="添加")
        except Exception:
            pass

    def delete_row(self, idx):
        if idx is None or idx < 0 or idx >= len(self.visible):
            return
        rid = self.visible[idx]["id"]
        for coll in (self.store.items, self.store.history):
            for i, x in enumerate(coll):
                if x["id"] == rid:
                    coll.pop(i)
                    break
        self.store.save()
        self.refresh()
        self.toast("已删除")

    def toggle_star(self, idx):
        if idx is None or idx < 0 or idx >= len(self.visible):
            return
        it = self.visible[idx]
        if self.tab == "history":
            # 历史条目点星标 = 转为固定片段（借鉴 EcoPaste 收藏夹）
            if any(x["text"] == it["text"] for x in self.store.items):
                self.toast("该内容已在片段中")
                return
            self.store.items.insert(0, new_item(it["text"], star=True))
            self.store.save()
            self.refresh()
            self.toast("已加入固定片段并收藏")
            return
        it["star"] = not it.get("star", False)
        self.store.save()
        self.refresh()
        self.toast("已收藏" if it["star"] else "已取消收藏")

    def reorder(self, a, b):
        if self.tab == "history" or a < 0 or b < 0:
            return
        if a >= len(self.visible) or b >= len(self.visible):
            return
        ida, idb = self.visible[a]["id"], self.visible[b]["id"]
        lst = self.store.items
        ia = next((i for i, x in enumerate(lst) if x["id"] == ida), -1)
        ib = next((i for i, x in enumerate(lst) if x["id"] == idb), -1)
        if ia < 0 or ib < 0:
            return
        obj = lst.pop(ia)
        lst.insert(ib, obj)
        self.store.save()
        self.refresh()
        self.toast("顺序已调整")

    def move_row(self, idx, delta):
        self.reorder(idx, max(0, min(len(self.visible) - 1, idx + delta)))

    def set_tag(self, idx):
        if idx is None or idx < 0 or idx >= len(self.visible):
            return
        it = self.visible[idx]
        try:
            v = simpledialog.askstring("设置标签", "输入标签名（留空可清除）",
                                       parent=self.root,
                                       initialvalue=it.get("tag", ""))
        except Exception as e:
            log("set_tag: %r" % (e,))
            return
        if v is None:
            return
        it["tag"] = v.strip()
        self.store.save()
        self.refresh()
        self.toast("标签已设置" if it["tag"] else "标签已清除")

    def clear_history(self):
        self.store.history.clear()
        self.store.save()
        self.refresh()
        self.toast("复制历史已清空")

    # ---- 剪贴板历史 ----
    def _poll_clipboard(self):
        try:
            seq = int(_user32.GetClipboardSequenceNumber())
            if self.last_clip_seq == 0:
                self.last_clip_seq = seq
            elif seq != self.last_clip_seq:
                self.last_clip_seq = seq
                if self.store.settings.get("capture"):
                    t = clip_get()
                    if isinstance(t, str) and t.strip():
                        t = t.strip()
                        own = (self.own_text == t and time.time() - self.own_ts < 2.0)
                        if not own and not is_sensitive(t):
                            self.add_history(t)
        except Exception as e:
            log("poll clipboard: %r" % (e,))
        try:
            self.root.after(400, self._poll_clipboard)
        except Exception:
            pass

    def add_history(self, text):
        h = self.store.history
        if h and h[0]["text"] == text:
            return
        for i, x in enumerate(h):
            if x["text"] == text:
                h.pop(i)
                break
        h.insert(0, new_item(text))
        try:
            limit = int(self.store.settings.get("max_history", 200))
        except Exception:
            limit = 200
        if len(h) > limit:
            del h[limit:]
        self.store.save()
        if self.tab == "history":
            self.refresh()
        else:
            self.update_status()

    # ---- 设置开关 ----
    def toggle_topmost(self):
        s = self.store.settings
        s["topmost"] = not bool(s.get("topmost"))
        self.store.save()
        self.root.attributes("-topmost", bool(s["topmost"]))
        self._refresh_buttons()
        self.toast("窗口置顶: " + ("开" if s["topmost"] else "关"))

    def toggle_capture(self):
        s = self.store.settings
        s["capture"] = not bool(s.get("capture"))
        self.store.save()
        self.toast("自动记录历史: " + ("开" if s["capture"] else "关"))

    def toggle_theme(self):
        s = self.store.settings
        s["theme"] = "light" if s.get("theme") == "dark" else "dark"
        self.store.save()
        self._apply_theme()
        self.toast("已切换主题")

    def toggle_autostart(self):
        on = not autostart_on()
        ok = set_autostart(on)
        self.toast(("开机自启已开启" if on else "开机自启已关闭") if ok else "设置失败，请以普通用户运行")

    def export_items(self):
        try:
            p = filedialog.asksaveasfilename(
                parent=self.root, defaultextension=".txt",
                initialfile="CopyPad-片段-%s.txt" % time.strftime("%Y%m%d"),
                filetypes=[("文本文件", "*.txt")])
            if not p:
                return
            with open(p, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(x["text"] for x in self.store.items))
            self.toast("已导出: " + os.path.basename(p))
        except Exception as e:
            log("export: %r" % (e,))
            self.toast("导出失败")

    def import_items(self):
        try:
            p = filedialog.askopenfilename(parent=self.root,
                                           filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
            if not p:
                return
            with open(p, "r", encoding="utf-8-sig") as f:
                lines = [x.rstrip("\r\n") for x in f]
            n = 0
            for t in lines:
                if t.strip() and not is_sensitive(t):
                    self.store.items.append(new_item(t.strip()))
                    n += 1
            self.store.save()
            self.refresh()
            self.toast("已导入 %d 条" % n)
        except Exception as e:
            log("import: %r" % (e,))
            self.toast("导入失败")

    def show_help(self):
        txt = (
            "全局（任何软件里都能用）\n"
            "  Ctrl+Shift+Space   显示 / 隐藏小窗\n"
            "  Ctrl+Alt+1~9       直接复制第 N 条，不弹窗\n\n"
            "窗口内\n"
            "  单击 / Enter       复制到剪贴板\n"
            "  双击 / Ctrl+Enter  复制并粘贴到刚才的窗口\n"
            "  ↑ ↓               选择条目\n"
            "  输入即搜索        Ctrl+F 聚焦搜索框\n"
            "  F2 / 铅笔图标      编辑   Delete 删除\n"
            "  Esc                隐藏到托盘\n\n"
            "鼠标\n"
            "  拖标题栏移动 · 右下角拖动缩放\n"
            "  拖左侧序号调整顺序 · 星标收藏\n"
            "  托盘右键：置顶 / 自动记录 / 主题 / 开机自启 / 导入导出")
        try:
            if self.root.state() == "withdrawn":
                self.show()
            messagebox.showinfo("CopyPad 快捷键", txt, parent=self.root)
        except Exception as e:
            log("show_help: %r" % (e,))


# ---------------------------------------------------------------- 入口
def excepthook(t, v, tb):
    log("UNCAUGHT:\n" + "".join(traceback.format_exception(t, v, tb)))


def thread_hook(args):
    log("THREAD UNCAUGHT:\n" + "".join(
        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))


def main():
    enable_dpi()
    sys.excepthook = excepthook
    try:
        threading.excepthook = thread_hook
    except Exception:
        pass
    mutex = win32event.CreateMutex(None, 1, MUTEX_NAME)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        h = win32gui.FindWindow(WND_CLASS, "CopyPad")
        if h:
            win32gui.PostMessage(h, WM_SHOW_APP, 0, 0)
        return
    app = App()
    bridge = NativeBridge(app)
    app.bridge = bridge
    bridge.start()
    try:
        app.root.mainloop()
    finally:
        bridge.tray_remove()
        try:
            win32api.CloseHandle(mutex)
        except Exception:
            pass


if __name__ == "__main__":
    main()
