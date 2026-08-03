"""
GPU Memory Manager — Quản lý VRAM an toàn cho RTX 2080 Ti
Cung cấp: monitor, clear cache, guard decorator, context manager
"""

import gc
import time
import logging
from contextlib import contextmanager
from typing import Optional

import torch

from config import MAX_VRAM_GB, GPU_ID, VRAM_CLEAR_DELAY

logger = logging.getLogger(__name__)


def get_vram_stats() -> dict:
    """Trả về thống kê VRAM hiện tại (GB)."""
    if not torch.cuda.is_available():
        return {"total": 0, "allocated": 0, "reserved": 0, "free": 0}

    total     = torch.cuda.get_device_properties(GPU_ID).total_memory / 1e9
    allocated = torch.cuda.memory_allocated(GPU_ID) / 1e9
    reserved  = torch.cuda.memory_reserved(GPU_ID) / 1e9
    free      = total - reserved

    return {
        "total":     round(total, 2),
        "allocated": round(allocated, 2),
        "reserved":  round(reserved, 2),
        "free":      round(free, 2),
    }


def log_vram(prefix: str = "") -> None:
    """Log trạng thái VRAM hiện tại."""
    stats = get_vram_stats()
    logger.info(
        f"{prefix}VRAM — "
        f"Allocated: {stats['allocated']:.2f}GB | "
        f"Reserved: {stats['reserved']:.2f}GB | "
        f"Free: {stats['free']:.2f}GB / {stats['total']:.2f}GB"
    )


def clear_vram(delay: float = VRAM_CLEAR_DELAY) -> None:
    """
    Giải phóng VRAM: Python GC + CUDA cache.
    Dùng giữa các chunk hoặc giữa các file lớn.
    """
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize(GPU_ID)
    time.sleep(delay)
    log_vram(prefix="[After clear] ")


def check_vram_safe(required_gb: float = 3.0) -> bool:
    """
    Kiểm tra xem có đủ VRAM trống để xử lý không.
    Nếu không đủ → tự động clear trước.
    """
    stats = get_vram_stats()
    if stats["free"] < required_gb:
        logger.warning(
            f"VRAM không đủ ({stats['free']:.2f}GB < {required_gb}GB yêu cầu). "
            f"Đang clear cache..."
        )
        clear_vram(delay=2.0)
        stats = get_vram_stats()

    ok = stats["free"] >= required_gb
    if not ok:
        logger.error(
            f"VRAM vẫn không đủ sau khi clear: {stats['free']:.2f}GB. "
            f"Hãy đóng ứng dụng GPU khác."
        )
    return ok


@contextmanager
def vram_guard(label: str = "", required_gb: float = 3.0):
    """
    Context manager: log VRAM trước/sau, clear cache sau khi xong.

    Cách dùng:
        with vram_guard("Xử lý chunk 1/5", required_gb=4.0):
            ... xử lý ...
    """
    log_vram(prefix=f"[Before {label}] ")
    check_vram_safe(required_gb)
    try:
        yield
    finally:
        log_vram(prefix=f"[After  {label}] ")
        clear_vram()


def set_gpu_memory_fraction(fraction: float = 0.9) -> None:
    """
    Giới hạn tỷ lệ VRAM PyTorch được phép dùng.
    Fraction 0.9 = tối đa 90% tổng VRAM (~9.9 GB trên 2080 Ti).
    """
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(fraction, GPU_ID)
        logger.info(
            f"Giới hạn VRAM: {fraction*100:.0f}% "
            f"(~{get_vram_stats()['total'] * fraction:.1f} GB)"
        )


def get_device() -> str:
    """Trả về device string phù hợp."""
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(GPU_ID)
        logger.info(f"GPU phát hiện: {name}")
        return f"cuda:{GPU_ID}"
    logger.warning("Không tìm thấy GPU, dùng CPU (chậm hơn nhiều).")
    return "cpu"
