"""Mouse click helpers for quiz automation."""

import logging
import os
import random
import subprocess
import time
from pathlib import Path

import pyautogui

try:
    import win32api
    import win32con
    import win32gui
except ImportError:
    win32api = None
    win32con = None
    win32gui = None

logger = logging.getLogger(__name__)


def _run_subprocess_no_window(args, **kwargs):
    """Run a subprocess without flashing a console window on Windows."""
    if os.name == "nt":
        kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(args, **kwargs)


pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


class Clicker:
    """Perform clicks with small randomized offsets and optional adb backend."""

    def __init__(
        self,
        click_delay: float = 0.3,
        random_offset: int = 5,
        restore_mouse_position: bool = True,
        click_mode: str = "mouse",
        mumu_adb_path: str = "",
        mumu_adb_serial: str = "",
        mumu_device_width: int = 0,
        mumu_device_height: int = 0,
    ):
        self.click_delay = click_delay
        self.random_offset = random_offset
        self.restore_mouse_position = restore_mouse_position
        self.click_mode = click_mode
        self.mumu_adb_path = mumu_adb_path
        self.mumu_adb_serial = mumu_adb_serial
        self.mumu_device_width = mumu_device_width
        self.mumu_device_height = mumu_device_height
        self._mumu_adb_connected = False

    def set_mumu_adb_path(self, path: str):
        """Update the MuMu adb executable path at runtime."""
        path_text = (path or "").strip()
        if path_text == self.mumu_adb_path:
            return
        self.mumu_adb_path = path_text
        self._mumu_adb_connected = False

    def set_mumu_adb_serial(self, serial: str):
        """Update the MuMu adb device serial at runtime."""
        serial_text = (serial or "").strip()
        if serial_text == self.mumu_adb_serial:
            return
        self.mumu_adb_serial = serial_text
        self._mumu_adb_connected = False

    def click_at(self, x: int, y: int, hwnd: int | None = None, delay_override: float | None = None):
        """Click at the given screen coordinate with bounded random offset."""
        offset_x = self._sample_normal_offset()
        offset_y = self._sample_normal_offset()

        target_x = x + offset_x
        target_y = y + offset_y

        click_delay = self.click_delay if delay_override is None else max(0.0, float(delay_override))
        time.sleep(click_delay)

        if self.click_mode == "mumu_adb" and hwnd:
            if self._click_by_mumu_adb(hwnd, target_x, target_y):
                logger.info(f"MuMu adb click: ({target_x}, {target_y}) serial={self.mumu_adb_serial}")
            else:
                logger.warning("MuMu adb click failed")
            return

        if self.click_mode == "window_message" and hwnd:
            if self._click_by_window_message(hwnd, target_x, target_y):
                logger.info(f"Window message click: ({target_x}, {target_y}) hwnd={hwnd}")
                return
            logger.warning("Window message click failed, falling back to mouse")

        self._click_by_mouse(target_x, target_y)
        logger.info(f"Mouse click: ({target_x}, {target_y})")

    def _sample_normal_offset(self) -> int:
        """Sample a truncated normal offset centered at 0."""
        radius = max(0, int(self.random_offset))
        if radius <= 0:
            return 0

        sigma = max(1.0, radius / 3.0)
        sample = 0.0
        for _ in range(8):
            sample = random.gauss(0.0, sigma)
            if abs(sample) <= radius:
                return int(round(sample))

        sample = max(-radius, min(radius, sample))
        return int(round(sample))

    def _click_by_mouse(self, x: int, y: int):
        """Click using the system mouse."""
        prev_pos = None
        if self.restore_mouse_position:
            try:
                prev_pos = pyautogui.position()
            except Exception:
                prev_pos = None

        pyautogui.click(x, y)

        if prev_pos is not None:
            try:
                pyautogui.moveTo(prev_pos.x, prev_pos.y)
            except Exception:
                pass

    def _click_by_window_message(self, hwnd: int, screen_x: int, screen_y: int) -> bool:
        """Click via window messages without moving the system cursor."""
        if not hwnd or not win32gui or not win32api or not win32con:
            return False

        try:
            client_x, client_y = win32gui.ScreenToClient(hwnd, (screen_x, screen_y))
            if client_x < 0 or client_y < 0:
                return False

            target_hwnds = [hwnd]
            try:
                child = win32gui.ChildWindowFromPointEx(
                    hwnd,
                    (client_x, client_y),
                    win32con.CWP_SKIPINVISIBLE | win32con.CWP_SKIPDISABLED,
                )
                if child and child not in target_hwnds:
                    target_hwnds.insert(0, child)
            except Exception:
                pass

            for target_hwnd in target_hwnds:
                target_client_x, target_client_y = win32gui.ScreenToClient(target_hwnd, (screen_x, screen_y))
                if target_client_x < 0 or target_client_y < 0:
                    continue

                lparam = win32api.MAKELONG(target_client_x, target_client_y)
                try:
                    hit_test = win32gui.SendMessage(target_hwnd, win32con.WM_NCHITTEST, 0, lparam)
                except Exception:
                    hit_test = win32con.HTCLIENT

                try:
                    win32gui.SendMessage(
                        target_hwnd,
                        win32con.WM_MOUSEACTIVATE,
                        hwnd,
                        win32api.MAKELONG(hit_test, win32con.WM_LBUTTONDOWN),
                    )
                except Exception:
                    pass

                win32gui.SendMessage(
                    target_hwnd,
                    win32con.WM_SETCURSOR,
                    target_hwnd,
                    win32api.MAKELONG(hit_test, win32con.WM_MOUSEMOVE),
                )
                win32gui.SendMessage(target_hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
                win32gui.SendMessage(target_hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
                time.sleep(0.03)
                win32gui.SendMessage(target_hwnd, win32con.WM_LBUTTONUP, 0, lparam)

            return True
        except Exception as exc:
            logger.warning(f"Window message click failed: {exc}")
            return False

    def _click_by_mumu_adb(self, hwnd: int, screen_x: int, screen_y: int) -> bool:
        """Click via MuMu adb without using the system cursor."""
        if not hwnd or not win32gui:
            return False

        adb_exe = Path(self.mumu_adb_path)
        if not adb_exe.exists() or not self.mumu_adb_serial:
            logger.warning("MuMu adb is not fully configured")
            return False

        if not self._ensure_mumu_adb_connected():
            return False

        try:
            client_x, client_y = win32gui.ScreenToClient(hwnd, (screen_x, screen_y))
            _left, _top, client_width, client_height = win32gui.GetClientRect(hwnd)
            if client_width <= 0 or client_height <= 0:
                return False

            tap_x = round(client_x * self.mumu_device_width / client_width)
            tap_y = round(client_y * self.mumu_device_height / client_height)
            tap_x = max(0, min(tap_x, self.mumu_device_width - 1))
            tap_y = max(0, min(tap_y, self.mumu_device_height - 1))

            result = _run_subprocess_no_window(
                [
                    str(adb_exe),
                    "-s",
                    self.mumu_adb_serial,
                    "shell",
                    "input",
                    "tap",
                    str(tap_x),
                    str(tap_y),
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(f"MuMu adb tap failed: {result.stderr.strip() or result.stdout.strip()}")
                self._mumu_adb_connected = False
                return False

            logger.info(f"MuMu adb tap: client=({client_x}, {client_y}) device=({tap_x}, {tap_y})")
            return True
        except Exception as exc:
            logger.warning(f"MuMu adb click error: {exc}")
            self._mumu_adb_connected = False
            return False

    def _ensure_mumu_adb_connected(self) -> bool:
        """Ensure the configured MuMu adb device is connected."""
        if self._mumu_adb_connected:
            return True

        adb_exe = Path(self.mumu_adb_path)
        try:
            result = _run_subprocess_no_window(
                [str(adb_exe), "connect", self.mumu_adb_serial],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            output = f"{result.stdout}\n{result.stderr}".lower()
            if result.returncode == 0 and ("connected" in output or "already connected" in output):
                self._mumu_adb_connected = True
                return True

            logger.warning(f"MuMu adb connect failed: {output.strip()}")
            return False
        except Exception as exc:
            logger.warning(f"MuMu adb connect error: {exc}")
            return False
