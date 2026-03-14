"""图像预处理工具 - 裁剪区域和OCR前增强"""

import cv2
import numpy as np


def crop_region(image: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """从图像中裁剪指定矩形区域。"""
    img_h, img_w = image.shape[:2]
    # 确保不越界
    x = max(0, min(x, img_w - 1))
    y = max(0, min(y, img_h - 1))
    w = min(w, img_w - x)
    h = min(h, img_h - y)
    return image[y:y + h, x:x + w]


def preprocess_for_ocr(image: np.ndarray, scale_factor: float = 2.0) -> np.ndarray:
    """
    图像预处理流水线，提升 OCR 识别准确率。

    流程：灰度 → 放大 → 双边滤波去噪 → 自适应二值化 → 转回RGB
    """
    if image is None or image.size == 0:
        return image

    # 灰度化
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image

    # 放大（小文字变清晰）
    if scale_factor > 1.0:
        h, w = gray.shape
        new_w, new_h = int(w * scale_factor), int(h * scale_factor)
        gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    # CLAHE 增强对比度（对游戏 UI 小字更友好）
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # 双边滤波去噪（保留边缘）
    denoised = cv2.bilateralFilter(enhanced, 9, 75, 75)

    # 自适应阈值二值化（去除游戏背景花纹）
    binary = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11, 2
    )

    # PaddleOCR 需要 3 通道输入
    rgb = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)
    return rgb
