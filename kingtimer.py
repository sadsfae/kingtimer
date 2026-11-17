#!/usr/bin/env python3
"""Alert 48 minutes after King Gragnarr is slain (P99 EQ log watcher)."""

import argparse
import atexit
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import wave
from tkinter import filedialog, messagebox, ttk

CONFIG_PATH = os.path.expanduser("~/.config/gragnar_timer.json")
SOUND_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert.wav")


def load_log_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            path = json.load(f).get("log")
    except (OSError, ValueError):
        return None
    return path if path and os.path.exists(path) else None


def save_log_config(path):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"log": path}, f)


KILL_RE = re.compile(r"king gragnar", re.IGNORECASE)  # matches Gragnar and Gragnarr
STAMP_RE = re.compile(r"\[(.*?)\]")


def fmt_time(sec):
    return f"{sec // 60:02d}:{sec % 60:02d}"


def read_new(path, offset):
    """Return (new_offset, lines) for content appended after offset."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return offset, []
    if size < offset:  # log truncated/recreated
        offset = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        data = f.read()
        pos = f.tell()
    return pos, data.splitlines()


def find_player():
    if shutil.which("mpv"):
        return ["mpv", "--no-video", "--loop-file=inf", "--really-quiet"]
    if shutil.which("mplayer"):
        return ["mplayer", "-loop", "0", "-really-quiet"]
    for cmd in (["paplay"], ["aplay", "-q"], ["play", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def make_alarm_wav(path, rate=22050):
    """Alternating two-tone alarm, ~2 s, loops seamlessly."""
    samples = []

    def tone(freq, dur, vol=0.6):
        n = int(rate * dur)
        fade = max(1, int(rate * 0.005))
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)
            samples.append(vol * env * math.sin(2 * math.pi * freq * i / rate))

    for _ in range(4):
        tone(800.0, 0.25)
        tone(1000.0, 0.25)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *[int(s * 32767) for s in samples]))


class GragnarApp:
    def __init__(self, root, log_path, alert_seconds, alert_early=20):
        self.root = root
        self.log_path = log_path
        self.alert_seconds = alert_seconds
        self.alert_early = alert_early
        self.watching = False
        self.offset = 0
        self.deadline = None
        self.alert_open = False
        self.alert_dialog = None
        self.stop_sound = None
        self.sound_thread = None
        self.player = find_player()
        self.notifier = shutil.which("omarchy-notification-send") or shutil.which("notify-send")
        self.dark = False
        self.colors = {
            "light": {"bg": "#f2f2f2", "fg": "#1c1c1c", "muted": "#5f5f5f", "btn": "#e0e0e0", "btn_active": "#cfcfcf"},
            "dark": {"bg": "#232323", "fg": "#ececec", "muted": "#a8a8a8", "btn": "#3a3a3a", "btn_active": "#4a4a4a"},
        }
        self.current_colors = self.colors["light"]
        if os.path.exists(SOUND_PATH):
            self.wav_path = SOUND_PATH
            self._owns_wav = False
        else:
            fd, self.wav_path = tempfile.mkstemp(prefix="gragnar-", suffix=".wav")
            os.close(fd)
            make_alarm_wav(self.wav_path)
            self._owns_wav = True
        atexit.register(self._cleanup)
        self._build_ui()
        self.root.after(250, self._poll)

    def _build_ui(self):
        self.root.title("Gragnar Timer")
        self.root.resizable(False, False)
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure("Start.TButton", background="#43a047", foreground="#ffffff", padding=(16, 6))
        self.style.map("Start.TButton", background=[("active", "#2e7d32")])
        self.style.configure("Stop.TButton", background="#e53935", foreground="#ffffff", padding=(16, 6))
        self.style.map("Stop.TButton", background=[("active", "#b71c1c")])

        frame = ttk.Frame(self.root, padding=8)
        frame.pack(fill="both", expand=True)

        self.time_var = tk.StringVar(value="--:--")
        self.time_label = tk.Label(frame, textvariable=self.time_var, font=("DejaVu Sans", 18, "bold"))
        self.time_label.pack(side="left")

        self.status_var = tk.StringVar(
            value="No log file - click the gear to pick your character's log" if not self.log_path else "Not watching"
        )
        self.status_label = tk.Label(frame, textvariable=self.status_var, font=("DejaVu Sans", 9))
        self.status_label.pack(side="left", padx=(10, 0))

        self.gear_btn = ttk.Button(frame, text="\u2699", width=2, command=self.pick_log)
        self.gear_btn.pack(side="right", padx=(0, 4))
        self.moon_btn = ttk.Button(frame, text="\u263e", width=2, command=self.toggle_theme)
        self.moon_btn.pack(side="right")
        self.toggle_btn = ttk.Button(frame, text="Start", style="Start.TButton", command=self.toggle)
        self.toggle_btn.pack(side="right", padx=(4, 0))
        self.toggle_btn.focus_set()
        self._apply_theme()

    def start(self):
        if self.watching:
            return
        if not self.log_path:
            self.status_var.set("No log file - click the gear to pick your character's log")
            messagebox.showwarning(
                "No log file", "Pick your character's EQ log file with the gear button first."
            )
            return
        if not os.path.exists(self.log_path):
            self.status_var.set("Log file not found - is EQ logging (/log)?")
            return
        with open(self.log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            self.offset = f.tell()
        self.watching = True
        self.deadline = None
        self.time_var.set("--:--")
        self.status_var.set("Watching for the kill message...")
        self.toggle_btn.configure(text="Stop", style="Stop.TButton")
        print(f"[gragnar] watching {self.log_path}", flush=True)

    def stop(self):
        self.watching = False
        self.deadline = None
        self._stop_sound()
        if self.alert_dialog is not None:
            self.alert_dialog.destroy()
            self.alert_dialog = None
        self.alert_open = False
        self.time_var.set("--:--")
        self.status_var.set("Not watching")
        self.root.title("Gragnar Timer")
        self.toggle_btn.configure(text="Start", style="Start.TButton")
        print("[gragnar] stopped", flush=True)

    def toggle(self):
        self.start() if not self.watching else self.stop()

    def toggle_theme(self):
        self.dark = not self.dark
        self._apply_theme()

    def _apply_theme(self):
        c = self.colors["dark" if self.dark else "light"]
        self.current_colors = c
        self.root.configure(bg=c["bg"])
        self.style.configure("TFrame", background=c["bg"])
        self.style.configure("TButton", background=c["btn"], foreground=c["fg"], padding=(6, 2))
        self.style.map("TButton", background=[("active", c["btn_active"]), ("pressed", c["btn_active"])])
        self.time_label.configure(bg=c["bg"], fg=c["fg"])
        self.status_label.configure(bg=c["bg"], fg=c["muted"])

    def pick_log(self):
        log_dir = (
            os.path.dirname(self.log_path)
            if self.log_path
            else os.path.expanduser("~/.wine/drive_c/Program Files/Everquest_P99/Logs")
        )
        path = filedialog.askopenfilename(
            title="Select EQ log file",
            initialdir=log_dir if os.path.isdir(log_dir) else None,
            filetypes=[("EQ logs", "eqlog_*.txt"), ("All files", "*.*")],
        )
        if path:
            self.set_log(path)
            print(f"[gragnar] log set to {path}", flush=True)

    def set_log(self, path):
        self.log_path = path
        save_log_config(path)
        if self.watching:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                self.offset = f.tell()
            if self.deadline is None:
                self.status_var.set("Watching for the kill message...")
        else:
            self.status_var.set("Log set - press Start to watch")

    def _poll(self):
        if self.watching:
            self.offset, lines = read_new(self.log_path, self.offset)
            for line in lines:
                if "slain" in line and KILL_RE.search(line):
                    m = STAMP_RE.match(line)
                    stamp = m.group(1) if m else time.strftime("%H:%M:%S")
                    if self.alert_open:
                        self.dismiss_alert()
                    self.deadline = time.time() + self.alert_seconds
                    self.status_var.set(f"Slain at {stamp} - respawn in {fmt_time(self.alert_seconds)}")
                    print(f"[gragnar] slain detected at {stamp}", flush=True)
                    break
            if not self.alert_open and self.deadline is not None:
                rem = int(self.deadline - time.time())
                self.time_var.set(fmt_time(max(rem, 0)))
                if rem <= self.alert_early:
                    self._alert(max(rem, 0))
        self.root.after(250, self._poll)

    def _alert(self, rem):
        if self.alert_open:
            return
        self.alert_open = True
        self.time_var.set(fmt_time(max(rem, 0)))
        self.status_var.set(f"KING GRAGNARR IN {self.alert_early} SECONDS!")
        self.root.title("!!! KING GRAGNARR IN 20 SECONDS !!!")
        self.stop_sound = threading.Event()
        self.sound_thread = threading.Thread(target=self._sound_loop, daemon=True)
        self.sound_thread.start()
        if self.notifier:
            subprocess.Popen(
                [self.notifier, "-u", "critical", "KING GRAGNARR IN 20 SECONDS", "Click OK in Kingtimer to stop the alarm"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        print("[gragnar] ALERT - timer done", flush=True)

        c = self.current_colors
        dlg = tk.Toplevel(self.root)
        self.alert_dialog = dlg
        dlg.title("King Gragnarr!")
        dlg.transient(self.root)
        dlg.attributes("-topmost", True)
        dlg.resizable(False, False)
        dlg.configure(bg=c["bg"])
        tk.Label(
            dlg,
            text=f"KING GRAGNARR IN {self.alert_early} SECONDS",
            font=("DejaVu Sans", 18, "bold"),
            fg="#e5484d",
            bg=c["bg"],
        ).pack(padx=28, pady=(20, 4))
        tk.Label(
            dlg,
            text=f"{self.alert_seconds // 60} minutes have passed since the kill - get ready!",
            font=("DejaVu Sans", 11),
            fg=c["fg"],
            bg=c["bg"],
        ).pack(pady=(0, 14))
        ok = ttk.Button(dlg, text="OK", command=self.dismiss_alert)
        ok.pack(pady=(0, 18))
        dlg.protocol("WM_DELETE_WINDOW", self.dismiss_alert)
        ok.focus_set()
        dlg.bind("<Return>", lambda e: self.dismiss_alert())
        dlg.grab_set()

    def dismiss_alert(self):
        self._stop_sound()
        self.alert_open = False
        self.deadline = None
        if self.alert_dialog is not None:
            self.alert_dialog.destroy()
            self.alert_dialog = None
        self.root.title("Gragnar Timer")
        self.time_var.set("--:--")
        self.status_var.set("Watching for the next kill...")
        print("[gragnar] alarm dismissed", flush=True)

    def _sound_loop(self):
        ev = self.stop_sound
        while not ev.is_set():
            p = subprocess.Popen(self.player + [self.wav_path])
            while p.poll() is None:
                if ev.is_set():
                    p.terminate()
                    break
                time.sleep(0.1)

    def _stop_sound(self):
        if self.stop_sound is not None:
            self.stop_sound.set()
            self.stop_sound = None

    def _cleanup(self):
        self._stop_sound()
        if self._owns_wav:
            try:
                os.unlink(self.wav_path)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="Alert 48 minutes after King Gragnarr is slain")
    parser.add_argument("--log", default=load_log_config())
    parser.add_argument("--alert-seconds", type=int, default=2880)
    args = parser.parse_args()
    root = tk.Tk(className="gragnar_timer")
    GragnarApp(root, args.log, args.alert_seconds)
    root.mainloop()


if __name__ == "__main__":
    main()
