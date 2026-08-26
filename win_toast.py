"""Always-on-top, non-activating recording/result toast for the Windows
tray client (#16) -- a small custom popup window, not a Tkinter one.

Runs on its own dedicated thread with its own Win32 message loop so it
never shares thread affinity with pystray's icon loop or the existing
Tk-based "Enter new server..." dialog in tray_client.py -- a bug here
can't hang or corrupt either of those (see #16 design discussion: reusing
Tk would have required moving pystray to run_detached() and marshaling
every existing dialog handler onto Tk's thread, real regression risk to
code that already works).

Built on raw ctypes against user32/gdi32 (a layered window, ULW_ALPHA),
not pywin32 -- the handful of Win32 calls needed are well-documented and
this avoids adding a new dependency.

Content is pre-rendered once with PIL into a handful of fixed RGBA
frames (listening pulse x2, copied, no-speech, error) and pushed to the
window via UpdateLayeredWindow -- the toast never shows arbitrary text
(no live transcript preview, per the #16 spec), so there's no runtime
text layout to get right in GDI.
"""

import ctypes
import queue
import threading
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Independent WinDLL handles, deliberately NOT ctypes.windll.user32 et al.
# -- that accessor is a process-wide cache, and pynput (imported by
# client.py) sets its own argtypes on the exact same shared GetMessageW/
# PostMessageW/etc. function objects. Setting ours there last would
# silently overwrite pynput's, corrupting its message loop for the rest
# of the process's life -- confirmed hands-on: pynput swallows the
# resulting ArgumentError with a bare `except: pass` in its listener
# thread, so the hotkey just stops firing with no error anywhere. A
# fresh WinDLL() call gets our own private function-wrapper objects
# pointing at the same DLLs, so our argtypes can't leak into pynput's.
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

DWMWA_TRANSITIONS_FORCEDISABLED = 3

ICON_DIR = Path(__file__).resolve().parent / "images"
ICON_SIZE = 64
PULSE_INTERVAL_MS = 700
RESULT_HOLD_MS = 1000
TOP_MARGIN = 16

CHIP_BG = (28, 28, 30, 255)  # fully opaque -- avoid any background bleed-through
CHIP_PAD_X = 18
CHIP_PAD_Y = 14
GAP = 12
TEXT_COLOR = (240, 240, 242, 255)
FONT_SIZE = 15

CLASS_NAME = "KubunDictateToast"
WM_APP_UPDATE = 0x8001
WM_APP_HIDE = 0x8002
TIMER_PULSE = 1
TIMER_HIDE = 2

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE = 0
ULW_ALPHA = 2
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
DIB_RGB_COLORS = 0
BI_RGB = 0
WM_DESTROY = 0x0002
WM_TIMER = 0x0113
MONITOR_DEFAULTTONEAREST = 2
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", ctypes.c_uint32),
    ]


user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_long
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p]
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.MonitorFromWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.MonitorFromWindow.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(SIZE),
    wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(BITMAPINFO), ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


def _fill_frame(img, size):
    img = img.convert("RGBA")
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    scale = min(size / img.width, size / img.height)
    new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    img = img.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - new_size[0]) // 2, (size - new_size[1]) // 2), img)
    return canvas


def _rounded_chip(size, radius, fill):
    chip = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle([(0, 0), (size[0] - 1, size[1] - 1)], radius=radius, fill=fill)
    return chip


def _compose(icon_img, text, font):
    text_w, text_h = (0, 0)
    if text:
        bbox = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    content_w = ICON_SIZE + (GAP + text_w if text else 0)
    content_h = max(ICON_SIZE, text_h)
    w = content_w + CHIP_PAD_X * 2
    h = content_h + CHIP_PAD_Y * 2

    frame = _rounded_chip((w, h), radius=h // 2, fill=CHIP_BG)
    icon_y = (h - ICON_SIZE) // 2
    frame.alpha_composite(icon_img, (CHIP_PAD_X, icon_y))
    if text:
        text_x = CHIP_PAD_X + ICON_SIZE + GAP
        text_y = (h - text_h) // 2
        ImageDraw.Draw(frame).text((text_x, text_y), text, font=font, fill=TEXT_COLOR)
    return frame


def _build_frames():
    try:
        font = ImageFont.truetype("segoeui.ttf", FONT_SIZE)
    except OSError:
        font = ImageFont.load_default()

    icons = {
        state: _fill_frame(Image.open(ICON_DIR / f"kubundictate-{state}-{ICON_SIZE}.png"), ICON_SIZE)
        for state in ("idle", "listening-a", "listening-b")
    }
    return {
        "listening-a": _compose(icons["listening-a"], "Listening...", font),
        "listening-b": _compose(icons["listening-b"], "Listening...", font),
        # Held static (no pulse), same convention as the tray icon itself
        # (_current_icon_state) while awaiting the server's response.
        "transcribing": _compose(icons["listening-a"], "Transcribing...", font),
        "copied": _compose(icons["idle"], "Copied to clipboard", font),
        "no-speech": _compose(icons["idle"], "No speech detected", font),
        "error": _compose(icons["idle"], "Couldn't reach server", font),
    }


def _premultiplied_bgra_bytes(rgba_img):
    arr = np.asarray(rgba_img).astype(np.uint16)
    alpha = arr[..., 3:4]
    premult = (arr[..., :3] * alpha // 255).astype(np.uint8)
    bgra = np.dstack([premult[..., 2], premult[..., 1], premult[..., 0], arr[..., 3].astype(np.uint8)])
    return np.ascontiguousarray(bgra[::-1]).tobytes()  # bottom-up rows, as CreateDIBSection expects


class Toast:
    """Thread-safe: show_listening()/show_result()/hide() may be called
    from any thread. Everything else runs on this instance's own thread.
    """

    def __init__(self):
        self._frames = _build_frames()
        self._pending = queue.Queue()
        self._hwnd = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def show_listening(self):
        self._post(("listening",))

    def show_transcribing(self):
        self._post(("transcribing",))

    def show_result(self, error):
        # error is None for a successful "copied" outcome, else one of
        # "no-speech" / "could not reach server".
        self._post(("result", error))

    def hide(self):
        self._post(("hide",))

    def _post(self, item):
        if self._hwnd is None:
            return
        self._pending.put(item)
        user32.PostMessageW(self._hwnd, WM_APP_UPDATE, 0, 0)

    # -- toast thread --------------------------------------------------

    def _run(self):
        hinst = kernel32.GetModuleHandleW(None)
        wndproc = WNDPROC(self._wndproc)
        self._wndproc_ref = wndproc  # keep alive -- ctypes doesn't retain callback refs
        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = wndproc
        wc.hInstance = hinst
        wc.lpszClassName = CLASS_NAME
        user32.RegisterClassW(ctypes.byref(wc))

        ex_style = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self._hwnd = user32.CreateWindowExW(
            ex_style, CLASS_NAME, "KubunDictate", WS_POPUP,
            0, 0, 1, 1, None, None, hinst, None,
        )
        # DWM can cross-fade content changes on layered windows by default;
        # force instant, non-blended swaps instead so pulse/state repaints
        # never look like they're fading between frames.
        disable = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            self._hwnd, DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(disable), ctypes.sizeof(disable)
        )
        self._pulse_a = True
        self._visible = False
        self._ready.set()

        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, message, wparam, lparam):
        if message == 0x8001:  # WM_APP_UPDATE
            self._drain_pending(hwnd)
            return 0
        if message == WM_TIMER:
            if wparam == TIMER_PULSE:
                self._pulse_a = not self._pulse_a
                self._paint(hwnd, "listening-a" if self._pulse_a else "listening-b")
            elif wparam == TIMER_HIDE:
                user32.KillTimer(hwnd, TIMER_HIDE)
                user32.ShowWindow(hwnd, SW_HIDE)
                self._visible = False
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _drain_pending(self, hwnd):
        try:
            while True:
                item = self._pending.get_nowait()
                kind = item[0]
                if kind == "listening":
                    user32.KillTimer(hwnd, TIMER_HIDE)
                    self._pulse_a = True
                    self._paint(hwnd, "listening-a")
                    user32.SetTimer(hwnd, TIMER_PULSE, PULSE_INTERVAL_MS, None)
                elif kind == "transcribing":
                    user32.KillTimer(hwnd, TIMER_PULSE)
                    user32.KillTimer(hwnd, TIMER_HIDE)
                    self._paint(hwnd, "transcribing")
                elif kind == "result":
                    user32.KillTimer(hwnd, TIMER_PULSE)
                    error = item[1]
                    state = {"no-speech": "no-speech", "could not reach server": "error"}.get(error, "copied")
                    self._paint(hwnd, state)
                    user32.SetTimer(hwnd, TIMER_HIDE, RESULT_HOLD_MS, None)
                elif kind == "hide":
                    user32.KillTimer(hwnd, TIMER_PULSE)
                    user32.KillTimer(hwnd, TIMER_HIDE)
                    user32.ShowWindow(hwnd, SW_HIDE)
                    self._visible = False
        except queue.Empty:
            pass

    def _paint(self, hwnd, state):
        frame = self._frames[state]
        w, h = frame.size
        x, y = self._top_center_position(hwnd, w, h)

        screen_dc = user32.GetDC(None)
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bits_ptr = ctypes.c_void_p()
        hbitmap = gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits_ptr), None, 0)
        pixel_bytes = _premultiplied_bgra_bytes(frame)
        ctypes.memmove(bits_ptr, pixel_bytes, len(pixel_bytes))
        old_bitmap = gdi32.SelectObject(mem_dc, hbitmap)

        size = SIZE(w, h)
        src_pt = wintypes.POINT(0, 0)
        dst_pt = wintypes.POINT(x, y)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        # UpdateLayeredWindow alone repositions, resizes, and repaints the
        # window atomically in one compositor pass -- a follow-up
        # SetWindowPos/ShowWindow on every repaint would be redundant.
        # SetWindowPos still runs, but only once per show (below), to
        # establish topmost z-order and actually map the window the
        # first time.
        user32.UpdateLayeredWindow(hwnd, screen_dc, ctypes.byref(dst_pt), ctypes.byref(size),
                                    mem_dc, ctypes.byref(src_pt), 0, ctypes.byref(blend), ULW_ALPHA)
        if not self._visible:
            user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
            self._visible = True

        gdi32.SelectObject(mem_dc, old_bitmap)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)

    def _top_center_position(self, hwnd, w, h):
        fg = user32.GetForegroundWindow() or hwnd
        hmon = user32.MonitorFromWindow(fg, MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        work = info.rcWork  # already excludes the taskbar on whichever edge it docks to
        x = work.left + (work.right - work.left - w) // 2
        y = work.top + TOP_MARGIN
        return x, y


user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
