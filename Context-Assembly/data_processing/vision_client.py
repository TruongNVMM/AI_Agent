"""
vision_client.py — Client gọi Ollama API cho Qwen2-VL 7B.

Chiến lược chống OOM trên RTX 2080 Ti (11 GB VRAM):
──────────────────────────────────────────────────────
1. Resize ảnh về ≤ OCR_MAX_IMAGE_SIZE px trước khi gửi.
   Qwen2-VL tính VRAM theo số patch 28×28: ảnh 896×896 ≈ 1024 patch.
   Gửi ảnh 1920×1080 sẽ cần ~4000 patch → dễ OOM.

2. Chỉ gửi 1 request tại một thời điểm (OCR_CONCURRENT_REQUESTS=1).
   Ollama giữ activation VRAM trong khi xử lý; 2 request song song
   có thể nhân đôi peak VRAM lên ~9 GB → vượt 11 GB khi kể OS overhead.

3. num_ctx=2048 thay vì 4096 mặc định → tiết kiệm ~0.5 GB KV cache.

4. Dùng OLLAMA_FLASH_ATTENTION=1 (env var) → giảm KV cache thêm 40%.
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
    OLLAMA_BASE_URL,
    OLLAMA_MAX_RETRIES,
    OLLAMA_OPTIONS,
    OLLAMA_TIMEOUT_SEC,
    OCR_MAX_IMAGE_SIZE,
    QWEN2_VL_MODEL,
)

log = logging.getLogger(__name__)

# ─── Prompts ────────────────────────────────────────────────────────────────

_PROMPT_IMAGE = """\
You are an expert at analyzing academic figures and charts.
Examine this image carefully and provide a concise markdown description.

Rules:
- If it is a chart/graph: describe axes, key trends, and main findings in 2-4 sentences.
- If it is a diagram/architecture: describe the components and data flow briefly.
- If it is a table rendered as image: transcribe it as a markdown table.
- If it is a photo or decorative image: write one descriptive sentence.
- Do NOT add preamble like "This image shows..." — start directly with the content.
- Wrap your response in a markdown blockquote: > [Figure] ...
"""

_PROMPT_MATH = """\
You are an expert LaTeX typesetter.
Convert the mathematical formula or equation in this image to LaTeX.

Rules:
- Return ONLY the LaTeX expression — no explanation, no prose.
- Wrap display equations in $$...$$
- Wrap inline formulas in $...$
- If there are multiple equations, separate them with a blank line.
- If the image is not a formula, return: [Non-math content]
"""


# ─── Helpers ────────────────────────────────────────────────────────────────

def _resize_image_bytes(image_bytes: bytes, max_size: int = OCR_MAX_IMAGE_SIZE) -> bytes:
    """
    Resize ảnh sao cho cạnh dài nhất ≤ max_size pixel.
    Giữ nguyên aspect ratio. Trả về PNG bytes.

    Đây là bước quan trọng nhất để kiểm soát VRAM:
    - Ảnh 2000×1000 px → 60% VRAM hơn ảnh 896×448 px cùng nội dung.
    - Qwen2-VL vẫn nhận ra nội dung tốt ở 768-896 px.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size

    if max(w, h) <= max_size:
        # Không cần resize, trả về bytes gốc (tránh re-encode lãng phí)
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
    mode: Literal["image", "math"],
) -> dict:
    """Xây dựng request payload cho Ollama /api/generate."""
    prompt = _PROMPT_IMAGE if mode == "image" else _PROMPT_MATH
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
    mode: Literal["image", "math"],
) -> str:
    """
    Gọi Ollama Qwen2-VL với ảnh PNG bytes và trả về chuỗi markdown.

    Args:
        image_bytes: PNG bytes của vùng ảnh cần OCR.
        mode: "image" (mô tả đồ thị/hình ảnh) hoặc "math" (chuyển sang LaTeX).

    Returns:
        Chuỗi markdown / LaTeX. Nếu thất bại sau retries → "[OCR Failed]".
    """
    # Resize trước khi encode để tránh gửi ảnh quá lớn lên Ollama
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
                log.debug("Ollama phản hồi trong %.1fs, %d chars", elapsed, len(result))
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
            wait = 2 ** attempt  # Exponential backoff: 2s, 4s
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
