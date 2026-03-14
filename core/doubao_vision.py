"""豆包视觉理解模块 - 使用豆包 Vision API 直接识别图片并选择答案"""

import base64
import json
import logging
import re
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)

PROMPT = """识别图片中的题目和4个选项，返回JSON格式：
{"question": "题目文字", "options": ["选项A", "选项B", "选项C", "选项D"]}
注意：必须包含全部4个选项"""

JSON_BLOCK_PATTERN = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
JSON_OBJECT_PATTERN = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}")
QUESTION_PATTERN = re.compile(r'题目.*?[是为].*?[：:"""]([^"""]+)[""""]')
QUESTION_FALLBACK_PATTERN = re.compile(r'题目[是为]?[：:]?(.+?)(?:，|。|；|选项)')
OPTIONS_PATTERN = re.compile(r'选项.*?\[([^\]]+)\]')
OPTIONS_FALLBACK_PATTERN = re.compile(r'选项.*?(?:直接)?[是为]?[：:]?(.+?)(?:。|，按|Ȼ)')


class DoubaoVision:
    """豆包视觉理解封装，直接看图识别题目和答案。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        model: str = "doubao-vision-pro",
        timeout: float = 30,
        min_interval: float = 1.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_request_ts = 0.0
        self.last_error = ""
        self._client = self._build_client()

    def _build_client(self):
        """复用 API 客户端，避免每次识别都重新创建连接配置。"""
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError("请安装 openai: pip install openai") from exc

        return OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )

    def analyze_quiz_image(self, image: np.ndarray) -> dict | None:
        """
        分析答题图片，返回识别结果。

        Args:
            image: 游戏截图（numpy 数组）

        Returns:
            dict: {
                "question": "题目文字",
                "options": ["选项A", "选项B", "选项C", "选项D"]
            }
            或 None（识别失败）
        """
        try:
            total_start = time.time()
            self._last_request_ts = total_start

            # 将图片转为 base64
            encode_start = time.time()
            mime_type, image_base64 = self._image_to_base64(image)
            encode_elapsed = time.time() - encode_start
            logger.info(f"图片编码耗时: {encode_elapsed:.3f} 秒，大小: {len(image_base64) / 1024:.1f} KB")

            # 调用豆包 Vision API
            logger.info("开始调用豆包 API...")
            api_start = time.time()
            result = self._call_vision_api(image_base64, mime_type)
            api_elapsed = time.time() - api_start

            total_elapsed = time.time() - total_start
            logger.info(f"豆包 API 调用完成，API 耗时: {api_elapsed:.2f} 秒，总耗时: {total_elapsed:.2f} 秒")

            return result

        except Exception as e:
            logger.error(f"豆包视觉识别失败: {e}")
            return None

    def _image_to_base64(self, image: np.ndarray) -> tuple[str, str]:
        """将 numpy 图像转为 base64 字符串，压缩以加快上传速度。"""
        if image.dtype != np.uint8:
            image = image.astype(np.uint8)

        working = image
        max_size = 600  # 最大边长（从800降到600以加快上传）
        height, width = working.shape[:2]
        if width > max_size or height > max_size:
            ratio = min(max_size / width, max_size / height)
            new_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
            working = cv2.resize(working, new_size, interpolation=cv2.INTER_AREA)

        bgr_image = cv2.cvtColor(working, cv2.COLOR_RGB2BGR)
        encode_params = [
            int(cv2.IMWRITE_JPEG_QUALITY), 70,
            int(cv2.IMWRITE_JPEG_OPTIMIZE), 1,
        ]
        ok, encoded = cv2.imencode(".jpg", bgr_image, encode_params)
        if not ok:
            raise ValueError("JPEG 编码失败")

        image_bytes = encoded.tobytes()
        return "image/jpeg", base64.b64encode(image_bytes).decode("utf-8")

    def _call_vision_api(self, image_base64: str, mime_type: str) -> dict | None:
        """调用豆包 Vision API。"""
        try:
            # 调用豆包 Vision API（使用标准 OpenAI 格式）
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_base64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": PROMPT
                            },
                        ],
                    }
                ],
                timeout=self.timeout,
            )

            # 解析响应
            if not response or not response.choices:
                logger.error("豆包 API 返回空内容")
                return None

            content = response.choices[0].message.content

            if not content:
                logger.error("豆包 API 返回空文本")
                return None

            # 打印豆包返回的原始内容（用于调试）
            logger.info(f"豆包返回原始内容: {content}")

            # 解析 JSON 结果
            # 尝试提取 JSON（可能被包裹在 markdown 代码块中）
            json_match = JSON_BLOCK_PATTERN.search(content)
            if json_match:
                content = json_match.group(1)
            else:
                # 尝试直接提取第一个 JSON 对象（非贪婪匹配）
                json_match = JSON_OBJECT_PATTERN.search(content)
                if json_match:
                    content = json_match.group(0)

            # 处理转义字符（豆包可能返回带 \n 的字符串）
            content = content.replace('\\n', '\n').replace('\\"', '"')

            try:
                result = json.loads(content)
                # 验证结果格式（只需要 question 和 options）
                if "question" in result and "options" in result:
                    return result
                else:
                    logger.error(f"豆包返回格式不正确: {result}")
                    return None
            except json.JSONDecodeError as e:
                # JSON 解析失败，尝试从文本中提取信息
                logger.warning(f"JSON 解析失败，尝试从文本提取: {e}")

                # 尝试从文本中提取题目和选项
                # 匹配模式：题目是"xxx"
                question_match = QUESTION_PATTERN.search(content)
                if not question_match:
                    # 尝试另一种模式：题目是xxx
                    question_match = QUESTION_FALLBACK_PATTERN.search(content)

                # 匹配选项数组：["A", "B", "C", "D"]
                options_match = OPTIONS_PATTERN.search(content)
                if not options_match:
                    # 尝试匹配：选项直接是A、B、C、D
                    options_match = OPTIONS_FALLBACK_PATTERN.search(content)

                if question_match and options_match:
                    question = question_match.group(1).strip()
                    options_str = options_match.group(1)

                    # 解析选项列表
                    if '[' in options_str:
                        # JSON 数组格式
                        options = [opt.strip(' "\'') for opt in options_str.split(',')]
                    else:
                        # 文本格式：A、B、C、D
                        options = [opt.strip() for opt in re.split(r'[、，,]', options_str) if opt.strip()]

                    result = {
                        "question": question,
                        "options": options
                    }
                    logger.info(f"从文本提取成功: {result}")
                    return result

                logger.error(f"无法从文本提取信息\n内容: {content}")
                return None

        except Exception as e:
            logger.error(f"豆包 API 调用失败: {e}")
            return None
