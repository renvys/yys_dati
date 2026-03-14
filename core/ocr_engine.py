"""OCR engine wrapper built on PaddleOCR only."""

import logging

import numpy as np

logger = logging.getLogger(__name__)


class OCREngine:
    """Provide a small uniform OCR interface for the rest of the app."""

    def __init__(
        self,
        lang: str = "ch",
        use_angle_cls: bool = True,
        use_gpu: bool = False,
    ):
        logger.info("正在初始化 PaddleOCR...")
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ImportError("请安装 PaddleOCR: pip install paddlepaddle paddleocr") from exc

        self.lang = lang
        self.ocr = PaddleOCR(
            use_angle_cls=use_angle_cls,
            lang=lang,
            show_log=False,
            use_gpu=use_gpu,
        )
        logger.info("PaddleOCR 初始化完成")

    def _recognize_paddle(self, image: np.ndarray, confidence_threshold: float) -> list[dict]:
        """Use PaddleOCR and return normalized results."""
        try:
            result = self.ocr.ocr(image, cls=True)
        except Exception as exc:
            logger.error(f"OCR 识别出错: {exc}")
            return []

        if not result or not result[0]:
            return []

        parsed = []
        for line in result[0]:
            bbox = line[0]
            text = line[1][0]
            confidence = line[1][1]

            if confidence >= confidence_threshold:
                parsed.append(
                    {
                        "text": text,
                        "confidence": confidence,
                        "bbox": bbox,
                    }
                )

        parsed.sort(key=lambda item: (item["bbox"][0][1], item["bbox"][0][0]))
        return parsed

    def recognize(self, image: np.ndarray, confidence_threshold: float = 0.6) -> list[dict]:
        """Run OCR and return structured results."""
        if image is None or image.size == 0:
            return []
        return self._recognize_paddle(image, confidence_threshold)

    def recognize_text(self, image: np.ndarray, confidence_threshold: float = 0.6) -> str:
        """Run OCR and concatenate all detected text."""
        results = self.recognize(image, confidence_threshold)
        return "".join(item["text"] for item in results)
