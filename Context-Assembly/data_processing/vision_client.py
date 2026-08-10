"""
vision_client.py — Client gọi Ollama API cho Qwen2-VL 7B.

Chiến lược chống OOM trên RTX 2080 Ti (11 GB VRAM):
──────────────────────────────────────────────────────
1. Resize ảnh về ≤ OCR_MAX_IMAGE_SIZE px trước khi gửi.
2. Chỉ gửi 1 request tại một thời điểm (OCR_CONCURRENT_REQUESTS=1).
3. num_ctx=2048 thay vì 4096 mặc định.
4. Dùng OLLAMA_FLASH_ATTENTION=1 (env var).
"""

from __future__ import annotations

import base64
import io
import logging
import time
from typing import Literal

import requests
from PIL import Image

from .config import (
    OCR_MAX_IMAGE_SIZE,
    OLLAMA_BASE_URL,
    OLLAMA_MAX_RETRIES,
    OLLAMA_OPTIONS,
    OLLAMA_TIMEOUT_SEC,
    QWEN2_VL_MODEL,
)

log = logging.getLogger(__name__)

# ─── Prompts cho từng chế độ ────────────────────────────────────────────────

_PROMPT_IMAGE = """\
You are an expert at analyzing academic figures and images.
Examine this image carefully and provide a concise description.

Rules:
- If it is a diagram or architectural diagram: describe main components and flow in 2-3 sentences.
- If it is a photo or illustration: write one concise descriptive sentence.
- Do NOT add preamble like "This image shows..." — start directly with content.
- Wrap your response in a blockquote: > [Image] ...
"""

_PROMPT_FIGURE = """\
You are an expert data analyst and computer vision specialist.
Examine this academic chart, graph, or plot image.

STRICT INSTRUCTIONS:
1. Identify chart type (e.g. Bar Chart, Line Graph, Scatter Plot, Heatmap, Confusion Matrix).
2. Summarize key findings, axes, units, and main trends in 2-3 concise sentences.
3. If data values or a data table can be extracted accurately from the chart/plot, provide a compact Markdown table below the summary.
4. Format:
   > **[Figure Analysis]** <Summary of trends and key findings>

   | <Axis/Category> | <Value/Metric> |
   | --- | --- |
"""

_PROMPT_MATH = """\
You are an expert LaTeX typesetter specializing in mathematical notation.
Convert the mathematical content in this image to clean, accurate LaTeX.

STRICT RULES:
1. Return ONLY LaTeX — no explanation, no prose, no preamble like "The equation is...".
2. Display equations (standalone, centered): wrap in $$...$$
   Example: $$\\frac{\\partial L}{\\partial \\theta} = \\sum_{i=1}^{N} x_i$$
3. Inline formulas or simple expressions: wrap in $...$
   Example: $f(x) = ax^2 + bx + c$
4. Multiple equations separated by blank lines:
   $$E = mc^2$$
   
   $$F = ma$$
5. If there is an equation number like (1) or (3.2) at the right margin, include it:
   $$\\mathcal{L}(\\theta) = \\mathbb{E}[\\log p(x)] \\tag{1}$$
6. Align environments for multi-line equations:
   $$\\begin{aligned}
     a &= b + c \\\\
     &= d + e
   \\end{aligned}$$
7. Greek letters: \\alpha \\beta \\gamma \\theta \\sigma \\mu \\lambda \\omega \\nabla \\partial
8. Common operators: \\sum \\prod \\int \\frac{}{} \\sqrt{} \\mathbb{} \\mathcal{} \\text{}
9. If the image contains only text (not math), return: [Non-math content]
10. If the image is too blurry to read, return: [Unreadable math]
"""

_PROMPT_TABLE_COMPLEX = """\
You are an expert in academic document transcription.
Convert the table image into a clean LaTeX tabular environment.

STRICT RULES:
1. Return ONLY LaTeX table code (or Markdown table if simple) — no commentary or preamble.
2. Use standard LaTeX tabular format with booktabs rules where applicable:
   \\begin{tabular}{l c r}
     \\toprule
     Header 1 & Header 2 & Header 3 \\\\
     \\midrule
     Row 1 & Value 1 & Value 2 \\\\
     \\bottomrule
   \\end{tabular}
3. Preserve math symbols in cells inside $...$.
4. Ensure merged cells (multi-column / multi-row) are correctly represented using \\multicolumn or \\multirow if present.
"""

_PROMPT_ALGORITHM = """\
You are an expert in computer science algorithm transcription.
Convert this algorithm / pseudocode box image into clean, structured pseudocode.

STRICT RULES:
1. Return ONLY the code inside a fenced code block with `algorithm` language specifier:
   ```algorithm
   Input: ...
   Output: ...
   1: for i = 1 to N do
   2:     update theta
   ```
2. Maintain exact indentation and line numbering as shown in the image.
3. Preserve mathematical variables using standard notation.
4. Do NOT add explanation before or after the code block.
"""

OCRMode = Literal["image", "figure", "math", "table_complex", "table_simple", "algorithm", "text"]

_PROMPT_MAP: dict[str, str] = {
    "image":         _PROMPT_IMAGE,
    "figure":        _PROMPT_FIGURE,
    "math":          _PROMPT_MATH,
    "table_complex": _PROMPT_TABLE_COMPLEX,
    "table_simple":  _PROMPT_TABLE_COMPLEX,
    "algorithm":     _PROMPT_ALGORITHM,
    "text":          _PROMPT_MATH,
}


# ─── Helpers ────────────────────────────────────────────────────────────────

def _resize_image_bytes(image_bytes: bytes, max_size: int = OCR_MAX_IMAGE_SIZE) -> bytes:
    """Resize ảnh sao cho cạnh dài nhất ≤ max_size pixel."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size

    if max(w, h) <= max_size:
        return image_bytes

    if w >= h:
        new_w = max_size
        new_h = int(h * max_size / w)
    else:
        new_h = max_size
        new_w = int(w * max_size / h)

    img_resized = img.resize((new_w, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img_resized.save(buf, format="PNG", optimize=True)
    log.debug("Resize ảnh: %dx%d → %dx%d", w, h, new_w, new_h)
    return buf.getvalue()


def _bytes_to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _build_payload(
    image_b64: str,
    mode: OCRMode,
) -> dict:
    """Xây dựng request payload cho Ollama /api/generate."""
    prompt = _PROMPT_MAP.get(mode, _PROMPT_IMAGE)
    return {
        "model":   QWEN2_VL_MODEL,
        "prompt":  prompt,
        "images":  [image_b64],
        "stream":  False,
        "options": OLLAMA_OPTIONS,
    }


# ─── Main API call ──────────────────────────────────────────────────────────

def call_qwen2_vl(
    image_bytes: bytes,
    mode: OCRMode = "image",
) -> str:
    """
    Gọi Ollama Qwen2-VL với ảnh PNG bytes và trả về chuỗi markdown/LaTeX.

    Args:
        image_bytes: PNG bytes của vùng ảnh cần OCR.
        mode: Chế độ OCR ("math", "figure", "table_complex", "algorithm", "image").

    Returns:
        Chuỗi markdown / LaTeX. Nếu thất bại sau retries → "[OCR Failed]".
    """
    try:
        resized = _resize_image_bytes(image_bytes)
    except Exception as exc:
        log.warning("Không thể resize ảnh: %s", exc)
        resized = image_bytes

    image_b64 = _bytes_to_base64(resized)
    payload   = _build_payload(image_b64, mode)
    url       = f"{OLLAMA_BASE_URL}/api/generate"

    for attempt in range(1, OLLAMA_MAX_RETRIES + 1):
        try:
            log.debug("Gọi Ollama [%s] lần %d/%d ...", mode, attempt, OLLAMA_MAX_RETRIES)
            t0       = time.perf_counter()
            response = requests.post(
                url,
                json=payload,
                timeout=OLLAMA_TIMEOUT_SEC,
            )
            elapsed  = time.perf_counter() - t0

            if response.status_code == 200:
                data   = response.json()
                result = data.get("response", "").strip()
                log.debug("Ollama phản hồi [%s] trong %.1fs, %d chars", mode, elapsed, len(result))
                return result

            log.warning(
                "Ollama trả về HTTP %d (lần %d): %s",
                response.status_code, attempt, response.text[:200],
            )

        except requests.exceptions.ConnectionError:
            log.error(
                "Không kết nối được Ollama tại %s. "
                "Hãy đảm bảo Ollama đang chạy: 'ollama serve'",
                OLLAMA_BASE_URL,
            )
        except requests.exceptions.Timeout:
            log.warning("Ollama timeout sau %ds (lần %d)", OLLAMA_TIMEOUT_SEC, attempt)
        except Exception as exc:
            log.warning("Lỗi không mong đợi khi gọi Ollama (lần %d): %s", attempt, exc)

        if attempt < OLLAMA_MAX_RETRIES:
            wait = 2 ** attempt
            log.info("Thử lại sau %ds...", wait)
            time.sleep(wait)

    return "[OCR Failed: Không thể kết nối Ollama sau nhiều lần thử]"


def check_ollama_health() -> bool:
    """Kiểm tra Ollama server có đang chạy và model đã được pull chưa."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if r.status_code != 200:
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        if not any(QWEN2_VL_MODEL.split(":")[0] in m for m in models):
            log.warning(
                "Model '%s' chưa được pull. Chạy: ollama pull %s",
                QWEN2_VL_MODEL, QWEN2_VL_MODEL,
            )
            return False
        return True
    except Exception:
        return False
