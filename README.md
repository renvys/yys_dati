# 阴阳师答题器

一个面向 Windows 的阴阳师答题辅助工具。

程序会从 MuMu 模拟器窗口抓取当前答题画面，识别题目与选项，匹配本地题库，并自动点击答案；在需要二阶段确认的场景下，也会继续检测并点击对应确认按钮。

## 项目说明

本项目主要由 AI 编写，人工负责测试、验收和迭代修正。

## 功能概览

- 自动识别题目和四个选项
- 本地题库模糊匹配答案
- 必须配置豆包视觉识别
- 支持 MuMu 多实例窗口选择与 `adb` 绑定
- 支持二阶段固定确认按钮检测与点击
- 显式状态机控制点击、确认和切题等待
- GUI 内展示日志、命中统计和本次运行时长
- 支持打包为可分发的 Windows `exe`

## 工作流程

1. 枚举 MuMu 窗口并绑定对应实例的 `adb` 端口。
2. 截取题目区域和选项区域。
3. 使用豆包视觉识别题目与选项文本。
4. 在本地题库中进行模糊匹配。
5. 点击命中的选项。
6. 若进入二阶段，继续检测固定确认按钮并点击。
7. 等待题目变化，再进入下一轮识别。

## 当前实现

- GUI：Tkinter
- 识别：Doubao Vision
- 点击：鼠标 / 窗口消息 / MuMu `adb`
- 平台：仅 Windows

核心入口：

- 源码入口：[`main.py`](./main.py)
- 运行脚本：[`run.bat`](./run.bat)、[`run.ps1`](./run.ps1)
- 打包脚本：[`build_exe.bat`](./build_exe.bat)、[`build_exe.ps1`](./build_exe.ps1)
- PyInstaller 配置：[`yys_dati.spec`](./yys_dati.spec)

## 环境要求

- Windows 10 / 11
- Python 3.12 左右
- MuMu Player 12
- MuMu 窗口分辨率必须设置为 `960 x 540`
- 阴阳师答题界面保持可见

不支持 macOS / Linux。

## 安装依赖

建议使用虚拟环境：

```powershell
cd <repo-dir>
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

当前主要依赖包括：

- `paddlepaddle`
- `paddleocr`
- `opencv-python`
- `rapidfuzz`
- `pywin32`
- `openai`

## 配置说明

主要配置文件：[`config.py`](./config.py)

常用配置项：

- `WINDOW_TITLE_KEYWORDS`
  - MuMu 窗口标题匹配关键字
- `QUESTION_REGION` / `ANSWER_REGIONS`
  - 题目和选项区域的相对坐标
- `USE_DOUBAO_VISION`
  - 是否启用豆包视觉识别
- `DOUBAO_*`
  - 豆包接入点、接口地址、超时、触发间隔等
- `CLICK_MODE`
  - 点击后端，当前默认 `mumu_adb`
- `MUMU_ADB_PATH`
  - MuMu `adb.exe` 路径
- `SECOND_STAGE_*`
  - 二阶段确认按钮检测、冷却、切题等待等参数
- `DEBUG_LOGS`
  - 是否输出调试日志

### `secrets.json`

本项目必须使用豆包 API Key，需在项目根目录提供 `secrets.json`。可直接参考模板：[`secrets.json.example`](./secrets.json.example)

```json
{
  "doubao_api_key": "your-api-key-here",
  "doubao_model": "ep-your-endpoint-id"
}
```

配置说明：

- `doubao_api_key`
  - 火山引擎在线推理使用的 API Key
- `doubao_model`
  - 你创建好的自定义推理接入点 ID，通常形如 `ep-xxxxxx`
  - 这里填写的是接入点 ID，不是直接填写 `Doubao-1.5-vision-pro-32k`

申请与创建方式：

1. 打开 [火山引擎控制台](https://console.volcengine.com/)
2. 进入“在线推理”
3. 创建“自定义推理接入点”
4. 在“指定单一模型”中选择 `Doubao-1.5-vision-pro-32k`
5. 创建完成后，记录 API Key 和接入点 ID
6. 将它们填入 `secrets.json`

说明：

- 开发环境下缺少 `secrets.json` 时，可以手动复制模板后填写。
- 打包后的程序若缺少该文件，会尝试自动生成模板。
- 未配置有效的 `doubao_api_key` 或 `doubao_model` 时，程序无法按预期正常使用。

## 运行

### 方式 1：直接运行源码

```powershell
cd <repo-dir>
.venv\Scripts\python.exe main.py
```

### 方式 2：使用启动脚本

```powershell
cd <repo-dir>
.\run.ps1
```

或：

```cmd
run.bat
```

## 使用方式

1. 启动程序。
2. 确认 MuMu 窗口分辨率已设置为 `960 x 540`。
3. 确认 MuMu `adb.exe` 路径正确。
4. 点击“刷新”加载当前 MuMu 实例。
5. 在窗口列表中选择目标实例。
6. 点击“开始”。

运行时界面会显示：

- 当前状态
- 匹配命中 / 未命中统计
- 本次运行时长
- 实时日志

说明：

- 当没有可用 MuMu 窗口时，“开始”按钮会保持禁用。
- 刷新窗口列表是异步执行的，目的是避免 GUI 卡死。
- 列表会按排序默认选中第一个可用 MuMu 窗口，不再显示“自动匹配窗口”选项。

## 打包

项目使用 PyInstaller 的 `one-dir` 方式打包。

```cmd
build_exe.bat
```

或：

```powershell
cd <repo-dir>
.\build_exe.ps1
```

输出目录：

- [`dist/yys_dati`](./dist/yys_dati)
- [`dist/yys_dati/yys_dati.exe`](./dist/yys_dati/yys_dati.exe)
- [`dist/yys_dati.zip`](./dist/yys_dati.zip)

当前打包说明：

- 分发时应直接发送整个 `dist/yys_dati` 目录，或发送压缩包 `dist/yys_dati.zip`。
- 打包结果不是单文件 `exe`。
- 打包版会附带 `secrets.json.example`，缺少正式配置时会自动提示补充豆包 API Key。
- 目前打包脚本中的 Python 解释器路径是固定配置；如果换机器打包，需要先调整脚本中的解释器路径。

## 项目结构

```text
yys_dati/
├─ core/
│  ├─ clicker.py              点击后端
│  ├─ doubao_vision.py        豆包视觉封装
│  ├─ ocr_engine.py           本地 OCR 封装
│  ├─ question_matcher.py     本地题库匹配
│  ├─ region_calculator.py    相对区域换算
│  └─ window_manager.py       MuMu 窗口与实例绑定
├─ data/
│  ├─ question_bank.json      题库
│  └─ confirm_templates/      固定确认按钮模板
├─ gui/
│  └─ app_window.py           主界面
├─ utils/
│  └─ image_utils.py          图像辅助处理
├─ main.py                    主流程 / 状态机
├─ config.py                  全局配置
├─ run.bat                    启动脚本
├─ build_exe.bat              打包脚本
└─ yys_dati.spec              PyInstaller 配置
```

## 已知限制

- 仅适配 Windows。
- MuMu 窗口分辨率必须为 `960 x 540`，否则区域识别和点击坐标会明显偏移。
- 题目区域、选项区域、确认区域都依赖当前游戏 UI 布局。
- 模拟器分辨率、缩放、皮肤变化会直接影响识别与点击稳定性。
- 二阶段确认按钮识别基于当前模板和区域限制，不保证对未来 UI 改版仍然有效。
- 豆包识别速度受网络和接口响应影响。
- OCR 或视觉识别如果返回缺失选项，仍可能导致当前轮次等待更久或跳过点击。

## 常见问题

### 启动后“开始”按钮不可点击

通常是因为没有识别到可用 MuMu 窗口，或尚未选择目标实例。先检查 MuMu 是否已启动，再点击“刷新”。

### 没有配置豆包 API Key 会怎样

程序无法按预期正常使用，应先补齐 `secrets.json` 并填入可用的 `doubao_api_key` 和 `doubao_model`。

### 为什么打包后体积依然不小

主要体积来自 OCR 推理依赖和底层动态库，例如 `paddlepaddle`、`paddleocr`、OpenBLAS 等；目前已经做过一轮瘦身，但不可能压到普通脚本工具的体积。

### 为什么偶尔会重复点击或等待偏久

当前已经加入显式状态机、题面双通道变化判断、确认点击冷却和超时回退，但游戏切题动画、识别延迟、窗口抖动、接口波动仍会影响自动化行为，通常需要结合日志继续调整参数。

## 免责声明

本项目主要用于个人学习、图像识别实验和桌面自动化测试。使用前请自行评估风险。
