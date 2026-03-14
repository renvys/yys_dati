"""鼠标点击模块 - 模拟人类点击操作"""

import os
import random
import subprocess
import time
import logging
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

# 安全设置：鼠标移到屏幕角落可紧急停止
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


class Clicker:
    """模拟鼠标点击，带随机偏移和延时。"""

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
        """
        Args:
            click_delay: 点击前的延时（秒）
            random_offset: 随机偏移像素范围
            restore_mouse_position: 点击后将鼠标恢复到点击前位置，避免遮挡 UI
            click_mode: 点击方式，mouse 或 window_message
            mumu_adb_path: MuMu adb.exe 路径
            mumu_adb_serial: MuMu adb 设备序列
            mumu_device_width: MuMu 当前横屏逻辑宽度
            mumu_device_height: MuMu 当前横屏逻辑高度
        """
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
        """运行时切换 MuMu adb.exe 路径。"""
        path_text = (path or "").strip()
        if path_text == self.mumu_adb_path:
            return
        self.mumu_adb_path = path_text
        self._mumu_adb_connected = False

    def set_mumu_adb_serial(self, serial: str):
        """运行时切换 MuMu adb 设备。"""
        serial_text = (serial or "").strip()
        if serial_text == self.mumu_adb_serial:
            return
        self.mumu_adb_serial = serial_text
        self._mumu_adb_connected = False

    def click_at(self, x: int, y: int, hwnd: int | None = None, delay_override: float | None = None):
        """
        在指定坐标点击，加入随机偏移使操作更自然。

        Args:
            x: 屏幕 X 坐标
            y: 屏幕 Y 坐标
            hwnd: 目标窗口句柄；在 window_message 模式下用于后台点击
            delay_override: 本次点击覆盖默认延时；为 None 时使用全局 click_delay
        """
        offset_x = random.randint(-self.random_offset, self.random_offset)
        offset_y = random.randint(-self.random_offset, self.random_offset)

        target_x = x + offset_x
        target_y = y + offset_y

        click_delay = self.click_delay if delay_override is None else max(0.0, float(delay_override))
        time.sleep(click_delay)

        if self.click_mode == "mumu_adb" and hwnd:
            if self._click_by_mumu_adb(hwnd, target_x, target_y):
                logger.info(f"MuMu adb 点击坐标: ({target_x}, {target_y}) serial={self.mumu_adb_serial}")
            else:
                logger.warning("MuMu adb 点击失败")
            return

        if self.click_mode == "window_message" and hwnd:
            if self._click_by_window_message(hwnd, target_x, target_y):
                logger.info(f"后台点击坐标: ({target_x}, {target_y}) hwnd={hwnd}")
                return
            logger.warning("后台点击失败，回退到真实鼠标点击")

        self._click_by_mouse(target_x, target_y)
        logger.info(f"点击坐标: ({target_x}, {target_y})")

    def _click_by_mouse(self, x: int, y: int):
        """使用系统鼠标执行点击。"""
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
        """通过窗口消息点击，不占用系统鼠标。"""
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
                if child:
                    if child not in target_hwnds:
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

                win32gui.SendMessage(target_hwnd, win32con.WM_SETCURSOR, target_hwnd, win32api.MAKELONG(hit_test, win32con.WM_MOUSEMOVE))
                win32gui.SendMessage(target_hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
                win32gui.SendMessage(target_hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
                time.sleep(0.03)
                win32gui.SendMessage(target_hwnd, win32con.WM_LBUTTONUP, 0, lparam)

            return True
        except Exception as e:
            logger.warning(f"窗口消息点击失败: {e}")
            return False

    def _click_by_mumu_adb(self, hwnd: int, screen_x: int, screen_y: int) -> bool:
        """通过 MuMu 的 adb 点击，不占用系统鼠标。"""
        if not hwnd or not win32gui:
            return False

        adb_exe = Path(self.mumu_adb_path)
        if not adb_exe.exists() or not self.mumu_adb_serial:
            logger.warning("MuMu adb 未配置完整")
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
                logger.warning(f"MuMu adb tap 失败: {result.stderr.strip() or result.stdout.strip()}")
                self._mumu_adb_connected = False
                return False

            logger.info(f"MuMu adb tap: client=({client_x}, {client_y}) device=({tap_x}, {tap_y})")
            return True
        except Exception as e:
            logger.warning(f"MuMu adb 点击异常: {e}")
            self._mumu_adb_connected = False
            return False

    def _ensure_mumu_adb_connected(self) -> bool:
        """确保 MuMu adb 已连接。"""
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

            logger.warning(f"MuMu adb 连接失败: {output.strip()}")
            return False
        except Exception as e:
            logger.warning(f"MuMu adb connect 异常: {e}")
            return False
