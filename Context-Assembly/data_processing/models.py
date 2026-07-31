"""
models.py — Dataclasses trung tâm cho toàn bộ pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class BlockType(str, Enum):
    """Loại của từng vùng nội dung trong một trang PDF."""
    TEXT        = "text"         # Đoạn văn thuần — xử lý trên CPU
    TABLE       = "table"        # Bảng biểu — CPU detect + render Markdown
    IMAGE       = "image"        # Hình ảnh / đồ thị — gửi Qwen2-VL
    MATH        = "math"         # Công thức toán — gửi Qwen2-VL
    UNKNOWN     = "unknown"      # Không xác định, bỏ qua


@dataclass
class DocumentBlock:
    """
    Đơn vị nhỏ nhất trong pipeline: một vùng nội dung trên trang PDF.

    block_id được gán SAU KHI đã sắp xếp thứ tự đọc → bất biến trong suốt pipeline.
    Đây là chìa khoá để reassembly luôn đúng thứ tự.
    """
    block_id:       int                     # Chỉ số thứ tự (0, 1, 2, …) — BẤT BIẾN
    page_num:       int                     # Số trang PDF (1-indexed)
    bbox:           tuple[float, ...]       # (x0, y0, x1, y1) tính theo points

    block_type:     BlockType = BlockType.UNKNOWN

    # Nội dung thô từ PDF (cho TEXT/TABLE):
    raw_content:    str = ""

    # Ảnh crop (bytes PNG) cho IMAGE/MATH — được set bởi layout_detector:
    crop_bytes:     bytes | None = None

    # Đường dẫn tương đối đến file ảnh đã lưu (cho Markdown link ![alt](path)):
    image_rel_path: str | None = None

    # Kết quả cuối cùng sau toàn bộ xử lý — được set bởi text_extractor / ocr_worker:
    markdown_result: str = ""

    # True nếu block này đã xử lý xong (dùng để theo dõi progress):
    is_done:        bool = False

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def needs_ocr(self) -> bool:
        return self.block_type in (BlockType.IMAGE, BlockType.MATH)


@dataclass
class PageResult:
    """Kết quả sau khi xử lý xong một trang PDF."""
    page_num:    int
    doc_name:    str
    layout:      str                     # "1-column" | "2-column"
    blocks:      list[DocumentBlock] = field(default_factory=list)

    @property
    def markdown(self) -> str:
        """
        Ghép nối tất cả blocks theo đúng block_id.
        Đây là điểm then chốt bảo toàn Reading Order.
        """
        parts = []
        for block in sorted(self.blocks, key=lambda b: b.block_id):
            content = block.markdown_result.strip()
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    @property
    def has_ocr_blocks(self) -> bool:
        return any(b.needs_ocr for b in self.blocks)


@dataclass
class DocumentResult:
    """Kết quả sau khi xử lý xong toàn bộ một file PDF."""
    doc_name:    str
    source_path: Path
    pages:       list[PageResult] = field(default_factory=list)

    # Thống kê:
    total_blocks:       int = 0
    text_blocks:        int = 0
    table_blocks:       int = 0
    image_blocks:       int = 0
    math_blocks:        int = 0
    ocr_failed_blocks:  int = 0

    @property
    def markdown(self) -> str:
        """Ghép toàn bộ trang → markdown hoàn chỉnh của tài liệu."""
        page_mds = []
        for page in sorted(self.pages, key=lambda p: p.page_num):
            page_md = page.markdown
            if page_md.strip():
                page_mds.append(f"<!-- page {page.page_num} -->\n\n{page_md}")
        return "\n\n---\n\n".join(page_mds)

    def summary(self) -> dict:
        return {
            "doc_name":         self.doc_name,
            "total_pages":      len(self.pages),
            "total_blocks":     self.total_blocks,
            "text_blocks":      self.text_blocks,
            "table_blocks":     self.table_blocks,
            "image_blocks":     self.image_blocks,
            "math_blocks":      self.math_blocks,
            "ocr_failed":       self.ocr_failed_blocks,
        }
