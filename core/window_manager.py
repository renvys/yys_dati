"""游戏窗口管理与截图工具。"""

import ctypes
import json
import logging
import os
import subprocess
import re

import cv2
import numpy as np

try:
    import win32api
    import win32con
    import win32gui
    import win32process
    import win32ui
except ImportError:
    raise ImportError("请安装 pywin32: pip install pywin32")

logger = logging.getLogger(__name__)


def _run_subprocess_no_window(args, **kwargs):
    """Run a subprocess without flashing a console window on Windows."""
    if os.name == "nt":
        kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(args, **kwargs)


def set_dpi_awareness():
    """启用 DPI 感知，确保窗口坐标准确。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class WindowManager:
    """查找、跟踪并截图目标游戏窗口。"""

    def __init__(
        self,
        title_keywords: list[str],
        mumu_adb_path: str = "",
        mumu_adb_serial: str = "",
        process_keywords: list[str] | None = None,
    ):
        self.title_keywords = title_keywords
        self.process_keywords = process_keywords or []
        self.hwnd = None
        self._window_rect = None  # (左, 上, 右, 下)
        self._self_pid = os.getpid()
        self.mumu_adb_path = mumu_adb_path
        self.mumu_adb_serial = mumu_adb_serial
        self._mumu_adb_connected = False
        self._active_capture_backend = None
        self._preferred_window_title = ""
        self._pid_name_cache: dict[int, str] = {}
        self._pid_command_line_cache: dict[int, str] = {}

    def find_window(self) -> bool:
        """在可见顶层窗口中查找标题包含指定关键词的目标窗口。"""
        if self._is_cached_window_valid():
            return True

        self.hwnd = None
        self._window_rect = None
        for window_info in self.list_matching_windows(prefer_selected=True):
            self.hwnd = window_info["hwnd"]
            self._window_rect = window_info["rect"]
            logger.info(f"找到窗口: '{window_info['title']}' (hwnd={self.hwnd})")
            break
        return self.hwnd is not None

    def _is_cached_window_valid(self) -> bool:
        """检查缓存的 hwnd 是否仍然有效，避免每轮都重新枚举窗口。"""
        if not self.hwnd:
            return False

        try:
            if not win32gui.IsWindow(self.hwnd):
                return False
            if not win32gui.IsWindowVisible(self.hwnd):
                return False

            title = win32gui.GetWindowText(self.hwnd)
            if not title:
                return False
            if self._preferred_window_title and title != self._preferred_window_title:
                return False
            if not self._matches_window(self.hwnd, title):
                return False

            self._window_rect = win32gui.GetWindowRect(self.hwnd)
            return True
        except Exception:
            return False

    def list_matching_windows(self, prefer_selected: bool = False) -> list[dict]:
        """列出当前可见的候选窗口，供 GUI 选择具体 MuMu 实例。"""
        windows: list[dict] = []

        def enum_callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True

            title = win32gui.GetWindowText(hwnd)
            if not title:
                return True

            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == self._self_pid:
                    return True
            except Exception:
                pass

            if prefer_selected and self._preferred_window_title and title != self._preferred_window_title:
                return True

            if not self._matches_window(hwnd, title):
                return True

            try:
                rect = win32gui.GetWindowRect(hwnd)
            except Exception:
                rect = (0, 0, 0, 0)

            left, top, right, bottom = rect
            windows.append(
                {
                    "hwnd": hwnd,
                    "pid": pid,
                    "title": title,
                    "rect": rect,
                    "width": max(0, right - left),
                    "height": max(0, bottom - top),
                    "instance_index": self._get_instance_index(hwnd, pid),
                }
            )
            return True

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception:
            pass

        windows.sort(key=lambda item: (item["title"].lower(), item["hwnd"]))
        return windows

    def _matches_window(self, hwnd: int, title: str) -> bool:
        """判断窗口是否属于目标模拟器实例。"""
        title_text = (title or "").strip()
        process_name = self._get_process_name(hwnd)
        if self.process_keywords and process_name:
            return any(keyword.lower() in process_name.lower() for keyword in self.process_keywords)

        return any(keyword.lower() in title_text.lower() for keyword in self.title_keywords)

    def _get_process_name(self, hwnd: int) -> str:
        """根据窗口句柄获取进程名。"""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return ""

        if pid in self._pid_name_cache:
            return self._pid_name_cache[pid]

        process_name = ""
        process_handle = None
        try:
            access = getattr(win32con, "PROCESS_QUERY_LIMITED_INFORMATION", 0x1000)
            access |= getattr(win32con, "PROCESS_VM_READ", 0x0010)
            process_handle = win32api.OpenProcess(access, False, pid)
            module_path = win32process.GetModuleFileNameEx(process_handle, 0)
            process_name = os.path.splitext(os.path.basename(module_path))[0]
        except Exception:
            process_name = ""
        finally:
            if process_handle:
                try:
                    win32api.CloseHandle(process_handle)
                except Exception:
                    pass

        self._pid_name_cache[pid] = process_name
        return process_name

    def _get_instance_index(self, hwnd: int, pid: int | None = None) -> int | None:
        """根据 MuMuNxDevice 进程命令行解析实例编号。"""
        process_name = self._get_process_name(hwnd)
        if process_name.lower() != "mumunxdevice":
            return None

        actual_pid = pid
        if actual_pid is None:
            try:
                _, actual_pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                return None

        command_line = self._get_process_command_line(actual_pid)
        if not command_line:
            return 0

        match = re.search(r"(?:^|\s)-v\s+(\d+)(?:\s|$)", command_line)
        if match:
            return int(match.group(1))
        return 0

    def _get_process_command_line(self, pid: int) -> str:
        """读取指定 PID 的命令行，并做简单缓存。"""
        if pid in self._pid_command_line_cache:
            return self._pid_command_line_cache[pid]

        command = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.ProcessId -eq {pid} }} | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            payload = (result.stdout or "").strip()
            if not payload:
                self._pid_command_line_cache[pid] = ""
                return ""

            parsed = json.loads(payload)
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else {}

            command_line = str(parsed.get("CommandLine", "") or "")
            self._pid_command_line_cache[pid] = command_line
            return command_line
        except Exception:
            self._pid_command_line_cache[pid] = ""
            return ""

    def set_window_preference(self, hwnd: int | None = None, title: str = ""):
        """设置优先绑定的窗口；未指定时回退为按关键词自动匹配。"""
        self._preferred_window_title = (title or "").strip()
        self.hwnd = hwnd
        self._window_rect = None
        if self.hwnd and self._is_cached_window_valid():
            return
        if self.hwnd:
            self.hwnd = None

    def set_mumu_adb_serial(self, serial: str):
        """运行时切换 MuMu adb 设备。"""
        serial_text = (serial or "").strip()
        if serial_text == self.mumu_adb_serial:
            return
        self.mumu_adb_serial = serial_text
        self._mumu_adb_connected = False

    def set_mumu_adb_path(self, path: str):
        """运行时切换 MuMu adb.exe 路径。"""
        path_text = (path or "").strip()
        if path_text == self.mumu_adb_path:
            return
        self.mumu_adb_path = path_text
        self._mumu_adb_connected = False

    def get_window_rect(self) -> tuple | None:
        """返回窗口位置与尺寸：(左, 上, 宽, 高)。"""
        if not self.hwnd:
            return None

        try:
            rect = win32gui.GetWindowRect(self.hwnd)
            self._window_rect = rect
            left, top, right, bottom = rect
            return (left, top, right - left, bottom - top)
        except Exception as e:
            logger.warning(f"获取窗口位置失败: {e}")
            return None

    def capture_window(self) -> np.ndarray | None:
        """
        截取游戏窗口图像，返回 RGB 格式的 numpy 数组。
        优先尝试 MuMu adb；如果失败，再回退到 PrintWindow 和桌面截图。
        """
        if not self.hwnd:
            return None

        adb_screenshot = self._capture_via_mumu_adb()
        if adb_screenshot is not None:
            return adb_screenshot

        print_window_screenshot = self._capture_via_print_window()
        if print_window_screenshot is not None:
            return print_window_screenshot

        return self._capture_fallback()

    def _capture_via_print_window(self) -> np.ndarray | None:
        """使用 PrintWindow 截图。"""
        if not self.hwnd:
            return None

        try:
            rect = win32gui.GetWindowRect(self.hwnd)
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                logger.warning("窗口尺寸无效")
                return None

            hwnd_dc = win32gui.GetWindowDC(self.hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            result = ctypes.windll.user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), 2)
            if result == 0:
                save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)

            bmp_info = bitmap.GetInfo()
            bmp_str = bitmap.GetBitmapBits(True)
            img = np.frombuffer(bmp_str, dtype=np.uint8).reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
            img_rgb = img[:, :, :3][:, :, ::-1].copy()

            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwnd_dc)
            win32gui.DeleteObject(bitmap.GetHandle())

            if img_rgb.mean() < 5:
                logger.info("PrintWindow 截图全黑")
                return None

            self._set_capture_backend("printwindow", "当前优先使用 PrintWindow 截图")
            return img_rgb
        except Exception as e:
            logger.warning(f"PrintWindow 截图失败: {e}")
            return None

    def _capture_fallback(self) -> np.ndarray | None:
        """最后回退到桌面截图。"""
        try:
            import pyautogui

            rect = self.get_window_rect()
            if not rect:
                return None
            left, top, width, height = rect
            screenshot = pyautogui.screenshot(region=(left, top, width, height))
            return np.array(screenshot)
        except Exception as e:
            logger.error(f"回退截图也失败: {e}")
            return None

    def _capture_via_mumu_adb(self) -> np.ndarray | None:
        """通过 MuMu adb 截图，避免识别依赖窗口必须位于前台。"""
        if not self.hwnd or not self.mumu_adb_path or not self.mumu_adb_serial:
            return None
        if not self._ensure_mumu_adb_connected():
            return None

        try:
            result = _run_subprocess_no_window(
                [
                    self.mumu_adb_path,
                    "-s",
                    self.mumu_adb_serial,
                    "exec-out",
                    "screencap",
                    "-p",
                ],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0 or not result.stdout:
                stderr = result.stderr.decode(errors="ignore").strip()
                logger.warning(f"MuMu adb 截图失败: {stderr}")
                self._mumu_adb_connected = False
                return None

            decoded = cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
            if decoded is None:
                logger.warning("MuMu adb 截图解码失败")
                return None

            client_rgb = cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)
            composed = self._compose_client_screenshot(client_rgb)
            self._set_capture_backend("mumu_adb", "当前优先使用 MuMu adb 截图")
            return composed if composed is not None else client_rgb
        except Exception as e:
            logger.warning(f"MuMu adb 截图异常: {e}")
            self._mumu_adb_connected = False
            return None

    def _compose_client_screenshot(self, client_img: np.ndarray) -> np.ndarray | None:
        """将客户区截图贴回外层窗口画布，兼容现有按窗口比例配置的区域。"""
        if not self.hwnd:
            return None

        try:
            left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
            win_width = right - left
            win_height = bottom - top
            if win_width <= 0 or win_height <= 0:
                return None

            client_left, client_top = win32gui.ClientToScreen(self.hwnd, (0, 0))
            client_rect = win32gui.GetClientRect(self.hwnd)
            client_width = client_rect[2] - client_rect[0]
            client_height = client_rect[3] - client_rect[1]
            if client_width <= 0 or client_height <= 0:
                return None

            resized = cv2.resize(client_img, (client_width, client_height), interpolation=cv2.INTER_LINEAR)
            canvas = np.zeros((win_height, win_width, 3), dtype=np.uint8)
            offset_x = max(0, client_left - left)
            offset_y = max(0, client_top - top)

            paste_width = min(client_width, win_width - offset_x)
            paste_height = min(client_height, win_height - offset_y)
            if paste_width <= 0 or paste_height <= 0:
                return None

            canvas[offset_y:offset_y + paste_height, offset_x:offset_x + paste_width] = resized[:paste_height, :paste_width]
            return canvas
        except Exception as e:
            logger.warning(f"MuMu adb 截图拼接失败: {e}")
            return None

    def _ensure_mumu_adb_connected(self) -> bool:
        """在需要时连接到已配置的 MuMu adb 设备。"""
        if self._mumu_adb_connected:
            return True

        try:
            result = _run_subprocess_no_window(
                [self.mumu_adb_path, "connect", self.mumu_adb_serial],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode(errors="ignore").strip()
                logger.warning(f"MuMu adb 连接失败: {stderr}")
                return False

            self._mumu_adb_connected = True
            return True
        except Exception as e:
            logger.warning(f"MuMu adb 连接异常: {e}")
            return False

    def _set_capture_backend(self, backend: str, message: str):
        """仅在截图后端切换时记录一次日志，避免重复刷屏。"""
        if self._active_capture_backend == backend:
            return
        self._active_capture_backend = backend
        logger.info(message)

    def bring_to_front(self):
        """将窗口置于前台。"""
        if self.hwnd:
            try:
                win32gui.SetForegroundWindow(self.hwnd)
            except Exception as e:
                logger.warning(f"窗口置前失败: {e}")
