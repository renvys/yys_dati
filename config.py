"""阴阳师答题器全局配置。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

# ============================================================
# 窗口识别
# ============================================================
WINDOW_TITLE_KEYWORDS = ["MuMuNxDevice", "MuMu"]
WINDOW_PROCESS_KEYWORDS = ["MuMuNxDevice"]

# ============================================================
# 区域坐标（比例值，相对窗口宽高）
# ============================================================
QUESTION_REGION = {
    "x_ratio": 0.70,
    "y_ratio": 0.05,
    "w_ratio": 0.26,
    "h_ratio": 0.12,
}

ANSWER_REGIONS = [
    {"x_ratio": 0.74, "y_ratio": 0.24, "w_ratio": 0.16, "h_ratio": 0.08},  # A
    {"x_ratio": 0.74, "y_ratio": 0.40, "w_ratio": 0.16, "h_ratio": 0.08},  # B
    {"x_ratio": 0.74, "y_ratio": 0.55, "w_ratio": 0.16, "h_ratio": 0.08},  # C
    {"x_ratio": 0.74, "y_ratio": 0.70, "w_ratio": 0.16, "h_ratio": 0.08},  # D
]

# ============================================================
# OCR
# ============================================================
OCR_LANG = "ch"
OCR_USE_ANGLE_CLS = True
OCR_USE_GPU = False
OCR_CONFIDENCE_THRESHOLD = 0
OCR_QUESTION_CONFIDENCE_THRESHOLD = 0.55
OCR_OPTION_CONFIDENCE_THRESHOLD = 0.20

# 豆包视觉理解 API（可选，用于直接看图识别题目和答案）
USE_DOUBAO_VISION = True
DOUBAO_API_KEY = "132ca775-7c4a-47e8-bf9f-adbd101f9075"
DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_MODEL = "ep-20260313205708-qnj75"
DOUBAO_TIMEOUT = 30
DOUBAO_MIN_INTERVAL = 0.6
DOUBAO_TRIGGER_STABLE_FRAMES = 2
DOUBAO_HASH_SIZE = 12
DOUBAO_HASH_DISTANCE_THRESHOLD = 6
DOUBAO_CACHE_SIZE = 32

# ============================================================
# 匹配
# ============================================================
FUZZY_MATCH_THRESHOLD = 75
ANSWER_MATCH_THRESHOLD = 70

# ============================================================
# 时间
# ============================================================
LOOP_INTERVAL = 0.2
CLICK_DELAY = 0.3
POST_CLICK_DELAY = 0

# ============================================================
# 点击
# ============================================================
CLICK_MODE = "mumu_adb"
CLICK_RANDOM_OFFSET = 5
RESTORE_MOUSE_POSITION = True
MUMU_ADB_PATH = r"D:\games\MuMu Player 12\shell\adb.exe"
MUMU_ADB_SERIAL = "127.0.0.1:16384"
MUMU_DEVICE_WIDTH = 960
MUMU_DEVICE_HEIGHT = 540
MUMU_ADB_CANDIDATE_PORTS = [5555, 5557, 16384, 16416, 7555]

# 选项 OCR 重试
OPTION_OCR_RETRY_COUNT = 100
OPTION_OCR_RETRY_DELAY = 0.25

# ============================================================
# 图像预处理
# ============================================================
PREPROCESSING_SCALE_FACTOR = 2.5

# ============================================================
# 路径
# ============================================================
QUESTION_BANK_PATH = str(DATA_DIR / "question_bank.json")
ENABLE_SECOND_STAGE_CONFIRM = True
SECOND_STAGE_CONFIRM_TIMEOUT = 0.60
SECOND_STAGE_CONFIRM_POLL_INTERVAL = 0.03
SECOND_STAGE_CONFIRM_AFTER_CLICK_TIMEOUT = 0.45
SECOND_STAGE_CONFIRM_CLICK_DELAY = 0.05
SECOND_STAGE_CONFIRM_RECLICK_INTERVAL = 4.0
SECOND_STAGE_CONFIRM_TEMPLATE_PATHS = [
    str(DATA_DIR / "confirm_templates" / "confirm_template_A.png"),
    str(DATA_DIR / "confirm_templates" / "confirm_template_B.png"),
    str(DATA_DIR / "confirm_templates" / "confirm_template_D.png"),
]
SECOND_STAGE_CONFIRM_TEMPLATE_THRESHOLD = 0.30
SECOND_STAGE_CONFIRM_TRIGGER_DELAY = 0.12
SECOND_STAGE_CONFIRM_MIN_PRESENT_FRAMES = 1
SECOND_STAGE_SELECTION_RETRY_COUNT = 0
SECOND_STAGE_SELECTED_MIN_GOLD_RATIO = 0.004
SECOND_STAGE_SELECTED_MIN_GOLD_BORDER_RATIO = 0.012
SECOND_STAGE_SELECTED_MIN_VALUE_MEAN = 145.0
SECOND_STAGE_CONFIRM_REGIONS = [
    {"x_ratio": 0.92, "y_ratio": 0.235, "w_ratio": 0.075, "h_ratio": 0.09},  # A
    {"x_ratio": 0.92, "y_ratio": 0.395, "w_ratio": 0.075, "h_ratio": 0.09},  # B
    {"x_ratio": 0.92, "y_ratio": 0.545, "w_ratio": 0.075, "h_ratio": 0.09},  # C
    {"x_ratio": 0.92, "y_ratio": 0.695, "w_ratio": 0.075, "h_ratio": 0.09},  # D
]
SECOND_STAGE_CONFIRM_FIXED_MIN_DIFF_RATIO = 0.015
SECOND_STAGE_CONFIRM_FIXED_MIN_MEAN_DIFF = 4.0
SECOND_STAGE_CONFIRM_FIXED_MIN_SATURATION = 45
SECOND_STAGE_CONFIRM_FIXED_MIN_VALUE = 105
SECOND_STAGE_CONFIRM_FIXED_MIN_MASK_RATIO = 0.08
SECOND_STAGE_CONFIRM_FIXED_MIN_AREA_RATIO = 0.05
UNMATCHED_LOG_PATH = str(DATA_DIR / "unmatched.log")
