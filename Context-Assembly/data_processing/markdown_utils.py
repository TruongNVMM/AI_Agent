"""
markdown_utils.py — Helper định dạng Markdown an toàn.
"""

from __future__ import annotations

from urllib.parse import quote


def escape_markdown_alt(text: str) -> str:
    """Escape các ký tự có thể phá phần alt text của image/link."""
    return (
        text.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def markdown_image(alt: str, rel_path: str) -> str:
    """
    Tạo image tag Markdown với path đã URL-encode.

    Tên PDF thường có dấu cách hoặc ngoặc, ví dụ:
    ``Generative-Adversarial-Nets (GAN)_p1_b0_image.png``.
    Nếu đưa thẳng vào ``![...](...)``, dấu ``)`` trong tên file sẽ đóng link
    sớm và làm hỏng cú pháp Markdown.
    """
    safe_path = quote(rel_path.replace("\\", "/"), safe="/")
    safe_alt = escape_markdown_alt(alt)
    return f"![{safe_alt}]({safe_path})"


def markdown_image_for_block(
    rel_path: str,
    page_num: int,
    block_id: int,
) -> str:
    """Tạo image tag thống nhất cho một block ảnh trong PDF."""
    return markdown_image(f"Image p{page_num} #{block_id}", rel_path)
