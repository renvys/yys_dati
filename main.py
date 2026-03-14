"""阴阳师答题器 - 主程序入口"""

from __future__ import annotations

import logging
import os
import re
import site
import json
import subprocess
import sys
import time
import threading
from collections import OrderedDict, deque
from pathlib import Path


def _bootstrap_project_venv():
    """允许直接运行 `python main.py`，无需手动激活 `.venv`。"""
    project_root = os.path.dirname(os.path.abspath(__file__))
    venv_site_packages = os.path.join(project_root, ".venv", "Lib", "site-packages")
    if not os.path.isdir(venv_site_packages):
        return

    normalized = os.path.normcase(os.path.normpath(venv_site_packages))
    existing = {
        os.path.normcase(os.path.normpath(path))
        for path in sys.path
        if isinstance(path, str) and path
    }
    if normalized not in existing:
        site.addsitedir(venv_site_packages)


_bootstrap_project_venv()

import cv2
import numpy as np
from PIL import Image
from rapidfuzz import fuzz

import config
from core.window_manager import WindowManager, set_dpi_awareness
from core.ocr_engine import OCREngine
from core.question_matcher import QuestionMatcher
from core.region_calculator import RegionCalculator
from core.clicker import Clicker
from core.doubao_vision import DoubaoVision
from utils.image_utils import crop_region, preprocess_for_ocr
from gui.app_window import AppWindow

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


class QuizBot:
    """答题器主逻辑，编排截图→OCR→匹配→点击的完整流程。"""

    def __init__(self, gui: AppWindow):
        self.gui = gui
        self._running = threading.Event()
        self._thread = None

        # 统计
        self.total = 0
        self.matched = 0
        self.unmatched = 0

        # 重复题目检测
        self.recent_questions = deque(maxlen=5)

        # 异步识别状态
        self._pending_recognition = None  # (screenshot, calc, timestamp)
        self._recognition_result = None   # 识别结果
        self._recognition_lock = threading.Lock()
        self._last_recognition_start = 0.0  # 上次启动识别的时间
        self._doubao_last_frame_hash = None
        self._doubao_last_sent_hash = None
        self._doubao_last_processed_hash = None
        self._doubao_pending_hash = None
        self._doubao_stable_frames = 0
        self._doubao_result_cache = OrderedDict()
        self._awaiting_confirm_question_hash = None
        self._awaiting_confirm_logged_hash = None
        self._awaiting_confirm_question_text_key = None
        self._awaiting_confirm_logged_text_key = None
        self._pending_answer_question_hash = None
        self._pending_answer_question_text_key = None
        self._pending_answer_question_text = None
        self._pending_answer_index = None
        self._pending_answer_baseline = None
        self._pending_answer_confirmed = False
        self._pending_answer_last_click_at = 0.0
        self._last_confirm_click_at = 0.0
        self._seen_match_success_log_keys: set[str] = set()
        self._seen_question_detail_log_keys: set[str] = set()
        self._seen_pending_answer_debug_keys: set[str] = set()
        self._confirm_templates_gray: list[np.ndarray] | None = None
        self._confirm_template_load_failed = False
        self._last_mumu_adb_options: list[dict] = []

        # 初始化各模块
        self.gui.log("正在初始化模块...")

        self.window_mgr = WindowManager(
            config.WINDOW_TITLE_KEYWORDS,
            mumu_adb_path=getattr(config, "MUMU_ADB_PATH", ""),
            mumu_adb_serial=getattr(config, "MUMU_ADB_SERIAL", ""),
            process_keywords=getattr(config, "WINDOW_PROCESS_KEYWORDS", []),
        )
        self.clicker = Clicker(
            click_delay=config.CLICK_DELAY,
            random_offset=config.CLICK_RANDOM_OFFSET,
            restore_mouse_position=getattr(config, "RESTORE_MOUSE_POSITION", True),
            click_mode=getattr(config, "CLICK_MODE", "mouse"),
            mumu_adb_path=getattr(config, "MUMU_ADB_PATH", ""),
            mumu_adb_serial=getattr(config, "MUMU_ADB_SERIAL", ""),
            mumu_device_width=getattr(config, "MUMU_DEVICE_WIDTH", 0),
            mumu_device_height=getattr(config, "MUMU_DEVICE_HEIGHT", 0),
        )

        # OCR 和题库在后台初始化（较耗时）
        self.ocr_engine = None
        self.matcher = None
        self.doubao_vision = None

    def _init_heavy_modules(self):
        """初始化耗时较长的模块（OCR引擎和题库）。"""
        # 检查是否启用豆包视觉识别
        use_doubao = getattr(config, "USE_DOUBAO_VISION", False)

        if use_doubao:
            self.gui.log("正在初始化豆包视觉识别...")
            doubao_api_key = getattr(config, "DOUBAO_API_KEY", "")
            if not doubao_api_key:
                self.gui.log("警告：未配置 DOUBAO_API_KEY，将使用传统 OCR 模式")
                use_doubao = False
            else:
                self.doubao_vision = DoubaoVision(
                    api_key=doubao_api_key,
                    base_url=getattr(config, "DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
                    model=getattr(config, "DOUBAO_MODEL", "doubao-seed-1-8-251228"),
                    timeout=getattr(config, "DOUBAO_TIMEOUT", 30),
                    min_interval=getattr(config, "DOUBAO_MIN_INTERVAL", 1.0),
                )
                self.gui.log("豆包视觉识别初始化完成")

        if not use_doubao:
            # 传统 OCR 模式
            self.gui.log("正在加载 OCR 引擎（首次可能需要下载模型）...")
            self.ocr_engine = OCREngine(
                lang=config.OCR_LANG,
                use_angle_cls=config.OCR_USE_ANGLE_CLS,
                use_gpu=config.OCR_USE_GPU,
            )
            self.gui.log("OCR 引擎加载完成")

        # 题库在两种模式下都需要（豆包模式用于匹配答案）
        self.gui.log("正在加载题库...")
        self.matcher = QuestionMatcher(config.QUESTION_BANK_PATH)
        self.gui.log(f"题库加载完成: {len(self.matcher.questions)} 道题")

    def start(self):
        """启动答题循环（在后台线程中）。"""
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止答题循环。"""
        self._running.clear()
        self.gui.log("已停止")

    def list_available_mumu_windows(self) -> list[dict]:
        """列出当前可选的 MuMu 窗口实例。"""
        return self.window_mgr.list_matching_windows()

    def list_available_mumu_window_bindings(self) -> list[dict]:
        """快速列出窗口与 vm_config.json 中 adb 主端口的绑定关系。"""
        windows = self.list_available_mumu_windows()
        adb_path = self.get_mumu_adb_path()
        adb_options = self._discover_mumu_vm_config_adb_options(adb_path) if adb_path else []
        self._last_mumu_adb_options = adb_options
        return self._attach_mumu_adb_to_windows(windows, adb_options)

    def list_available_mumu_adb_devices(self) -> list[dict]:
        """列出当前可用的 MuMu adb 设备，并按实例端口对分组。"""
        adb_path = self.get_mumu_adb_path()
        if not adb_path or not os.path.exists(adb_path):
            return []

        vm_config_options = self._discover_mumu_vm_config_adb_options(adb_path)
        candidate_serials = [str(option.get("serial", "")).strip() for option in vm_config_options]
        candidate_serials.extend(self._discover_mumu_adb_candidates())
        candidate_serials = [serial for serial in OrderedDict.fromkeys(candidate_serials) if serial]
        for serial in candidate_serials:
            self._try_connect_mumu_adb_device(adb_path, serial)

        try:
            result = subprocess.run(
                [adb_path, "devices"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except Exception as e:
            self.gui.log(f"[调试] 刷新 adb 设备失败: {e}")
            return []

        devices: list[str] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices attached"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])

        connected_serials = sorted(set(devices), key=lambda item: item)
        if vm_config_options:
            options: list[dict] = []
            consumed_serials: set[str] = set()
            for option in vm_config_options:
                serial = str(option.get("serial", "")).strip()
                if serial and serial in connected_serials:
                    options.append(option)
                    consumed_serials.add(serial)

            for serial in connected_serials:
                if serial in consumed_serials:
                    continue
                options.append({"label": serial, "serial": serial})

            self._last_mumu_adb_options = options
            return options

        grouped_options = self._build_mumu_adb_options(connected_serials)
        if grouped_options:
            self._last_mumu_adb_options = grouped_options
            return grouped_options

        self._last_mumu_adb_options = [{"label": serial, "serial": serial} for serial in connected_serials]
        return self._last_mumu_adb_options

    def _discover_mumu_adb_candidates(self) -> list[str]:
        """发现本机可能可连接的 MuMu adb 端口。"""
        configured_ports = getattr(config, "MUMU_ADB_CANDIDATE_PORTS", [])
        if not configured_ports:
            configured_ports = [5555, 5557, 16384, 16416, 7555]

        candidate_ports = {
            int(port)
            for port in configured_ports
            if str(port).isdigit()
        }
        serials = [f"127.0.0.1:{port}" for port in sorted(candidate_ports)]
        return serials

    def _discover_mumu_vm_config_adb_options(self, adb_path: str) -> list[dict]:
        """从 MuMu 每个实例的 vm_config.json 中读取 adb 端口。"""
        try:
            install_root = os.path.dirname(os.path.dirname(os.path.abspath(adb_path)))
        except Exception:
            return []

        vms_root = os.path.join(install_root, "vms")
        if not os.path.isdir(vms_root):
            return []

        options: list[dict] = []
        for entry in sorted(os.scandir(vms_root), key=lambda item: item.name.lower()):
            if not entry.is_dir():
                continue

            match = re.fullmatch(r"MuMuPlayer-\d+\.\d+-(\d+)", entry.name)
            if not match:
                continue

            instance_index = int(match.group(1))
            vm_config_path = os.path.join(entry.path, "configs", "vm_config.json")
            if not os.path.isfile(vm_config_path):
                continue

            try:
                with open(vm_config_path, "r", encoding="utf-8") as file:
                    payload = json.load(file)
            except Exception:
                continue

            port_forward = (((payload.get("vm") or {}).get("nat") or {}).get("port_forward") or {})
            adb_port = str((((port_forward.get("adb") or {}).get("host_port")) or "")).strip()
            if not adb_port.isdigit():
                continue

            frontend_port = str((((port_forward.get("frontend") or {}).get("host_port")) or "")).strip()
            serial = f"127.0.0.1:{adb_port}"
            label = f"实例 {instance_index}: {serial}"

            options.append(
                {
                    "label": label,
                    "serial": serial,
                    "instance_index": instance_index,
                    "vm_config_path": vm_config_path,
                    "frontend_port": frontend_port,
                }
            )

        return options

    def get_mumu_adb_path(self) -> str:
        """返回当前运行时使用的 MuMu adb.exe 路径。"""
        return str(self.window_mgr.mumu_adb_path or "").strip()

    def set_mumu_adb_path(self, path: str):
        """同步更新运行时的 MuMu adb.exe 路径。"""
        path_text = (path or "").strip()
        self.window_mgr.set_mumu_adb_path(path_text)
        self.clicker.set_mumu_adb_path(path_text)
        if not path_text:
            self._last_mumu_adb_options = []

    def detect_mumu_adb_path(self) -> str:
        """自动探测可用的 MuMu adb.exe 路径。"""
        candidates: list[str] = []

        configured_path = str(getattr(config, "MUMU_ADB_PATH", "") or "").strip()
        if configured_path:
            candidates.append(configured_path)

        current_path = self.get_mumu_adb_path()
        if current_path:
            candidates.append(current_path)

        env_path = str(os.environ.get("MUMU_ADB_PATH", "") or "").strip()
        if env_path:
            candidates.append(env_path)

        common_roots = [
            r"D:\games\MuMu Player 12",
            r"D:\Program Files\MuMu Player 12",
            r"C:\Program Files\MuMu Player 12",
            r"C:\Program Files (x86)\MuMu Player 12",
        ]
        for root in common_roots:
            candidates.append(os.path.join(root, "shell", "adb.exe"))
            candidates.append(os.path.join(root, "nx_main", "adb.exe"))

        process_paths = self._discover_mumu_paths_from_processes()
        candidates.extend(process_paths)

        seen: set[str] = set()
        for candidate in candidates:
            normalized = os.path.normcase(os.path.normpath(candidate))
            if not candidate or normalized in seen:
                continue
            seen.add(normalized)
            if os.path.isfile(candidate):
                return candidate

        return ""

    def _discover_mumu_paths_from_processes(self) -> list[str]:
        """从正在运行的 MuMu 进程路径反推 adb.exe 位置。"""
        command = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -match 'MuMuNxMain.exe|MuMuNxDevice.exe|MuMuManager.exe' } | "
            "Select-Object ExecutablePath | ConvertTo-Json -Compress"
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
        except Exception:
            return []

        output = (result.stdout or "").strip()
        if not output:
            return []

        try:
            payload = json.loads(output)
        except Exception:
            return []

        if isinstance(payload, dict):
            payload = [payload]

        candidates: list[str] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            executable_path = str(item.get("ExecutablePath", "") or "").strip()
            if not executable_path:
                continue

            exe_path = Path(executable_path)
            parents = list(exe_path.parents)
            for parent in parents[:4]:
                candidates.append(str(parent / "shell" / "adb.exe"))
                candidates.append(str(parent / "nx_main" / "adb.exe"))

        return candidates

    def _build_mumu_adb_options(self, connected_serials: list[str]) -> list[dict]:
        """按 MuMu VM 进程分组 adb 端口，并为 GUI 生成更清晰的选择项。"""
        if not connected_serials:
            return []

        port_to_serial: dict[int, str] = {}
        for serial in connected_serials:
            match = re.fullmatch(r"127\.0\.0\.1:(\d+)", serial)
            if not match:
                continue
            port_to_serial[int(match.group(1))] = serial

        if not port_to_serial:
            return [{"label": serial, "serial": serial} for serial in connected_serials]

        pid_to_ports = self._discover_mumu_port_groups(set(port_to_serial))
        pid_to_index = self._discover_mumu_vm_indexes(set(pid_to_ports))

        grouped_options: list[dict] = []
        consumed_serials: set[str] = set()

        for pid, ports in sorted(pid_to_ports.items(), key=lambda item: (pid_to_index.get(item[0], 9999), item[0])):
            matched_ports = sorted(port for port in ports if port in port_to_serial)
            if not matched_ports:
                continue

            serials = [port_to_serial[port] for port in matched_ports]
            primary_serial = self._pick_preferred_mumu_serial(serials)
            aliases = [serial for serial in serials if serial != primary_serial]
            consumed_serials.update(serials)

            index = pid_to_index.get(pid)
            prefix = f"实例 {index}" if index is not None else f"PID {pid}"
            alias_text = ", ".join(alias.split(":")[-1] for alias in aliases)
            label = f"{prefix}: {primary_serial}"
            if alias_text:
                label += f"  (同组: {alias_text})"
            grouped_options.append(
                {
                    "label": label,
                    "serial": primary_serial,
                    "aliases": aliases,
                    "pid": pid,
                    "instance_index": index,
                }
            )

        for serial in connected_serials:
            if serial in consumed_serials:
                continue
            grouped_options.append({"label": serial, "serial": serial})

        return grouped_options

    def _discover_mumu_port_groups(self, candidate_ports: set[int]) -> dict[int, set[int]]:
        """从 netstat 中提取 MuMu VM 进程监听的端口对。"""
        if not candidate_ports:
            return {}

        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except Exception:
            return {}

        pid_to_ports: dict[int, set[int]] = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if "LISTENING" not in line:
                continue

            parts = line.split()
            if len(parts) < 5:
                continue

            local_address = parts[1]
            pid_text = parts[-1]
            if ":" not in local_address or not pid_text.isdigit():
                continue

            port_text = local_address.rsplit(":", 1)[-1]
            if not port_text.isdigit():
                continue

            port = int(port_text)
            if port not in candidate_ports:
                continue

            pid = int(pid_text)
            pid_to_ports.setdefault(pid, set()).add(port)

        return pid_to_ports

    def _discover_mumu_vm_indexes(self, pids: set[int]) -> dict[int, int]:
        """读取 MuMu VM 进程命令行，解析实例编号。"""
        if not pids:
            return {}

        pid_list = ",".join(str(pid) for pid in sorted(pids))
        command = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.ProcessId -in {pid_list} }} | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except Exception:
            return {}

        output = (result.stdout or "").strip()
        if not output:
            return {}

        try:
            payload = json.loads(output)
        except Exception:
            return {}

        if isinstance(payload, dict):
            payload = [payload]

        pid_to_index: dict[int, int] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            pid = item.get("ProcessId")
            command_line = str(item.get("CommandLine", "") or "")
            if not isinstance(pid, int):
                continue
            match = re.search(r"MuMuPlayer-12\.0-(\d+)", command_line)
            if match:
                pid_to_index[pid] = int(match.group(1))
        return pid_to_index

    @staticmethod
    def _pick_preferred_mumu_serial(serials: list[str]) -> str:
        """在同组端口中优先选择 MuMu 的高位映射端口。"""
        if not serials:
            return ""

        def sort_key(serial: str):
            try:
                port = int(serial.rsplit(":", 1)[-1])
            except Exception:
                port = 0
            return (0 if port >= 16000 else 1, port)

        return sorted(serials, key=sort_key)[0]

    def _try_connect_mumu_adb_device(self, adb_path: str, serial: str):
        """对候选端口执行一次 adb connect，成功或已连接都视为可用。"""
        try:
            subprocess.run(
                [adb_path, "connect", serial],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except Exception:
            pass

    def configure_runtime_targets(self, window_choice: dict | None):
        """应用 GUI 中选择的窗口实例，并自动绑定对应的 adb 设备。"""
        selected_title = ""
        selected_hwnd = None
        if window_choice:
            selected_title = str(window_choice.get("title", "")).strip()
            selected_hwnd = window_choice.get("hwnd")

        self.window_mgr.set_window_preference(selected_hwnd, selected_title)

        serial_text = self._resolve_selected_mumu_serial(window_choice, "")
        self.window_mgr.set_mumu_adb_serial(serial_text)
        self.clicker.set_mumu_adb_serial(serial_text)

        if selected_title:
            self.gui.log(f"已选择 MuMu 窗口: {selected_title}")
        else:
            self.gui.log("MuMu 窗口: 自动匹配")

        if serial_text:
            self.gui.log(f"已选择 MuMu adb 设备: {serial_text}")
        else:
            self.gui.log("MuMu adb 设备: 未配置")

    @staticmethod
    def _attach_mumu_adb_to_windows(windows: list[dict], adb_options: list[dict]) -> list[dict]:
        """按实例号把 MuMu adb 主端口绑定到窗口项。"""
        adb_by_index = {
            option.get("instance_index"): str(option.get("serial", "")).strip()
            for option in adb_options
            if option.get("instance_index") is not None and str(option.get("serial", "")).strip()
        }

        bound_windows: list[dict] = []
        for window in windows:
            merged = dict(window)
            instance_index = merged.get("instance_index")
            if instance_index in adb_by_index:
                merged["adb_serial"] = adb_by_index[instance_index]
            bound_windows.append(merged)
        return bound_windows

    def _resolve_selected_mumu_serial(self, window_choice: dict | None, adb_serial: str) -> str:
        """优先按窗口实例号自动匹配对应的 MuMu adb serial。"""
        default_serial = str(getattr(config, "MUMU_ADB_SERIAL", "") or "").strip()
        selected_serial = (adb_serial or "").strip()
        if window_choice:
            bound_serial = str(window_choice.get("adb_serial", "") or "").strip()
            if bound_serial:
                return bound_serial

        window_index = None if not window_choice else window_choice.get("instance_index")

        if window_index is not None and (not selected_serial or selected_serial == default_serial):
            for option in self._last_mumu_adb_options:
                if option.get("instance_index") == window_index:
                    matched_serial = str(option.get("serial", "")).strip()
                    if matched_serial:
                        return matched_serial

        return selected_serial or default_serial

    def _loop(self):
        """主循环：截图→OCR→匹配→点击。"""
        # 延迟初始化耗时模块
        if self.ocr_engine is None and self.doubao_vision is None:
            try:
                self._init_heavy_modules()
            except Exception as e:
                self.gui.log(f"初始化失败: {e}")
                self.gui.stop()
                return

        self.gui.log("答题器已启动，开始监控游戏窗口...")

        while self._running.is_set():
            try:
                self._tick()
            except Exception as e:
                self.gui.log(f"运行出错: {e}")
                logger.exception("tick error")

            time.sleep(config.LOOP_INTERVAL)

    def _tick(self):
        """单次扫描流程。"""
        # 1. 查找窗口
        if not self.window_mgr.find_window():
            self.gui.log("未找到游戏窗口，等待重试...")
            return

        # 2. 获取窗口位置
        rect = self.window_mgr.get_window_rect()
        if not rect:
            return

        # 3. 截图
        screenshot = self.window_mgr.capture_window()
        if screenshot is None:
            self.gui.log("截图失败")
            return

        calc = RegionCalculator(rect)

        # 4. 判断使用豆包还是传统 OCR
        if self.doubao_vision:
            self._tick_with_doubao(screenshot, calc)
        else:
            self._tick_with_ocr(screenshot, calc)

    def _tick_with_doubao(self, screenshot, calc: RegionCalculator):
        """使用豆包视觉识别的流程（异步非阻塞）。"""
        frame_hash = self._get_doubao_frame_hash(screenshot, calc)
        self._clear_pending_states_if_question_changed(frame_hash, "")
        result_to_process = None
        cached_result = None
        should_start_recognition = False
        should_retry_current_frame = False

        with self._recognition_lock:
            # 检查是否有待处理的识别结果
            if self._recognition_result is not None:
                result, result_screenshot, result_calc, result_hash = self._recognition_result
                self._recognition_result = None
                result_to_process = (result, result_screenshot, result_calc, result_hash)

            if not frame_hash:
                pass
            elif self._is_same_doubao_frame(frame_hash, self._doubao_last_frame_hash):
                self._doubao_stable_frames += 1
            else:
                self._doubao_last_frame_hash = frame_hash
                self._doubao_stable_frames = 1

            if (
                frame_hash
                and self._pending_recognition is None
                and self._doubao_stable_frames >= getattr(config, "DOUBAO_TRIGGER_STABLE_FRAMES", 2)
                and not self._is_exact_doubao_frame(frame_hash, self._doubao_last_processed_hash)
            ):
                cached_result = self._get_cached_doubao_result(frame_hash)
                if cached_result is None:
                    now = time.time()
                    if (
                        not self._is_exact_doubao_frame(frame_hash, self._doubao_last_sent_hash)
                        and self._can_start_doubao_request(now)
                    ):
                        should_start_recognition = True

        if result_to_process is not None:
            result, result_screenshot, result_calc, result_hash = result_to_process
            if frame_hash and result_hash and not self._is_same_doubao_frame(frame_hash, result_hash):
                self.gui.log("[调试] 丢弃过期识别结果：题面已变化")
                processed_ok = False
                should_retry_current_frame = True
            else:
                processed_ok = self._process_doubao_result(result, result_screenshot, result_calc)
            with self._recognition_lock:
                if processed_ok:
                    self._doubao_last_processed_hash = result_hash
                else:
                    self._doubao_last_sent_hash = None

        if cached_result is not None:
            processed_ok = self._process_doubao_result(cached_result, screenshot, calc)
            with self._recognition_lock:
                if processed_ok:
                    self._doubao_last_processed_hash = frame_hash
                else:
                    self._doubao_last_sent_hash = None

        if (
            result_to_process is None
            and cached_result is None
            and self._pending_answer_index is not None
            and self._is_waiting_same_answer(frame_hash, "", self._pending_answer_index)
        ):
            if self._is_exact_doubao_frame(frame_hash, self._pending_answer_question_hash):
                self._advance_answer_state(
                    self._pending_answer_question_text or "",
                    frame_hash,
                    self._pending_answer_question_text_key or "",
                    self._pending_answer_index,
                    screenshot,
                    calc,
                )
            else:
                self._log_pending_answer_debug_once(
                    "wait_new_answer_after_change",
                    frame_hash,
                    self._pending_answer_question_text_key or "",
                    self._pending_answer_index,
                    "[调试] 题面已变化但尚未拿到新答案，跳过上一题的确认点击",
                )

        if should_retry_current_frame and frame_hash and cached_result is None:
            should_start_recognition = True

        if should_start_recognition:
            start_log = "[调试] 立即重新识别当前题面" if should_retry_current_frame else "[调试] 开始识别当前题面"
            self._start_doubao_recognition(screenshot, calc, frame_hash, log_message=start_log)

    def _async_recognize(self, cropped, screenshot, calc, frame_hash):
        """后台线程中调用豆包识别。"""
        result = self.doubao_vision.analyze_quiz_image(cropped)

        with self._recognition_lock:
            self._pending_recognition = None
            self._doubao_pending_hash = None
            if result:
                self.gui.log("[调试] 识别结果已返回")
                self._recognition_result = (result, screenshot, calc, frame_hash)
                if result.get("question") and len(result.get("options", [])) >= 4:
                    self._remember_doubao_result(frame_hash, result)
            else:
                self.gui.log("[调试] 识别失败，本轮未返回有效结果")
                self._doubao_last_sent_hash = None

    def _can_start_doubao_request(self, now: float | None = None) -> bool:
        """判断当前是否满足豆包请求最小间隔。"""
        current_time = time.time() if now is None else now
        min_interval = max(0.0, float(getattr(config, "DOUBAO_MIN_INTERVAL", 1.0)))
        return (current_time - self._last_recognition_start) >= min_interval

    def _start_doubao_recognition(
        self,
        screenshot: np.ndarray,
        calc: RegionCalculator,
        frame_hash: str,
        log_message: str | None = None,
    ) -> bool:
        """统一启动豆包识别，避免重复占用 pending 状态。"""
        if not frame_hash:
            return False

        now = time.time()
        with self._recognition_lock:
            if self._pending_recognition is not None:
                return False
            if not self._can_start_doubao_request(now):
                return False
            if self._is_exact_doubao_frame(frame_hash, self._doubao_last_sent_hash):
                return False
            if self._is_exact_doubao_frame(frame_hash, self._doubao_last_processed_hash):
                return False

            self._last_recognition_start = now
            self._doubao_last_sent_hash = frame_hash
            self._doubao_pending_hash = frame_hash
            self._pending_recognition = (screenshot, calc, now)

        if log_message:
            self.gui.log(log_message)

        cropped = self._get_doubao_crop(screenshot, calc)
        threading.Thread(
            target=self._async_recognize,
            args=(cropped, screenshot, calc, frame_hash),
            daemon=True,
        ).start()
        return True

    def _process_doubao_result(self, result, screenshot, calc: RegionCalculator) -> bool:
        """处理豆包识别结果。"""
        question_text = result.get("question", "")
        options = result.get("options", [])
        frame_hash = self._get_doubao_frame_hash(screenshot, calc)
        question_text_key = QuestionMatcher._clean_text(question_text)
        if not question_text:
            self.gui.log("[调试] 题目内容为空")
            return False
        self._clear_pending_states_if_question_changed(frame_hash, question_text_key)

        # 检查选项数量
        if not options or len(options) < 4:
            self.gui.log(f"[调试] 选项数量无效：{len(options)}，期望 4 个")
            return False

        # 重复检测
        if self._is_duplicate(question_text):
            return True

        self._log_question_and_options_once(question_text, options)

        # 使用题库匹配答案
        match = self.matcher.find_answer(question_text, config.FUZZY_MATCH_THRESHOLD)
        if not match:
            self.unmatched += 1
            self.total += 1
            self.gui.log(f"未匹配到答案")
            self.matcher.log_unmatched(question_text, config.UNMATCHED_LOG_PATH)
            self._update_stats()
            return True

        self._log_match_success_once(question_text, f"题库匹配成功 (分数:{match['score']}): 答案={match['answer']}")

        # 在豆包识别的选项中查找答案
        correct_answer = match["answer"]
        answer_index = self._select_answer_index(options, correct_answer, question_text)

        if answer_index == -1:
            self.gui.log("未在识别的选项中找到答案")
            self.unmatched += 1
            self.total += 1
            self._update_stats()
            return True

        answer_index = self._resolve_pending_answer_index(
            frame_hash,
            question_text_key,
            answer_index,
        )

        if self._is_waiting_same_answer(frame_hash, question_text_key, answer_index):
            self._advance_answer_state(
                question_text,
                frame_hash,
                question_text_key,
                answer_index,
                screenshot,
                calc,
            )
            return True

        # 点击答案
        self._advance_answer_state(
            question_text,
            frame_hash,
            question_text_key,
            answer_index,
            screenshot,
            calc,
        )
        return True

        return True

    def _tick_with_ocr(self, screenshot, calc: RegionCalculator):
        """使用传统 OCR + 题库匹配的流程。"""
        frame_hash = self._get_doubao_frame_hash(screenshot, calc)
        self._clear_pending_states_if_question_changed(frame_hash, "")

        # 4. 识别题目
        q_region = calc.get_pixel_region(config.QUESTION_REGION)
        q_image = crop_region(screenshot, *q_region)
        q_image_processed = preprocess_for_ocr(q_image, config.PREPROCESSING_SCALE_FACTOR)
        q_conf = getattr(config, "OCR_QUESTION_CONFIDENCE_THRESHOLD", config.OCR_CONFIDENCE_THRESHOLD)
        question_text = self.ocr_engine.recognize_text(
            q_image_processed, q_conf
        )
        if not question_text or len(question_text.strip()) < 2:
            return  # 可能不在答题界面
        question_text_key = QuestionMatcher._clean_text(question_text)
        self._clear_pending_states_if_question_changed(frame_hash, question_text_key)

        # 5. 重复检测
        if self._is_duplicate(question_text):
            return

        # 6. 匹配题库
        match = self.matcher.find_answer(question_text, config.FUZZY_MATCH_THRESHOLD)
        self._log_question_and_options_once(question_text, match.get("options", []) if match else [])
        if not match:
            self.unmatched += 1
            self.total += 1
            self.gui.log(f"未匹配到答案")
            self.matcher.log_unmatched(question_text, config.UNMATCHED_LOG_PATH)
            self._update_stats()
            self.recent_questions.append(question_text)
            return

        correct_answer = match["answer"]
        self._log_match_success_once(question_text, f"匹配成功 (分数:{match['score']:.0f}): 答案={correct_answer}")

        # 7. 确定点击哪个选项（若选项 OCR 不完整/不确定，可重试几次）
        retry_count = getattr(config, "OPTION_OCR_RETRY_COUNT", 0)
        retry_delay = getattr(config, "OPTION_OCR_RETRY_DELAY", 0.0)

        # 安全限制：即使配置被改得很大，也避免在单次 tick 内卡住太久
        retry_count = max(0, min(int(retry_count), 5))

        click_index = None
        for attempt in range(retry_count + 1):
            click_index = self._find_answer_option(screenshot, calc, match)
            if click_index is not None:
                break

            if attempt < retry_count:
                self.gui.log("选项识别不完整/不确定，等待后重试...")
                time.sleep(retry_delay)
                screenshot = self.window_mgr.capture_window()
                if screenshot is None:
                    self.gui.log("截图失败")
                    self.recent_questions.append(question_text)
                    return

        if click_index is None:
            # 选项区域可能被弹窗/动画遮挡，或者 OCR 暂时不稳定。
            # 此时不要把题目加入 recent_questions，也不要计入 total，
            # 让下一轮 tick 继续识别同一题直到点成功或题目变化。
            self.gui.log("未找到对应选项，本轮不点击，等待下轮继续识别...")
            return

        click_index = self._resolve_pending_answer_index(
            frame_hash,
            question_text_key,
            click_index,
        )

        if self._is_waiting_same_answer(frame_hash, question_text_key, click_index):
            self._advance_answer_state(
                question_text,
                frame_hash,
                question_text_key,
                click_index,
                screenshot,
                calc,
            )
            return

        # 8. 点击
        self._advance_answer_state(
            question_text,
            frame_hash,
            question_text_key,
            click_index,
            screenshot,
            calc,
        )

        # 9. 点击后等待

    def _advance_answer_state(
        self,
        question_text: str,
        frame_hash: str,
        question_text_key: str,
        answer_index: int,
        screenshot: np.ndarray,
        calc: RegionCalculator,
    ):
        """同一题只推进两件事：选中目标答案，点击固定确认按钮。"""
        if not getattr(config, "ENABLE_SECOND_STAGE_CONFIRM", True):
            click_x, click_y = calc.get_click_point(config.ANSWER_REGIONS[answer_index])
            self._log_answer_click(answer_index)
            self.clicker.click_at(click_x, click_y, self.window_mgr.hwnd)
            self.total += 1
            self.matched += 1
            self.recent_questions.append(question_text)
            self._update_stats()
            return

        if self._is_waiting_same_answer(frame_hash, question_text_key, answer_index):
            answer_selected = self._is_pending_answer_selected(screenshot, answer_index, calc)
            confirm_present = self._is_fixed_confirm_button_present(
                self._pending_answer_baseline,
                screenshot,
                answer_index,
                calc,
            )

            if confirm_present:
                if self._can_issue_confirm_click():
                    confirm_x, confirm_y = self._get_fixed_confirm_click_point(answer_index, calc)
                    self.gui.log(f"[调试] 检测到固定确认按钮：{chr(65 + answer_index)}")
                    self.clicker.click_at(
                        confirm_x,
                        confirm_y,
                        self.window_mgr.hwnd,
                        delay_override=max(
                            0.0,
                            float(
                                getattr(
                                    config,
                                    "SECOND_STAGE_CONFIRM_CLICK_DELAY",
                                    getattr(config, "CLICK_DELAY", 0.3),
                                )
                            ),
                        ),
                    )
                    self._pending_answer_confirmed = True
                    now = time.time()
                    self._pending_answer_last_click_at = now
                    self._last_confirm_click_at = now
                    self.gui.log(f"[调试] 已点击固定确认按钮：{chr(65 + answer_index)}")
                else:
                    self._log_pending_answer_debug_once(
                        "confirm_throttled",
                        frame_hash,
                        question_text_key,
                        answer_index,
                        f"[调试] 已检测到固定确认按钮，但确认点击冷却未到：{chr(65 + answer_index)}",
                    )
                return

            if not answer_selected:
                self._log_pending_answer_debug_once(
                    "wait_selection",
                    frame_hash,
                    question_text_key,
                    answer_index,
                    f"[调试] 选项 {chr(65 + answer_index)} 尚未判定为已选中，且固定确认按钮未命中",
                )
                if self._can_issue_pending_click():
                    click_x, click_y = calc.get_click_point(config.ANSWER_REGIONS[answer_index])
                    self._log_answer_click(answer_index)
                    self.clicker.click_at(click_x, click_y, self.window_mgr.hwnd)
                    self._pending_answer_last_click_at = time.time()
                return

            self._log_pending_answer_debug_once(
                "wait_confirm",
                frame_hash,
                question_text_key,
                answer_index,
                f"[调试] 选项 {chr(65 + answer_index)} 已判定为选中，但固定确认按钮未命中",
            )
            return

        click_x, click_y = calc.get_click_point(config.ANSWER_REGIONS[answer_index])
        self._pending_answer_question_hash = frame_hash or None
        self._pending_answer_question_text_key = question_text_key or None
        self._pending_answer_question_text = question_text
        self._pending_answer_index = answer_index
        self._pending_answer_baseline = screenshot
        self._pending_answer_confirmed = False
        self._pending_answer_last_click_at = time.time()
        self._log_answer_click(answer_index)
        self.clicker.click_at(click_x, click_y, self.window_mgr.hwnd)

    def _can_issue_pending_click(self) -> bool:
        min_interval = max(
            0.15,
            float(getattr(config, "SECOND_STAGE_PENDING_CLICK_INTERVAL", getattr(config, "CLICK_DELAY", 0.3))),
        )
        return (time.time() - self._pending_answer_last_click_at) >= min_interval

    def _can_issue_confirm_click(self) -> bool:
        min_interval = max(
            3.0,
            float(getattr(config, "SECOND_STAGE_CONFIRM_RECLICK_INTERVAL", 3.0)),
        )
        return (time.time() - self._last_confirm_click_at) >= min_interval

    def _is_pending_answer_selected(
        self,
        current: np.ndarray,
        answer_index: int,
        calc: RegionCalculator,
    ) -> bool:
        if self._pending_answer_baseline is None:
            return self._looks_answer_option_selected(current, answer_index, calc)
        if self._did_answer_region_change(
            self._pending_answer_baseline,
            current,
            answer_index,
            calc,
        ):
            return True
        return self._looks_answer_option_selected(current, answer_index, calc)

    def _finalize_pending_answer(self):
        if not self._pending_answer_confirmed:
            return
        self.total += 1
        self.matched += 1
        if self._pending_answer_question_text:
            self.recent_questions.append(self._pending_answer_question_text)
        self._update_stats()

    def _handle_post_answer_click(
        self,
        question_text: str,
        answer_index: int,
        screenshot_before_click: np.ndarray,
        calc: RegionCalculator,
    ) -> bool:
        """选中答案后，等待下一题出现或执行二阶段确认点击。"""
        if not getattr(config, "ENABLE_SECOND_STAGE_CONFIRM", True):
            time.sleep(config.POST_CLICK_DELAY)
            return True

        question_hash = self._get_doubao_frame_hash(screenshot_before_click, calc)
        timeout_s = max(0.2, float(getattr(config, "SECOND_STAGE_CONFIRM_TIMEOUT", 1.6)))
        poll_interval = max(0.05, float(getattr(config, "SECOND_STAGE_CONFIRM_POLL_INTERVAL", 0.12)))
        after_click_timeout_s = max(
            0.05,
            float(getattr(config, "SECOND_STAGE_CONFIRM_AFTER_CLICK_TIMEOUT", timeout_s)),
        )
        confirm_click_delay = max(
            0.0,
            float(getattr(config, "SECOND_STAGE_CONFIRM_CLICK_DELAY", getattr(config, "CLICK_DELAY", 0.3))),
        )
        confirm_trigger_delay = max(
            0.05,
            float(getattr(config, "SECOND_STAGE_CONFIRM_TRIGGER_DELAY", 0.12)),
        )
        retry_count = max(0, int(getattr(config, "SECOND_STAGE_SELECTION_RETRY_COUNT", 1)))
        min_present_frames = max(1, int(getattr(config, "SECOND_STAGE_CONFIRM_MIN_PRESENT_FRAMES", 2)))
        saw_selection_change = False

        for attempt in range(retry_count + 1):
            attempt_started_at = time.time()
            confirm_probe_enabled = False
            if attempt > 0:
                current_before_retry = self.window_mgr.capture_window()
                if current_before_retry is not None and self._did_answer_region_change(
                    screenshot_before_click,
                    current_before_retry,
                    answer_index,
                    calc,
                ):
                    self.gui.log(f"[调试] 当前已停留在选项 {chr(65 + answer_index)}，跳过重复点击")
                else:
                    self.gui.log(f"[调试] 重试点击选项 {chr(65 + answer_index)}")
                    retry_x, retry_y = calc.get_click_point(config.ANSWER_REGIONS[answer_index])
                    self.clicker.click_at(retry_x, retry_y, self.window_mgr.hwnd)

            selection_change_time = None
            confirm_present_frames = 0
            confirm_point = None
            confirm_source = None
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                time.sleep(poll_interval)
                current = self.window_mgr.capture_window()
                if current is None:
                    continue

                current_hash = self._get_doubao_frame_hash(current, calc)
                if current_hash and question_hash and not self._is_same_doubao_frame(question_hash, current_hash):
                    return True

                answer_region_changed = self._did_answer_region_change(
                    screenshot_before_click,
                    current,
                    answer_index,
                    calc,
                )

                if answer_region_changed and not saw_selection_change:
                    self.gui.log(f"[调试] 已选中选项 {chr(65 + answer_index)}，等待题目切换或固定确认点击")
                    saw_selection_change = True
                    selection_change_time = time.time()

                if answer_region_changed:
                    confirm_probe_enabled = True
                elif not confirm_probe_enabled and time.time() - attempt_started_at >= confirm_trigger_delay:
                    self.gui.log(f"[调试] 选项 {chr(65 + answer_index)} 未出现明显变化，继续探测题目切换或固定确认按钮")
                    confirm_probe_enabled = True
                    if selection_change_time is None:
                        selection_change_time = attempt_started_at

                if not confirm_probe_enabled:
                    continue

                if selection_change_time is None:
                    selection_change_time = time.time()
                if time.time() - selection_change_time < confirm_trigger_delay:
                    continue

                if self._is_fixed_confirm_button_present(
                    screenshot_before_click,
                    current,
                    answer_index,
                    calc,
                ):
                    confirm_present_frames += 1
                else:
                    confirm_present_frames = 0
                    continue

                if confirm_present_frames < min_present_frames:
                    continue

                confirm_point = self._get_fixed_confirm_click_point(answer_index, calc)
                self.gui.log(f"[调试] 检测到二阶段确认按钮并执行点击：{chr(65 + answer_index)}")
                self._awaiting_confirm_question_hash = question_hash or None
                self._awaiting_confirm_logged_hash = None
                self._awaiting_confirm_question_text_key = QuestionMatcher._clean_text(question_text)
                self._awaiting_confirm_logged_text_key = None
                self.clicker.click_at(
                    confirm_point[0],
                    confirm_point[1],
                    self.window_mgr.hwnd,
                    delay_override=confirm_click_delay,
                )
                if self._wait_for_question_change(question_hash, calc, after_click_timeout_s):
                    self._awaiting_confirm_question_hash = None
                    self._awaiting_confirm_logged_hash = None
                    self._awaiting_confirm_question_text_key = None
                    self._awaiting_confirm_logged_text_key = None
                    return True
                return False

        self.gui.log(f"[调试] 固定确认区域未命中：{chr(65 + answer_index)}")
        return False

    def _should_wait_for_confirmed_question(self, frame_hash: str) -> bool:
        """如果上一题已点击确认但尚未翻题，则阻止再次处理同一题。"""
        pending_hash = self._awaiting_confirm_question_hash
        if not pending_hash:
            return False

        if frame_hash and not self._is_same_doubao_frame(frame_hash, pending_hash):
            self._awaiting_confirm_question_hash = None
            self._awaiting_confirm_logged_hash = None
            self._clear_pending_answer()
            return False

        if self._awaiting_confirm_logged_hash != pending_hash:
            self.gui.log("[调试] 已点击确认，等待题目切换后再处理下一次确认")
            self._awaiting_confirm_logged_hash = pending_hash
        return True

    def _should_wait_for_confirmed_question_text(self, question_text_key: str) -> bool:
        """如果同一题已经点击过确认，则在题目文本变化前不再重复处理。"""
        pending_text_key = self._awaiting_confirm_question_text_key
        if not pending_text_key or not question_text_key:
            return False
        if question_text_key != pending_text_key:
            self._awaiting_confirm_question_text_key = None
            self._awaiting_confirm_logged_text_key = None
            return False
        if self._awaiting_confirm_logged_text_key != pending_text_key:
            self.gui.log("[调试] 已点击确认，等待题目切换后再处理下一次确认")
            self._awaiting_confirm_logged_text_key = pending_text_key
        return True

    def _is_waiting_same_answer(self, frame_hash: str, question_text_key: str, answer_index: int) -> bool:
        """判断当前题面是否仍在等待同一题、同一答案的后续确认。"""
        if (
            (not self._pending_answer_question_hash and not self._pending_answer_question_text_key)
            or self._pending_answer_index is None
            or self._pending_answer_baseline is None
        ):
            return False
        if answer_index != self._pending_answer_index:
            return False
        if question_text_key and self._pending_answer_question_text_key:
            if question_text_key == self._pending_answer_question_text_key:
                return True
        if not frame_hash or not self._pending_answer_question_hash:
            return False
        return self._is_same_doubao_frame(frame_hash, self._pending_answer_question_hash)

    def _resolve_pending_answer_index(self, frame_hash: str, question_text_key: str, answer_index: int) -> int:
        """同题重识别若得到不同答案，保持当前待确认选项，避免中途切换点击目标。"""
        pending_index = self._pending_answer_index
        if pending_index is None or pending_index == answer_index or self._pending_answer_baseline is None:
            return answer_index

        same_question = False
        pending_text_key = self._pending_answer_question_text_key
        if question_text_key and pending_text_key:
            same_question = question_text_key == pending_text_key
        elif frame_hash and self._pending_answer_question_hash:
            same_question = self._is_same_doubao_frame(frame_hash, self._pending_answer_question_hash)

        if not same_question:
            return answer_index

        self._log_pending_answer_debug_once(
            "keep_pending_answer",
            frame_hash,
            question_text_key or pending_text_key or "",
            pending_index,
            f"[调试] 同题重识别得到不同选项，保持原待确认选项 {chr(65 + pending_index)}，忽略新候选 {chr(65 + answer_index)}",
        )
        return pending_index

    def _clear_pending_states_if_question_changed(self, frame_hash: str, question_text_key: str):
        """题面或题目文本变化后，清理上一题残留状态。"""
        pending_text_key = self._pending_answer_question_text_key
        should_clear_pending = False
        question_changed = False
        if pending_text_key and question_text_key and question_text_key != pending_text_key:
            should_clear_pending = True
            question_changed = True
        elif self._pending_answer_question_hash and frame_hash and not self._is_same_doubao_frame(frame_hash, self._pending_answer_question_hash):
            should_clear_pending = True
            question_changed = True

        if should_clear_pending:
            self._finalize_pending_answer()
            self._clear_pending_answer()

        confirm_text_key = self._awaiting_confirm_question_text_key
        if confirm_text_key and question_text_key and question_text_key != confirm_text_key:
            self._awaiting_confirm_question_text_key = None
            self._awaiting_confirm_logged_text_key = None
            question_changed = True
        elif self._awaiting_confirm_question_hash and frame_hash and not self._is_same_doubao_frame(frame_hash, self._awaiting_confirm_question_hash):
            self._awaiting_confirm_question_hash = None
            self._awaiting_confirm_logged_hash = None
            self._awaiting_confirm_question_text_key = None
            self._awaiting_confirm_logged_text_key = None
            question_changed = True

        if question_changed:
            self._last_confirm_click_at = 0.0

    def _clear_pending_answer(self):
        """清理等待确认中的答案点击状态。"""
        self._pending_answer_question_hash = None
        self._pending_answer_question_text_key = None
        self._pending_answer_question_text = None
        self._pending_answer_index = None
        self._pending_answer_baseline = None
        self._pending_answer_confirmed = False
        self._pending_answer_last_click_at = 0.0
        self._seen_pending_answer_debug_keys.clear()

    def _log_question_and_options_once(self, question_text: str, options: list[str]):
        """同一道题在本次运行中只输出一次题目和选项。"""
        question_log_key = self._build_question_log_key("", question_text)
        if not question_log_key or question_log_key in self._seen_question_detail_log_keys:
            return

        self._seen_question_detail_log_keys.add(question_log_key)
        self.gui.log(f"识别题目: {question_text}")
        for idx, option in enumerate(options[:len(config.ANSWER_REGIONS)]):
            option_text = str(option).strip()
            if option_text:
                self.gui.log(f"  选项{chr(65 + idx)}: {option_text}")

    def _log_match_success_once(self, question_text: str, message: str):
        """同一道题在本次运行中只输出一次匹配成功日志。"""
        question_log_key = self._build_question_log_key("", question_text)
        if not question_log_key:
            return
        if question_log_key in self._seen_match_success_log_keys:
            return
        self._seen_match_success_log_keys.add(question_log_key)
        self.gui.log(message)

    def _log_answer_click(self, answer_index: int):
        """Log the answer click."""
        self.gui.log(f"点击选项 {chr(65 + answer_index)}")

    def _build_question_log_key(self, frame_hash: str, question_text: str) -> str:
        """为当前题目构造稳定的日志去重键。"""
        if frame_hash:
            return frame_hash
        return QuestionMatcher._clean_text(question_text)

    def _wait_for_question_change(self, previous_hash: str, calc: RegionCalculator, timeout_s: float) -> bool:
        """短暂等待题目区域切换到下一题。"""
        if not previous_hash:
            return False

        deadline = time.time() + max(0.2, timeout_s)
        poll_interval = max(0.05, float(getattr(config, "SECOND_STAGE_CONFIRM_POLL_INTERVAL", 0.12)))
        while time.time() < deadline:
            time.sleep(poll_interval)
            current = self.window_mgr.capture_window()
            if current is None:
                continue

            current_hash = self._get_doubao_frame_hash(current, calc)
            if current_hash and not self._is_same_doubao_frame(previous_hash, current_hash):
                return True

        return False

    def _did_answer_region_change(
        self,
        before: np.ndarray,
        after: np.ndarray,
        answer_index: int,
        calc: RegionCalculator,
    ) -> bool:
        """检查点击后所选答案行是否发生了明显变化。"""
        x, y, w, h = calc.get_pixel_region(config.ANSWER_REGIONS[answer_index])
        before_crop = crop_region(before, x, y, w, h)
        after_crop = crop_region(after, x, y, w, h)
        if before_crop.size == 0 or after_crop.size == 0 or before_crop.shape != after_crop.shape:
            return False

        diff = cv2.absdiff(before_crop, after_crop)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
        changed_ratio = float(np.count_nonzero(diff_gray > 24)) / diff_gray.size
        mean_diff = float(diff_gray.mean())
        return changed_ratio >= 0.03 or mean_diff >= 8.0

    def _looks_answer_option_selected(
        self,
        current: np.ndarray,
        answer_index: int,
        calc: RegionCalculator,
    ) -> bool:
        """通过当前帧里答案行的金色边框样式判断是否已处于选中态。"""
        x, y, w, h = calc.get_pixel_region(config.ANSWER_REGIONS[answer_index])
        crop = crop_region(current, x, y, w, h)
        if crop.size == 0:
            return False

        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        gold_mask = cv2.inRange(hsv, np.array([10, 70, 120]), np.array([45, 255, 255]))
        gold_ratio = float(np.count_nonzero(gold_mask)) / gold_mask.size

        border_mask = np.zeros_like(gold_mask)
        border_w = max(3, w // 12)
        border_h = max(3, h // 8)
        border_mask[:border_h, :] = 255
        border_mask[-border_h:, :] = 255
        border_mask[:, :border_w] = 255
        border_mask[:, -border_w:] = 255
        border_pixels = max(1, int(np.count_nonzero(border_mask)))
        gold_border_ratio = float(np.count_nonzero(cv2.bitwise_and(gold_mask, border_mask))) / border_pixels
        value_mean = float(hsv[:, :, 2].mean())

        min_gold_ratio = float(getattr(config, "SECOND_STAGE_SELECTED_MIN_GOLD_RATIO", 0.004))
        min_gold_border_ratio = float(getattr(config, "SECOND_STAGE_SELECTED_MIN_GOLD_BORDER_RATIO", 0.012))
        min_value_mean = float(getattr(config, "SECOND_STAGE_SELECTED_MIN_VALUE_MEAN", 145.0))
        return (
            gold_ratio >= min_gold_ratio
            and gold_border_ratio >= min_gold_border_ratio
            and value_mean >= min_value_mean
        )

    def _log_pending_answer_debug_once(
        self,
        tag: str,
        frame_hash: str,
        question_text_key: str,
        answer_index: int,
        message: str,
    ):
        """同一题同一状态只输出一次 pending 调试日志，避免刷屏。"""
        question_key = frame_hash or question_text_key or ""
        if not question_key:
            return
        log_key = f"{tag}:{question_key}:{answer_index}"
        if log_key in self._seen_pending_answer_debug_keys:
            return
        self._seen_pending_answer_debug_keys.add(log_key)
        self.gui.log(message)

    def _get_fixed_confirm_region_config(self, answer_index: int) -> dict | None:
        """返回指定选项对应的固定确认区域配置。"""
        confirm_regions = getattr(config, "SECOND_STAGE_CONFIRM_REGIONS", [])
        if 0 <= answer_index < len(confirm_regions):
            return confirm_regions[answer_index]
        return None

    def _get_fixed_confirm_region(self, calc: RegionCalculator, answer_index: int) -> tuple[int, int, int, int]:
        """返回指定选项对应的固定确认区域像素坐标。"""
        region_config = self._get_fixed_confirm_region_config(answer_index)
        if region_config is None:
            raise ValueError(f"Missing SECOND_STAGE_CONFIRM_REGIONS config for answer index {answer_index}")
        return calc.get_pixel_region(region_config)

    def _get_fixed_confirm_click_point(self, answer_index: int, calc: RegionCalculator) -> tuple[int, int]:
        """返回指定选项的固定确认点击坐标。"""
        region_config = self._get_fixed_confirm_region_config(answer_index)
        if region_config is None:
            raise ValueError(f"Missing SECOND_STAGE_CONFIRM_REGIONS config for answer index {answer_index}")
        return calc.get_click_point(region_config)

    def _get_confirm_templates_gray(self) -> list[np.ndarray]:
        """懒加载确认按钮模板图列表，优先使用模板匹配判断确认按钮。"""
        if self._confirm_templates_gray is not None:
            return self._confirm_templates_gray
        if self._confirm_template_load_failed:
            return []

        template_paths = list(
            getattr(
                config,
                "SECOND_STAGE_CONFIRM_TEMPLATE_PATHS",
                [r"D:\develop\yys_dati\data\confirm_template.png"],
            )
        )
        loaded_templates: list[np.ndarray] = []
        for template_path in template_paths:
            template_bgr = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template_bgr is None:
                logger.warning(f"确认按钮模板加载失败: {template_path}")
                continue

            template_rgb = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2RGB)
            loaded_templates.append(cv2.cvtColor(template_rgb, cv2.COLOR_RGB2GRAY))

        if not loaded_templates:
            self._confirm_template_load_failed = True
            return []

        self._confirm_templates_gray = loaded_templates
        return self._confirm_templates_gray

    def _matches_confirm_template(self, image: np.ndarray) -> bool:
        """在固定确认区域内做模板匹配，判断是否存在确认按钮。"""
        template_grays = self._get_confirm_templates_gray()
        if not template_grays:
            return False
        if image.size == 0:
            return False

        search_gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        search_h, search_w = search_gray.shape[:2]
        max_val = -1.0
        for template_gray in template_grays:
            template_h, template_w = template_gray.shape[:2]
            if search_h < template_h or search_w < template_w:
                continue
            result = cv2.matchTemplate(search_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            _min_val, score, _min_loc, _max_loc = cv2.minMaxLoc(result)
            max_val = max(max_val, float(score))

        if max_val < 0.0:
            return False
        threshold = float(getattr(config, "SECOND_STAGE_CONFIRM_TEMPLATE_THRESHOLD", 0.35))
        return max_val >= threshold

    def _is_fixed_confirm_button_present(
        self,
        before: np.ndarray,
        after: np.ndarray,
        answer_index: int,
        calc: RegionCalculator,
    ) -> bool:
        """判断当前选项对应的固定确认区域里是否真的出现了确认按钮。"""
        x, y, w, h = self._get_fixed_confirm_region(calc, answer_index)
        after_crop = crop_region(after, x, y, w, h)
        if after_crop.size == 0:
            return False

        if self._get_confirm_templates_gray():
            return self._matches_confirm_template(after_crop)

        before_crop = crop_region(before, x, y, w, h)
        if before_crop.size == 0 or before_crop.shape != after_crop.shape:
            return False

        diff = cv2.absdiff(after_crop, before_crop)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
        diff_ratio = float(np.count_nonzero(diff_gray > 18)) / diff_gray.size
        mean_diff = float(diff_gray.mean())
        min_diff_ratio = float(getattr(config, "SECOND_STAGE_CONFIRM_FIXED_MIN_DIFF_RATIO", 0.015))
        min_mean_diff = float(getattr(config, "SECOND_STAGE_CONFIRM_FIXED_MIN_MEAN_DIFF", 4.0))
        if diff_ratio < min_diff_ratio and mean_diff < min_mean_diff:
            return False

        hsv = cv2.cvtColor(after_crop, cv2.COLOR_RGB2HSV)
        sat_min = int(getattr(config, "SECOND_STAGE_CONFIRM_FIXED_MIN_SATURATION", 45))
        val_min = int(getattr(config, "SECOND_STAGE_CONFIRM_FIXED_MIN_VALUE", 105))
        mask = cv2.inRange(hsv, np.array([0, sat_min, val_min]), np.array([179, 255, 255]))
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        mask_ratio = float(np.count_nonzero(mask)) / mask.size
        min_mask_ratio = float(getattr(config, "SECOND_STAGE_CONFIRM_FIXED_MIN_MASK_RATIO", 0.08))
        if mask_ratio < min_mask_ratio:
            return False

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_area_ratio = float(getattr(config, "SECOND_STAGE_CONFIRM_FIXED_MIN_AREA_RATIO", 0.05))
        min_area = max(40, int((w * h) * min_area_ratio))
        for contour in contours:
            rx, ry, rw, rh = cv2.boundingRect(contour)
            if rw * rh >= min_area:
                return True
        return False

    def _find_answer_option(self, screenshot, calc: RegionCalculator, match: dict) -> int | None:
        """
        找到正确答案对应的选项索引。

        策略1：如果题库中有 options 列表且答案在其中，直接用索引。
        策略2：OCR 识别每个选项文字，模糊匹配正确答案。
        """
        correct_answer = match["answer"]
        options = match.get("options", [])

        # 策略1：直接用索引（更快更准）
        if options:
            normalized_aliases = {
                self._build_answer_forms(alias)["normalized"]
                for alias in self._split_multi_answer_aliases(correct_answer)
                if alias
            }
            for answer_alias in self._split_multi_answer_aliases(correct_answer):
                try:
                    idx = options.index(answer_alias)
                    if idx < len(config.ANSWER_REGIONS):
                        self.gui.log(f"閫氳繃棰樺簱绱㈠紩瀹氫綅閫夐」 {chr(65 + idx)}")
                        return idx
                except ValueError:
                    continue

            for idx, option in enumerate(options):
                if idx >= len(config.ANSWER_REGIONS):
                    break
                option_normalized = self._build_answer_forms(option)["normalized"]
                if option_normalized and option_normalized in normalized_aliases:
                    self.gui.log(f"閫氳繃棰樺簱鍒悕瀹氫綅閫夐」 {chr(65 + idx)}")
                    return idx

            try:
                idx = options.index(correct_answer)
                if idx < len(config.ANSWER_REGIONS):
                    self.gui.log(f"通过题库索引定位选项 {chr(65 + idx)}")
                    return idx
            except ValueError:
                pass

        # 策略2：OCR 各选项区域并匹配
        recognized_options: list[tuple[int, str]] = []
        recognized_count = 0

        for i, region_cfg in enumerate(config.ANSWER_REGIONS):
            region = calc.get_pixel_region(region_cfg)
            opt_image = crop_region(screenshot, *region)
            opt_image_processed = preprocess_for_ocr(opt_image, config.PREPROCESSING_SCALE_FACTOR)
            opt_conf = getattr(config, "OCR_OPTION_CONFIDENCE_THRESHOLD", config.OCR_CONFIDENCE_THRESHOLD)
            opt_text = self.ocr_engine.recognize_text(
                opt_image_processed, opt_conf
            )

            if not opt_text:
                continue

            recognized_count += 1
            recognized_options.append((i, opt_text))

        # 如果本轮没有识别出 4 个选项，认为界面可能被弹窗/动画遮挡，返回 None 交给上层重试。
        # 这样避免“缺选项时误点”。
        if recognized_count < len(config.ANSWER_REGIONS):
            self.gui.log(f"选项识别不足：识别到 {recognized_count}/{len(config.ANSWER_REGIONS)} 个，暂不点击")
            return None

        if not recognized_options:
            return None

        option_texts = [text for _index, text in recognized_options]
        selected_offset = self._select_answer_index(
            option_texts,
            correct_answer,
            match.get("question", ""),
        )
        if selected_offset == -1:
            return None

        return recognized_options[selected_offset][0]

    def _is_duplicate(self, text: str) -> bool:
        """检查是否与最近已处理的题目重复。"""
        cleaned = QuestionMatcher._clean_text(text)
        for recent in self.recent_questions:
            if fuzz.ratio(cleaned, QuestionMatcher._clean_text(recent)) > 95:
                return True
        return False

    def _select_answer_index(self, options: list[str], correct_answer: str, question_text: str = "") -> int:
        """在选项列表中选择最匹配正确答案的索引。"""
        if not options:
            return -1

        scored_options: list[tuple[int, float, str]] = []
        for i, option in enumerate(options):
            score = self._score_answer_match(option, correct_answer)
            scored_options.append((i, score, option))

        scored_options.sort(key=lambda item: item[1], reverse=True)
        best_i, best_score, _ = scored_options[0]
        second_score = scored_options[1][1] if len(scored_options) > 1 else -1.0
        top_tied = sum(1 for _i, score, _text in scored_options if abs(score - best_score) < 1e-6)

        if top_tied > 1 and best_score < 99:
            self.gui.log(f"选项匹配分并列（{best_score:.1f}），暂不点击")
            return -1

        if best_score >= config.ANSWER_MATCH_THRESHOLD:
            return best_i

        if best_score >= config.ANSWER_MATCH_THRESHOLD - 8 and (best_score - second_score) >= 12:
            self.gui.log(f"低分兜底：最佳分={best_score:.1f}，次佳分={second_score:.1f}，仍选择 {chr(65 + best_i)}")
            return best_i

        special_index = self._select_percentage_numeric_fallback(options, correct_answer, question_text)
        if special_index != -1:
            self.gui.log(
                f"百分比答案兼容：题库答案={correct_answer}，回退选择 {chr(65 + special_index)}"
            )
            return special_index

        return -1

    def _select_percentage_numeric_fallback(
        self,
        options: list[str],
        correct_answer: str,
        question_text: str,
    ) -> int:
        """兼容“百分比题答案被记成去零数字”的题库数据，例如 1 -> 100%。"""
        raw_answer = (correct_answer or "").strip()
        if not raw_answer or not re.fullmatch(r"\d+(?:\.\d+)?", raw_answer):
            return -1

        question_hint = question_text or ""
        if "百分之" not in question_hint and "%" not in question_hint and "％" not in question_hint:
            return -1

        candidate_indexes: list[int] = []
        for index, option in enumerate(options):
            option_forms = self._build_answer_forms(option)
            if option_forms["numeric_suffix"] not in {"%", "％"}:
                continue

            option_numeric = option_forms["numeric_value"]
            if not option_numeric or option_numeric == raw_answer:
                continue

            trimmed_numeric = option_numeric.rstrip("0") or "0"
            if trimmed_numeric == raw_answer:
                candidate_indexes.append(index)

        if len(candidate_indexes) == 1:
            return candidate_indexes[0]
        return -1

    def _score_answer_match(self, option_text: str, correct_answer: str) -> float:
        """计算选项与正确答案的匹配分数。"""
        answer_aliases = self._split_multi_answer_aliases(correct_answer)
        if len(answer_aliases) > 1:
            return max(
                self._score_answer_match(option_text, answer_alias)
                for answer_alias in answer_aliases
            )

        option_forms = self._build_answer_forms(option_text)
        answer_forms = self._build_answer_forms(correct_answer)

        option_values = option_forms["ordered"]
        answer_values = answer_forms["ordered"]

        if option_forms["clean"] == answer_forms["clean"]:
            return 100.0

        if option_forms["normalized"] == answer_forms["normalized"]:
            return 100.0

        option_numeric = option_forms["numeric"]
        answer_numeric = answer_forms["numeric"]
        if option_numeric and answer_numeric:
            if option_numeric == answer_numeric:
                return 100.0

        option_numeric_value = option_forms["numeric_value"]
        answer_numeric_value = answer_forms["numeric_value"]
        if option_numeric_value and answer_numeric_value:
            if option_numeric_value == answer_numeric_value:
                if option_forms["numeric_suffix"] == answer_forms["numeric_suffix"]:
                    return 100.0
                if option_forms["is_pure_numeric"] or answer_forms["is_pure_numeric"]:
                    return 99.0
                return 96.0
            if option_forms["is_numeric_like"] and answer_forms["is_numeric_like"]:
                return 0.0

        for opt in option_values:
            for ans in answer_values:
                if not opt or not ans:
                    continue
                if opt == ans:
                    return 100.0
                if len(opt) >= 2 and len(ans) >= 2 and (opt in ans or ans in opt):
                    return 96.0

        scores = []
        for opt in option_values:
            for ans in answer_values:
                if not opt or not ans:
                    continue
                scores.extend(
                    [
                        fuzz.ratio(opt, ans),
                        fuzz.partial_ratio(opt, ans),
                        fuzz.WRatio(opt, ans),
                    ]
                )

                spaced_opt = " ".join(opt)
                spaced_ans = " ".join(ans)
                scores.extend(
                    [
                        fuzz.ratio(spaced_opt, spaced_ans),
                        fuzz.partial_ratio(spaced_opt, spaced_ans),
                        fuzz.WRatio(spaced_opt, spaced_ans),
                    ]
                )

        return max(scores) if scores else 0.0

    @staticmethod
    def _split_answer_aliases(text: str) -> list[str]:
        """将“纸舞/座敷童子”这类多别名答案拆分为独立候选项。"""
        raw = (text or "").strip()
        if not raw:
            return []

        parts = re.split(r"\s*(?:/|／|\||｜|或者|或)\s*", raw)
        aliases: list[str] = []
        for part in parts:
            candidate = part.strip()
            if candidate and candidate not in aliases:
                aliases.append(candidate)

        return aliases or [raw]

    @staticmethod
    def _split_multi_answer_aliases(text: str) -> list[str]:
        """按稳定分隔符拆分多答案字段，提取别名候选。"""
        raw = (text or "").strip()
        if not raw:
            return []

        parts = re.split("\\s*(?:/|\uFF0F|\\||\uFF5C|\u6216\u8005|\u6216)\\s*", raw)
        aliases: list[str] = []
        for part in parts:
            candidate = part.strip()
            if candidate and candidate not in aliases:
                aliases.append(candidate)

        return aliases or [raw]

    def _build_answer_forms(self, text: str) -> dict:
        """构造用于答案比较的多种归一化形式。"""
        raw = (text or "").strip()
        raw = re.sub(r"^[A-DＡ-Ｄ][\.\-．、:：\s]+", "", raw)
        clean = self._clean_answer_text(raw)
        normalized = self._normalize_answer_text(clean)
        numeric = self._normalize_numeric_expression(normalized)
        numeric_value, numeric_suffix = self._extract_numeric_parts(numeric)

        forms = []
        for value in [raw, clean, normalized, numeric]:
            if value and value not in forms:
                forms.append(value)

        return {
            "raw": raw,
            "clean": clean,
            "normalized": normalized,
            "numeric": numeric,
            "numeric_value": numeric_value,
            "numeric_suffix": numeric_suffix,
            "is_pure_numeric": bool(numeric and re.fullmatch(r"\d+(?:\.\d+)?", numeric)),
            "is_numeric_like": bool(numeric_value),
            "ordered": forms,
        }

    @staticmethod
    def _clean_answer_text(text: str) -> str:
        """清洗答案文本，但保留数字信息。"""
        cleaned = re.sub(r"\s+", "", text or "")
        cleaned = re.sub(r"[，。？！、；：\"'（）【】《》,.?!;:()\[\]{}<>]", "", cleaned)
        cleaned = re.sub(r"[\.。…]+", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _normalize_answer_text(text: str) -> str:
        """统一答案文本中的常见格式差异。"""
        if not text:
            return ""

        normalized = text.lower()
        normalized = normalized.replace("兩", "两")
        normalized = normalized.replace("個", "个")
        normalized = normalized.replace("鐘", "钟")
        normalized = normalized.replace("鐘头", "小时")
        normalized = normalized.replace("鍾头", "小时")
        normalized = normalized.replace("鐘點", "点")
        normalized = normalized.replace("百分之", "")
        return normalized

    @staticmethod
    def _normalize_numeric_expression(text: str) -> str:
        """把中文数字表达归一成阿拉伯数字，便于选项比较。"""
        if not text:
            return ""

        converted = text
        for token in sorted(set(re.findall(r"[零〇一二两三四五六七八九十百千万半]+", text)), key=len, reverse=True):
            arabic = QuizBot._chinese_numeral_to_arabic(token)
            if arabic is not None:
                converted = converted.replace(token, arabic)
        return converted

    @staticmethod
    def _extract_numeric_parts(text: str) -> tuple[str, str]:
        """提取文本中的主数值和其后的单位后缀。"""
        if not text:
            return "", ""

        match = re.fullmatch(r"(\d+(?:\.\d+)?)(.*)", text)
        if not match:
            return "", ""

        numeric_value = match.group(1)
        suffix = match.group(2).strip()
        return numeric_value, suffix

    @staticmethod
    def _chinese_numeral_to_arabic(token: str) -> str | None:
        """将简单中文数字串转换为阿拉伯数字。"""
        if not token:
            return None

        if token == "半":
            return "0.5"

        digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
        total = 0
        section = 0
        number = 0

        for char in token:
            if char in digits:
                number = digits[char]
            elif char in units:
                unit = units[char]
                if unit == 10000:
                    section = (section + (number or 0)) * unit
                    total += section
                    section = 0
                    number = 0
                    continue
                if number == 0:
                    number = 1
                section += number * unit
                number = 0
            else:
                return None

        value = total + section + number
        return str(value)

    def _get_doubao_crop(self, screenshot: np.ndarray, calc: RegionCalculator) -> np.ndarray:
        """裁剪题目和四个选项的最小公共区域。"""
        crop_x = int(calc.win_width * 0.70)
        crop_y = int(calc.win_height * 0.05)
        crop_w = int(calc.win_width * 0.26)
        crop_h = int(calc.win_height * 0.73)
        return screenshot[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]

    def _get_doubao_frame_hash(self, screenshot: np.ndarray, calc: RegionCalculator) -> str:
        """对题目区域生成 dHash，用于判断是否切到了新题。"""
        q_region = calc.get_pixel_region(config.QUESTION_REGION)
        question_image = crop_region(screenshot, *q_region)
        if question_image is None or question_image.size == 0:
            return ""

        gray = cv2.cvtColor(question_image, cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        hash_size = max(6, int(getattr(config, "DOUBAO_HASH_SIZE", 12)))
        reduced = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
        diff = reduced[:, 1:] > reduced[:, :-1]
        return "".join("1" if bit else "0" for bit in diff.flatten())

    @staticmethod
    def _hash_distance(hash_a: str | None, hash_b: str | None) -> int:
        """计算两个题面指纹的汉明距离。"""
        if not hash_a or not hash_b or len(hash_a) != len(hash_b):
            return 1_000_000
        return sum(ch_a != ch_b for ch_a, ch_b in zip(hash_a, hash_b))

    def _is_same_doubao_frame(self, hash_a: str | None, hash_b: str | None) -> bool:
        """判断两帧是否可以视为同一题面。"""
        max_distance = int(getattr(config, "DOUBAO_HASH_DISTANCE_THRESHOLD", 6))
        return self._hash_distance(hash_a, hash_b) <= max_distance

    @staticmethod
    def _is_exact_doubao_frame(hash_a: str | None, hash_b: str | None) -> bool:
        """判断两帧指纹是否完全一致。"""
        return bool(hash_a) and bool(hash_b) and hash_a == hash_b

    def _get_cached_doubao_result(self, frame_hash: str) -> dict | None:
        """命中相同题面时复用上次豆包结果，避免重复请求。"""
        for cached_hash, cached_result in self._doubao_result_cache.items():
            if self._is_exact_doubao_frame(frame_hash, cached_hash):
                self._doubao_result_cache.move_to_end(cached_hash)
                return cached_result
        return None

    def _remember_doubao_result(self, frame_hash: str, result: dict):
        """保存会话内识别结果缓存，限制缓存大小。"""
        if not frame_hash:
            return

        self._doubao_result_cache[frame_hash] = result
        self._doubao_result_cache.move_to_end(frame_hash)

        max_cache_size = max(1, int(getattr(config, "DOUBAO_CACHE_SIZE", 32)))
        while len(self._doubao_result_cache) > max_cache_size:
            self._doubao_result_cache.popitem(last=False)

    def _update_stats(self):
        """更新 GUI 统计。"""
        self.gui.update_stats(self.total, self.matched, self.unmatched)

    def _update_preview(self, screenshot: np.ndarray, calc: RegionCalculator):
        """在截图上绘制区域框线并发送到 GUI 预览面板。"""
        try:
            # 转为 BGR 供 OpenCV 绘图
            annotated = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)

            # 绘制题目区域（绿色）
            qr = calc.get_pixel_region(config.QUESTION_REGION)
            cv2.rectangle(annotated, (qr[0], qr[1]), (qr[0] + qr[2], qr[1] + qr[3]),
                          (0, 255, 0), 2)
            cv2.putText(annotated, "Q", (qr[0] + 4, qr[1] + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # 绘制答案区域
            colors = [(255, 100, 100), (100, 100, 255), (255, 255, 100), (100, 255, 255)]
            for i, region_cfg in enumerate(config.ANSWER_REGIONS):
                ar = calc.get_pixel_region(region_cfg)
                color = colors[i] if i < len(colors) else (200, 200, 200)
                cv2.rectangle(annotated, (ar[0], ar[1]), (ar[0] + ar[2], ar[1] + ar[3]),
                              color, 2)
                cv2.putText(annotated, chr(65 + i), (ar[0] + 4, ar[1] + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                confirm_region = self._get_fixed_confirm_region(calc, i)
                cv2.rectangle(
                    annotated,
                    (confirm_region[0], confirm_region[1]),
                    (confirm_region[0] + confirm_region[2], confirm_region[1] + confirm_region[3]),
                    (240, 240, 240),
                    1,
                )
                cv2.putText(
                    annotated,
                    f"OK{chr(65 + i)}",
                    (confirm_region[0] + 2, max(16, confirm_region[1] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (240, 240, 240),
                    1,
                )

            # BGR -> RGB -> PIL Image
            rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            # 缩放到预览面板尺寸（约400px宽）
            preview_width = 400
            scale = preview_width / pil_img.width
            preview_height = int(pil_img.height * scale)
            pil_img = pil_img.resize((preview_width, preview_height), Image.LANCZOS)

            info_text = f"截图尺寸: {screenshot.shape[1]} x {screenshot.shape[0]}"
            self.gui.update_preview(pil_img, info_text)
        except Exception as e:
            logger.warning(f"预览更新失败: {e}")


def main():
    """程序入口。"""
    # 设置 DPI 感知
    set_dpi_awareness()

    # 创建 GUI
    gui = AppWindow()

    # 创建答题器
    bot = QuizBot(gui)
    refresh_state = {"running": False}

    def refresh_instance_choices():
        if refresh_state["running"]:
            return

        refresh_state["running"] = True
        gui.set_refreshing(True)

        def worker():
            error_message = ""
            bound_windows: list[dict] = []
            try:
                adb_path = gui.get_mumu_adb_path() or bot.detect_mumu_adb_path()
                bot.set_mumu_adb_path(adb_path)
                bound_windows = bot.list_available_mumu_window_bindings()
            except Exception as e:
                error_message = str(e)

            def finish():
                refresh_state["running"] = False
                gui.set_refreshing(False)
                if error_message:
                    gui.log(f"刷新 MuMu 实例失败: {error_message}")
                    return
                gui.set_mumu_adb_path(bot.get_mumu_adb_path())
                gui.set_target_choices(
                    bound_windows,
                    selected_window_title=bot.window_mgr._preferred_window_title,
                )
                gui.log(f"已刷新 MuMu 实例: 窗口 {len(bound_windows)} 个")

            gui.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def handle_start():
        bot.set_mumu_adb_path(gui.get_mumu_adb_path() or bot.detect_mumu_adb_path())
        bot.configure_runtime_targets(gui.get_selected_window())
        bot.start()

    def handle_auto_detect_mumu_adb_path():
        path = bot.detect_mumu_adb_path()
        if path:
            bot.set_mumu_adb_path(path)
            gui.log(f"已自动识别 MuMu adb 路径: {path}")
        else:
            gui.log("未自动识别到 MuMu adb 路径")
        return path

    # 绑定按钮事件
    gui.on_start = handle_start
    gui.on_stop = bot.stop
    gui.on_refresh_instances = refresh_instance_choices
    gui.on_auto_detect_mumu_adb_path = handle_auto_detect_mumu_adb_path

    gui.log("阴阳师答题器已就绪")
    gui.log(f"监控窗口关键词: {config.WINDOW_TITLE_KEYWORDS}")
    gui.log("点击「开始」按钮启动答题")
    detected_mumu_adb_path = bot.detect_mumu_adb_path()
    if detected_mumu_adb_path:
        bot.set_mumu_adb_path(detected_mumu_adb_path)
        gui.set_mumu_adb_path(detected_mumu_adb_path)
        gui.log(f"MuMu adb 路径: {detected_mumu_adb_path}")
    else:
        gui.log("未自动识别到 MuMu adb 路径，可手动选择 adb.exe")
    refresh_instance_choices()

    # 启动 GUI 主循环
    gui.run()


if __name__ == "__main__":
    main()
