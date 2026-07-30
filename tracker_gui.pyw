"""Small Windows GUI for the DSMaps read-only live tracker."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
import urllib.request
import webbrowser
from tkinter import ttk

import tracker


VERSION = "4.0.3"
MANIFEST_URL = "https://dsmaps.com/downloads/live-tracker-manifest.json"
SITE_URL = "https://dsmaps.com/"


def version_key(value: object) -> tuple[int, int, int]:
    parts = []
    for token in str(value).split("."):
        digits = "".join(character for character in token if character.isdigit())
        parts.append(int(digits or 0))
    return tuple((parts + [0, 0, 0])[:3])


class TrackerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.stop_event = threading.Event()
        self.reader = None
        self.server = None
        root.title("DSMaps Live Tracker BETA")
        root.geometry("470x315")
        root.minsize(430, 290)
        root.configure(bg="#09171b")
        root.protocol("WM_DELETE_WINDOW", self.close)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#09171b")
        style.configure("Title.TLabel", background="#09171b", foreground="#f4f8f7", font=("Segoe UI", 17, "bold"))
        style.configure("Eyebrow.TLabel", background="#09171b", foreground="#f0a34d", font=("Segoe UI", 8, "bold"))
        style.configure("Text.TLabel", background="#09171b", foreground="#8da3a4", font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#102329", foreground="#e4efed", font=("Segoe UI", 10, "bold"), padding=12)
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=9)

        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="DSMAPS LIVE TRACKER · BETA", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(frame, text="드래곤소드 실시간 위치 추적", style="Title.TLabel").pack(anchor="w", pady=(4, 16))
        self.status = ttk.Label(frame, text="게임 실행을 확인하고 있습니다.", style="Status.TLabel", anchor="w")
        self.status.pack(fill="x")
        self.detail = ttk.Label(frame, text="게임 캐릭터로 접속한 뒤 DSMaps의 LIVE 버튼을 열어 주세요.", style="Text.TLabel", wraplength=420, justify="left")
        self.detail.pack(anchor="w", pady=(11, 15))
        self.update_button = ttk.Button(frame, text="새 버전 다운로드", command=self.open_update)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", side="bottom")
        ttk.Button(buttons, text="DSMaps 열기", command=lambda: webbrowser.open(SITE_URL)).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ttk.Button(buttons, text="종료", command=self.close).pack(side="left", expand=True, fill="x", padx=(5, 0))
        ttk.Label(frame, text=f"버전 {VERSION} · 읽기 전용 · 로컬 연결", style="Text.TLabel").pack(anchor="w", side="bottom", pady=(0, 10))
        self.update_url = ""

        try:
            self.server = tracker.serve(8765)
        except OSError as exc:
            self.status.configure(text="트래커를 시작할 수 없습니다.")
            self.detail.configure(text=f"8765 포트를 다른 추적기가 사용 중입니다. 기존 프로그램을 종료해 주세요. ({exc})")
        else:
            threading.Thread(target=self.track_loop, daemon=True).start()
        threading.Thread(target=self.check_update, daemon=True).start()
        root.after(150, self.drain_events)

    def track_loop(self):
        while not self.stop_event.is_set():
            try:
                pid = tracker.find_pid()
                if not pid:
                    raise RuntimeError("게임이 실행되지 않았습니다.")
                if self.reader is None or self.reader.pid != pid:
                    if self.reader:
                        self.reader.close()
                    base = tracker.module_base(pid)
                    if not base:
                        raise RuntimeError("게임 모듈을 찾지 못했습니다.")
                    self.reader = tracker.GameReader(pid, base)
                tracker.set_public_state(self.reader.sample())
                self.events.put(("connected", "게임 위치를 정상적으로 읽고 있습니다. DSMaps에서 LIVE 패널을 열어 주세요."))
            except Exception as exc:
                tracker.set_public_state({"status": "waiting"})
                self.events.put(("waiting", str(exc)))
                if self.reader and not tracker.find_pid():
                    self.reader.close()
                    self.reader = None
            self.stop_event.wait(0.25)

    def check_update(self):
        try:
            request = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": f"DSMapsLiveTracker/{VERSION}"})
            with urllib.request.urlopen(request, timeout=5) as response:
                manifest = json.load(response)
            if version_key(manifest.get("version", VERSION)) > version_key(VERSION) and manifest.get("downloadUrl"):
                self.update_url = str(manifest["downloadUrl"])
                self.events.put(("update", f"새 버전 {manifest['version']}을 사용할 수 있습니다."))
        except Exception:
            pass

    def drain_events(self):
        try:
            while True:
                kind, text = self.events.get_nowait()
                if kind == "connected":
                    self.status.configure(text="● 게임 연결됨")
                    self.detail.configure(text=text)
                elif kind == "waiting":
                    self.status.configure(text="○ 게임 접속 대기 중")
                    self.detail.configure(text=text)
                elif kind == "update":
                    self.detail.configure(text=text)
                    self.update_button.pack(fill="x", pady=(0, 8), before=self.detail)
        except queue.Empty:
            pass
        if not self.stop_event.is_set():
            self.root.after(150, self.drain_events)

    def open_update(self):
        if self.update_url:
            webbrowser.open(self.update_url)

    def close(self):
        self.stop_event.set()
        if self.reader:
            self.reader.close()
            self.reader = None
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    TrackerApp(window)
    window.mainloop()
