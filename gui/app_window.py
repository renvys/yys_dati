"""GUI 界面模块 - tkinter 图形界面"""

import time
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk


class AppWindow:
    """阴阳师答题器的图形用户界面。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("阴阳师答题器")
        self.root.geometry("760x560")
        self.root.resizable(True, True)

        self.running = False
        self.on_start = None
        self.on_stop = None
        self.on_auto_detect_mumu_adb_path = None
        self.on_refresh_instances = None

        self.total_count = 0
        self.matched_count = 0
        self.unmatched_count = 0
        self.elapsed_seconds = 0
        self._run_started_at = None
        self._runtime_after_id = None

        self._last_log_message = None
        self._last_log_repeat_count = 0
        self._window_choices: dict[str, dict | None] = {}
        self.mumu_adb_path_var = tk.StringVar()

        self._build_ui()

    def _build_ui(self):
        """构建界面元素。"""
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(main_frame)
        left_frame.pack(fill=tk.BOTH, expand=True)

        ctrl_frame = tk.Frame(left_frame)
        ctrl_frame.pack(fill=tk.X, padx=10, pady=5)

        self.start_btn = tk.Button(
            ctrl_frame,
            text="▶ 开始",
            command=self._toggle,
            width=12,
            height=2,
            font=("Microsoft YaHei", 10, "bold"),
            bg="#4CAF50",
            fg="white",
            state=tk.DISABLED,
        )
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.status_label = tk.Label(
            ctrl_frame,
            text="状态: 已停止",
            fg="red",
            font=("Microsoft YaHei", 10),
        )
        self.status_label.pack(side=tk.LEFT, padx=15)

        instance_frame = tk.LabelFrame(left_frame, text="MuMu 实例", font=("Microsoft YaHei", 9))
        instance_frame.pack(fill=tk.X, padx=10, pady=5)

        path_row = tk.Frame(instance_frame)
        path_row.pack(fill=tk.X, padx=6, pady=(6, 3))

        tk.Label(
            path_row,
            text="ADB路径:",
            width=8,
            anchor="w",
            font=("Microsoft YaHei", 9),
        ).pack(side=tk.LEFT)
        self.path_entry = tk.Entry(
            path_row,
            textvariable=self.mumu_adb_path_var,
            font=("Consolas", 9),
        )
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.auto_path_btn = tk.Button(
            path_row,
            text="自动",
            width=6,
            command=self._auto_detect_mumu_adb_path,
            font=("Microsoft YaHei", 9),
        )
        self.auto_path_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.browse_path_btn = tk.Button(
            path_row,
            text="浏览",
            width=6,
            command=self._browse_mumu_adb_path,
            font=("Microsoft YaHei", 9),
        )
        self.browse_path_btn.pack(side=tk.LEFT, padx=(6, 0))

        window_row = tk.Frame(instance_frame)
        window_row.pack(fill=tk.X, padx=6, pady=(3, 6))

        tk.Label(
            window_row,
            text="窗口:",
            width=8,
            anchor="w",
            font=("Microsoft YaHei", 9),
        ).pack(side=tk.LEFT)
        self.window_combo = ttk.Combobox(
            window_row,
            state="disabled",
            font=("Microsoft YaHei", 9),
        )
        self.window_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.refresh_btn = tk.Button(
            window_row,
            text="刷新",
            width=8,
            command=self._refresh_instances,
            font=("Microsoft YaHei", 9),
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=(6, 0))

        stats_frame = tk.LabelFrame(left_frame, text="统计", font=("Microsoft YaHei", 9))
        stats_frame.pack(fill=tk.X, padx=10, pady=5)

        self.stats_label = tk.Label(
            stats_frame,
            text=self._render_stats_text(),
            font=("Microsoft YaHei", 10),
        )
        self.stats_label.pack(padx=5, pady=5)

        log_frame = tk.LabelFrame(left_frame, text="运行日志", font=("Microsoft YaHei", 9))
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=18,
            state=tk.DISABLED,
            font=("Consolas", 9),
            wrap=tk.WORD,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        tip_label = tk.Label(
            left_frame,
            text="提示: 将鼠标移到屏幕左上角可紧急停止 | 请先调整 config.py 中的区域坐标",
            font=("Microsoft YaHei", 8),
            fg="gray",
        )
        tip_label.pack(pady=3)

    def _toggle(self):
        """切换开始/停止状态。"""
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        """开始运行。"""
        if not self.get_selected_window():
            return

        self.running = True
        self.elapsed_seconds = 0
        self._run_started_at = time.time()
        self.start_btn.config(text="■ 停止", bg="#f44336", state=tk.NORMAL)
        self.refresh_btn.config(state=tk.DISABLED)
        self.auto_path_btn.config(state=tk.DISABLED)
        self.browse_path_btn.config(state=tk.DISABLED)
        self.path_entry.config(state=tk.DISABLED)
        self.window_combo.config(state="disabled")
        self.status_label.config(text="状态: 运行中", fg="green")
        self._refresh_stats()
        self._schedule_runtime_refresh()
        if self.on_start:
            self.on_start()

    def stop(self):
        """停止运行。"""
        self.running = False
        if self._runtime_after_id is not None:
            self.root.after_cancel(self._runtime_after_id)
            self._runtime_after_id = None
        if self._run_started_at is not None:
            self.elapsed_seconds = max(0, int(time.time() - self._run_started_at))
        self._run_started_at = None
        self.start_btn.config(text="▶ 开始", bg="#4CAF50")
        self.refresh_btn.config(state=tk.NORMAL)
        self.auto_path_btn.config(state=tk.NORMAL)
        self.browse_path_btn.config(state=tk.NORMAL)
        self.path_entry.config(state=tk.NORMAL)
        self.window_combo.config(state="readonly" if self._has_window_choices() else "disabled")
        self.status_label.config(text="状态: 已停止", fg="red")
        self._refresh_stats()
        self._update_start_button_state()
        if self.on_stop:
            self.on_stop()

    def log(self, message: str):
        """线程安全地添加日志消息。"""
        timestamp = time.strftime("%H:%M:%S")
        self.root.after(0, self._append_log, timestamp, message)

    def _append_log(self, timestamp: str, message: str):
        self._last_log_message = message
        self._last_log_repeat_count = 1
        full_msg = f"[{timestamp}] {message}"
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, full_msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def update_stats(self, total: int, matched: int, unmatched: int):
        """线程安全地更新统计信息。"""
        self.total_count = total
        self.matched_count = matched
        self.unmatched_count = unmatched
        self.root.after(0, self._refresh_stats)

    def _refresh_stats(self):
        self.stats_label.config(text=self._render_stats_text())

    def _render_stats_text(self) -> str:
        runtime_text = self._format_elapsed(self.elapsed_seconds)
        return (
            f"运行时长: {runtime_text}  |  已答题: {self.total_count}  |  "
            f"匹配成功: {self.matched_count}  |  未匹配: {self.unmatched_count}"
        )

    @staticmethod
    def _format_elapsed(total_seconds: int) -> str:
        hours, remainder = divmod(max(0, int(total_seconds)), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _schedule_runtime_refresh(self):
        if not self.running:
            self._runtime_after_id = None
            return
        self._refresh_runtime()
        self._runtime_after_id = self.root.after(1000, self._schedule_runtime_refresh)

    def _refresh_runtime(self):
        if self.running and self._run_started_at is not None:
            self.elapsed_seconds = max(0, int(time.time() - self._run_started_at))
            self._refresh_stats()

    def update_preview(self, pil_image, info_text: str = ""):
        """预览面板已移除，保留空接口兼容主流程调用。"""
        return

    def set_refreshing(self, refreshing: bool):
        """更新实例刷新按钮状态，避免刷新期间重复点击。"""
        self.root.after(0, self._set_refreshing, refreshing)

    def _set_refreshing(self, refreshing: bool):
        if self.running:
            self.refresh_btn.config(text="刷新", state=tk.DISABLED)
            return

        if refreshing:
            self.refresh_btn.config(text="刷新中", state=tk.DISABLED)
            self.start_btn.config(state=tk.DISABLED)
            self.auto_path_btn.config(state=tk.DISABLED)
            self.browse_path_btn.config(state=tk.DISABLED)
            self.path_entry.config(state=tk.DISABLED)
            self.window_combo.config(state="disabled")
            return

        self.refresh_btn.config(text="刷新", state=tk.NORMAL)
        self.auto_path_btn.config(state=tk.NORMAL)
        self.browse_path_btn.config(state=tk.NORMAL)
        self.path_entry.config(state=tk.NORMAL)
        self.window_combo.config(state="readonly" if self._has_window_choices() else "disabled")
        self._update_start_button_state()

    def set_target_choices(
        self,
        windows: list[dict],
        selected_window_title: str = "",
    ):
        """更新 MuMu 窗口候选列表。"""
        self._window_choices = {}
        window_labels: list[str] = []
        preferred_window_label = ""

        for window in windows:
            label = self._format_window_label(window)
            self._window_choices[label] = window
            window_labels.append(label)
            if selected_window_title and window.get("title") == selected_window_title:
                preferred_window_label = label

        self.window_combo["values"] = window_labels
        if preferred_window_label:
            self.window_combo.set(preferred_window_label)
        elif window_labels:
            self.window_combo.set(window_labels[0])
        else:
            self.window_combo.set("")

        if not self.running:
            self.window_combo.config(state="readonly" if self._has_window_choices() else "disabled")
        self._update_start_button_state()

    def get_selected_window(self) -> dict | None:
        """返回当前选择的窗口实例。"""
        return self._window_choices.get(self.window_combo.get())

    def get_mumu_adb_path(self) -> str:
        """返回当前界面上的 MuMu adb.exe 路径。"""
        return self.mumu_adb_path_var.get().strip()

    def set_mumu_adb_path(self, path: str):
        """更新界面上的 MuMu adb.exe 路径。"""
        self.mumu_adb_path_var.set((path or "").strip())

    def _refresh_instances(self):
        if self.on_refresh_instances:
            self.on_refresh_instances()

    def _auto_detect_mumu_adb_path(self):
        if not self.on_auto_detect_mumu_adb_path:
            return
        path = self.on_auto_detect_mumu_adb_path()
        if path:
            self.set_mumu_adb_path(path)

    def _browse_mumu_adb_path(self):
        path = filedialog.askopenfilename(
            title="选择 MuMu adb.exe",
            filetypes=[("adb.exe", "adb.exe"), ("可执行文件", "*.exe"), ("所有文件", "*.*")],
        )
        if path:
            self.set_mumu_adb_path(path)

    def _has_window_choices(self) -> bool:
        return bool(self._window_choices)

    def _update_start_button_state(self):
        if self.running:
            return
        self.start_btn.config(state=tk.NORMAL if self.get_selected_window() else tk.DISABLED)

    @staticmethod
    def _format_window_label(window: dict) -> str:
        title = str(window.get("title", "")).strip() or "未命名窗口"
        hwnd = window.get("hwnd")
        width = window.get("width", 0)
        height = window.get("height", 0)
        instance_index = window.get("instance_index")
        adb_serial = str(window.get("adb_serial", "") or "").strip()
        prefix = f"实例 {instance_index} | " if instance_index is not None else ""
        suffix = f" | {adb_serial}" if adb_serial else ""
        return f"{prefix}{title}{suffix} [hwnd={hwnd}] {width}x{height}"

    def run(self):
        """启动 GUI 主循环。"""
        self.root.mainloop()
