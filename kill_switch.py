"""Windows focus detection and destruction dialog for the doomscroller."""

import ctypes
from ctypes import wintypes
import math
import multiprocessing
import time
import tkinter as tk


COUNTDOWN_SECONDS = 15
POLL_MS = 20


class Windows:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.window_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = (self.window_callback, wintypes.LPARAM)
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.SetForegroundWindow.argtypes = (wintypes.HWND,)
        self.user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.user.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.user.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        self.user.FindWindowW.restype = wintypes.HWND
        self.user.ShowWindowAsync.argtypes = (wintypes.HWND, ctypes.c_int)
        self.user.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self.kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)

    def pid(self, window):
        pid = wintypes.DWORD()
        if window:
            self.user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        return pid.value

    def shortcut_down(self):
        # Virtual key codes for Ctrl, Shift and Q. Reading them consumes no key events.
        return all(self.user.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x10, 0x51))

    def hide_app_windows(self, chrome_pid, preview, hidden):
        if preview and self.user.IsWindowVisible(preview):
            hidden[preview] = self.pid(preview)
            self.user.ShowWindowAsync(preview, 0)  # SW_HIDE
        if not chrome_pid:
            return

        @self.window_callback
        def hide(window, _):
            if self.user.IsWindowVisible(window) and self.pid(window) == chrome_pid:
                hidden[window] = chrome_pid
                self.user.ShowWindowAsync(window, 0)
            return True

        self.user.EnumWindows(hide, 0)


class DestructionDialog:
    def __init__(self, root, resume):
        self.root = root
        self.resume = resume
        self.deadline = None
        root.title("Kill Switch")
        root.configure(bg="#10090c", highlightbackground="#e63c51", highlightthickness=2)
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", lambda: None)

        tk.Label(root, text="ENTER DESTRUCTION CODE:", bg="#10090c", fg="#fff0f2",
                 font=("Segoe UI", 16, "bold")).pack(pady=(20, 4))
        self.timer = tk.Label(root, bg="#10090c", fg="#ff5268",
                              font=("Consolas", 48, "bold"))
        self.timer.pack()
        self.entry = tk.Entry(root, show="*", bg="#29151a", fg="#fff0f2",
                              insertbackground="#fff0f2", font=("Consolas", 18),
                              justify="center", width=22)
        self.entry.pack(pady=(6, 8), ipady=5)
        self.entry.bind("<Return>", self.verify)
        self.error = tk.Label(root, bg="#10090c", fg="#ff5268", font=("Segoe UI", 11, "bold"))
        self.error.pack()

    def show(self):
        self.deadline = time.monotonic() + COUNTDOWN_SECONDS
        self.entry.delete(0, tk.END)
        self.error.config(text="")
        width, height = 420, 245
        x = (self.root.winfo_screenwidth() - width) // 2
        y = (self.root.winfo_screenheight() - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.update_countdown()
        self.root.deiconify()
        self.entry.focus_force()

    def update_countdown(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.deadline = None
            self.root.withdraw()
            self.resume()
        else:
            self.timer.config(text=f"{math.ceil(remaining):02d}")

    def verify(self, _):
        if self.deadline is None:
            return "break"
        if time.monotonic() >= self.deadline:
            self.update_countdown()
        elif self.entry.get() == "sih":
            self.root.quit()
        else:
            self.error.config(text="INVALID DESTRUCTION CODE")
            self.entry.delete(0, tk.END)
        return "break"


def run_with_kill_switch(run, preview, preview_title):
    windows = Windows()
    root = tk.Tk()
    root.withdraw()
    context = multiprocessing.get_context("spawn")
    paused = context.Event()
    stopping = context.Event()
    chrome_pid = context.Value("L", 0, lock=False)
    ready = context.Event()
    worker = context.Process(target=run, args=(preview, paused, stopping, chrome_pid, ready))
    hidden = {}
    previous_foreground = None
    shortcut_was_down = False

    def resume():
        for window, pid in hidden.items():
            if windows.pid(window) == pid:
                windows.user.ShowWindowAsync(window, 8)  # SW_SHOWNA
        hidden.clear()
        if previous_foreground:
            windows.user.SetForegroundWindow(previous_foreground)
        paused.clear()

    dialog = DestructionDialog(root, resume)
    job = windows.kernel.CreateJobObjectW(None, None)
    if not job:
        root.destroy()
        raise ctypes.WinError(ctypes.get_last_error())

    def poll():
        nonlocal previous_foreground, shortcut_was_down
        if not worker.is_alive() and not paused.is_set():
            root.quit()
            return
        preview_window = windows.user.FindWindowW(None, preview_title) if preview else None
        if windows.pid(preview_window) != worker.pid:
            preview_window = None
        browser_pid = chrome_pid.value
        shortcut_down = windows.shortcut_down()
        if paused.is_set():
            windows.hide_app_windows(browser_pid, preview_window, hidden)
            dialog.update_countdown()
        elif shortcut_down and not shortcut_was_down:
            foreground = windows.user.GetForegroundWindow()
            if foreground and (foreground == preview_window or
                               (browser_pid and windows.pid(foreground) == browser_pid)):
                paused.set()
                previous_foreground = foreground
                windows.hide_app_windows(browser_pid, preview_window, hidden)
                dialog.show()
        shortcut_was_down = shortcut_down
        root.after(POLL_MS, poll)

    try:
        worker.start()
        # Contain only this run's worker and the browser processes it starts.
        if not windows.kernel.AssignProcessToJobObject(job, worker.sentinel):
            error = ctypes.get_last_error()
            worker.terminate()
            raise ctypes.WinError(error)
        ready.set()
        root.after(POLL_MS, poll)
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        root.destroy()
        stopping.set()
        paused.set()
        if worker.pid is not None:
            worker.join(timeout=1)
            windows.kernel.TerminateJobObject(job, 1)
            worker.join()
        windows.kernel.CloseHandle(job)
    if not dialog.deadline and worker.exitcode not in (None, 0):
        raise SystemExit(worker.exitcode)
