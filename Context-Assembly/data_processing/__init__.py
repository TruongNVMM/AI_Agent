"""
data_processing — Hybrid PDF -> Markdown Pipeline

Modules:
    config          : Cau hinh tap trung (Ollama, DPI, VRAM, paths)
    models          : Dataclasses (DocumentBlock, PageResult, DocumentResult)
    layout_detector : Phan loai layout, phan doan block, sap xep Reading Order
    text_extractor  : CPU processor: lam sach text, post-process bang Markdown
    vision_client   : Ollama Qwen2-VL HTTP client (resize anh, retry)
    ocr_worker      : Worker OCR voi Semaphore chong OOM
    page_processor  : Dieu phoi xu ly 1 trang
    postprocessor   : Sua hyphenation, loc header/footer, detect References
    pipeline        : Dieu phoi toan bo pipeline
    run             : CLI entry point
"""
