"""DragonSword Awakening read-only live position tracker.

Reads the local game's Unreal Engine object chain with ReadProcessMemory.
It never writes to or injects code into the game process.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import struct
import subprocess
import time
import webbrowser
from ctypes import wintypes
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from pathlib import Path
from threading import Lock, Thread


PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

PROCESS_NAME = "DSClient-Win64-Shipping.exe"
GENGINE_RVA = 0x93F0510
GENGINE_SCAN_RADIUS = 0x40000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
                ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
                ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
                ("szModule", wintypes.WCHAR * 256), ("szExePath", wintypes.WCHAR * 260)]


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.OpenProcess.restype = wintypes.HANDLE
k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def find_pid() -> int | None:
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == PROCESS_NAME.lower():
                return int(entry.th32ProcessID)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return None


def module_base(pid: int) -> int | None:
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == INVALID_HANDLE_VALUE:
        return module_base_fallback(pid)
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Module32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szModule.lower() == PROCESS_NAME.lower():
                return ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value
            ok = k32.Module32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return module_base_fallback(pid)


def module_base_fallback(pid: int) -> int | None:
    """Some protected games deny module snapshots but expose MainModule read-only."""
    command = (f"$p=Get-Process -Id {pid} -ErrorAction Stop; "
               "$p.MainModule.BaseAddress.ToInt64()")
    try:
        value = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", command],
            text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        return int(value)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class GameReader:
    def __init__(self, pid: int, base: int):
        self.pid = pid
        self.base = base
        self.handle = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.engine_address = self._resolve_engine_address()

    def close(self):
        if self.handle:
            k32.CloseHandle(self.handle)
            self.handle = None

    def read(self, address: int, size: int) -> bytes:
        if not address or address < 0x10000:
            raise RuntimeError("invalid pointer")
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got))
        if not ok or got.value != size:
            raise RuntimeError(f"memory read failed at 0x{address:X}")
        return buf.raw

    def ptr(self, address: int) -> int:
        value = struct.unpack("<Q", self.read(address, 8))[0]
        if not 0x10000 < value < 0x0000800000000000:
            raise RuntimeError("pointer chain is temporarily unavailable")
        return value

    def _position_from_engine_address(self, engine_address: int) -> tuple[float, float, float]:
        engine = self.ptr(engine_address)
        viewport = self.ptr(engine + 0xA58)
        world = self.ptr(viewport + 0x78)
        game_instance = self.ptr(viewport + 0x80)
        players = self.ptr(game_instance + 0x38)
        local_player = self.ptr(players)
        controller = self.ptr(local_player + 0x30)
        pawn = self.ptr(controller + 0x2D8)
        root = self.ptr(pawn + 0x1A0)
        values = struct.unpack("<ddd", self.read(root + 0x128, 24))
        if not all(math.isfinite(value) and abs(value) < 1e9 for value in values):
            raise RuntimeError("invalid coordinate values")
        return values

    def _resolve_engine_address(self) -> int:
        """Locate GEngine near the known RVA when a game patch shifts globals."""
        hinted_address = self.base + GENGINE_RVA
        try:
            self._position_from_engine_address(hinted_address)
            return hinted_address
        except RuntimeError:
            pass

        start = hinted_address - GENGINE_SCAN_RADIUS
        data = self.read(start, GENGINE_SCAN_RADIUS * 2)
        for offset in range(0, len(data) - 8, 8):
            candidate = struct.unpack_from("<Q", data, offset)[0]
            if not 0x10000 < candidate < 0x0000800000000000:
                continue
            address = start + offset
            try:
                self._position_from_engine_address(address)
                return address
            except RuntimeError:
                continue
        raise RuntimeError("game engine pointer not found; a tracker update may be required")

    def sample(self) -> dict:
        # Resolve the complete chain on every sample so map changes are handled.
        x, y, z = self._position_from_engine_address(self.engine_address)
        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "meters": {"x": x / 100.0, "y": y / 100.0, "z": z / 100.0},
        }


def write_json(path: Path, value: dict):
    # A PID-specific temporary name avoids collisions if the VS Code task is
    # accidentally started twice. Windows scanners may also hold a file for a
    # few milliseconds, so retry the atomic replacement briefly.
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    last_error = None
    for attempt in range(6):
        try:
            temp.write_text(payload, encoding="utf-8")
            os.replace(temp, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.02 * (attempt + 1))
    raise last_error


_state_lock = Lock()
_public_state = {"status": "waiting"}


def set_public_state(value: dict):
    global _public_state
    with _state_lock:
        _public_state = value


class TrackerRequestHandler(BaseHTTPRequestHandler):
    """Expose only the minimum position JSON endpoint."""

    def do_GET(self):
        if urlparse(self.path).path != "/position":
            self.send_error(404)
            return
        with _state_lock:
            payload = json.dumps(_public_state, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        if urlparse(self.path).path != "/position":
            self.send_error(404)
            return
        self.send_response(204)
        self.end_headers()

    def end_headers(self):
        origin = self.headers.get("Origin", "")
        hostname = (urlparse(origin).hostname or "").lower()
        if hostname in {"127.0.0.1", "localhost", "dsmaps.com", "www.dsmaps.com"} or hostname.endswith((".replit.dev", ".replit.app")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            if self.headers.get("Access-Control-Request-Private-Network", "").lower() == "true":
                self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_args):
        pass


def serve(port: int):
    server = ThreadingHTTPServer(("127.0.0.1", port), TrackerRequestHandler)
    server.daemon_threads = True
    Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    parser = argparse.ArgumentParser(description="DragonSword read-only position tracker")
    parser.add_argument("--interval", type=float, default=0.25, help="sample interval in seconds")
    parser.add_argument("--port", type=int, default=8765, help="local viewer port (0 disables it)")
    parser.add_argument("--open", action="store_true", help="open the viewer in the default browser")
    args = parser.parse_args()
    root_dir = Path(__file__).resolve().parent
    output = root_dir / "current_position.json"
    if args.port:
        server = serve(args.port)
        if args.open:
            Thread(target=lambda: (time.sleep(0.5), webbrowser.open(f"http://127.0.0.1:{args.port}/")),
                   daemon=True).start()

    reader = None
    last_line = None
    print("Waiting for DragonSword Awakening. Press Ctrl+C to stop.")
    try:
        while True:
            try:
                pid = find_pid()
                if not pid:
                    raise RuntimeError("game is not running")
                if reader is None or reader.pid != pid:
                    if reader:
                        reader.close()
                    base = module_base(pid)
                    if not base:
                        raise RuntimeError("game module not found")
                    reader = GameReader(pid, base)
                data = reader.sample()
                set_public_state(data)
                write_json(output, data)
                p = data["meters"]
                line = f"X {p['x']:10.2f} m  Y {p['y']:10.2f} m  Z {p['z']:8.2f} m"
            except Exception as exc:
                line = f"Waiting: {exc}"
                waiting = {"status": "waiting", "timestamp": datetime.now(timezone.utc).isoformat()}
                set_public_state(waiting)
                write_json(output, waiting)
                if reader and not find_pid():
                    reader.close(); reader = None
            if line != last_line:
                print(line, flush=True)
                last_line = line
            time.sleep(max(0.05, args.interval))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if reader:
            reader.close()


if __name__ == "__main__":
    main()
