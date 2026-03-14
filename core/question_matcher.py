"""题库匹配模块 - 加载题库并进行模糊匹配"""

import json
import re
import logging
from pathlib import Path

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


class QuestionMatcher:
    """加载 JSON 题库，用模糊匹配查找答案。"""

    def __init__(self, bank_path: str):
        self.questions = []
        self.question_texts = []

        # 预计算清洗后的文本，避免每次匹配都重复清洗（也便于做“按字分词”的匹配）
        self._cleaned_question_texts: list[str] = []
        self._spaced_cleaned_question_texts: list[str] = []

        self.load_bank(bank_path)

    def load_bank(self, path: str):
        """加载 JSON 题库文件。"""
        path = Path(path)
        if not path.exists():
            logger.error(f"题库文件不存在: {path}")
            self.questions = []
            self.question_texts = []
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.questions = data.get("questions", [])
        self.question_texts = [q["question"] for q in self.questions]

        self._cleaned_question_texts = [self._clean_text(q) for q in self.question_texts]
        self._spaced_cleaned_question_texts = [" ".join(q) for q in self._cleaned_question_texts]

        logger.info(f"已加载题库: {len(self.questions)} 道题目")

    def find_answer(self, ocr_question: str, threshold: int = 75) -> dict | None:
        """
        用模糊匹配在题库中查找最匹配的题目。

        Args:
            ocr_question: OCR 识别出的题目文字
            threshold: 最低匹配分数 (0-100)

        Returns:
            匹配结果 dict（含 question, answer, score, options）或 None
        """
        if not ocr_question or len(ocr_question.strip()) < 2:
            return None

        if not self.question_texts:
            logger.warning("题库为空，无法匹配")
            return None

        cleaned = self._clean_text(ocr_question)
        if not cleaned:
            return None

        # 多策略匹配（按顺序尝试，命中即返回）：
        # 1) token_set_ratio：对“词集合”相似度鲁棒
        # 2) partial_ratio：对“只识别到题目的一部分”鲁棒
        # 3) WRatio + “按字加空格”：对中文单字误识、缺字更鲁棒

        result = process.extractOne(
            cleaned,
            self._cleaned_question_texts,
            scorer=fuzz.token_set_ratio,
            score_cutoff=threshold,
        )

        if result is None:
            result = process.extractOne(
                cleaned,
                self._cleaned_question_texts,
                scorer=fuzz.partial_ratio,
                score_cutoff=threshold,
            )

        if result is None:
            spaced = " ".join(cleaned)
            result = process.extractOne(
                spaced,
                self._spaced_cleaned_question_texts,
                scorer=fuzz.WRatio,
                score_cutoff=threshold,
            )

        if result is None:
            return None

        _matched_text, score, index = result
        question_data = self.questions[index]
        return {
            "question": question_data["question"],
            "answer": question_data["answer"],
            "score": score,
            "options": question_data.get("options", []),
        }

    def log_unmatched(self, ocr_text: str, log_path: str):
        """将未匹配的题目记录到日志文件，便于后续手动添加。"""
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{ocr_text}\n")
        except Exception as e:
            logger.error(f"写入未匹配日志失败: {e}")

    @staticmethod
    def _clean_text(text: str) -> str:
        """去除空白和标点，提高匹配率。"""
        # 去除空白
        text = re.sub(r'\s+', '', text)
        # 去除标点符号（包括中英文）
        text = re.sub(r"[，。？！、；：\"'（）【】《》,.?!;:()\[\]{}<>]", "", text)
        # 去除常见 OCR 噪声字符（点、省略号等）
        text = re.sub(r'[\.。…]+', '', text)
        # 只去除前后孤立的单个 ASCII 噪声字符，避免把 SR/SSR/SP 或题目中的有效数字删掉
        text = re.sub(r'^[a-zA-Z](?=[\u4e00-\u9fff])', '', text)
        text = re.sub(r'(?<=[\u4e00-\u9fff])[a-zA-Z]$', '', text)
        return text.strip()
