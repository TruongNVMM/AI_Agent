#!/usr/bin/env python3
"""
Face Clustering with DBSCAN
============================
Phân nhóm người trong video dựa trên khuôn mặt sử dụng DBSCAN.

Pipeline:
  1. Load model best_head.pt (YOLO) để detect đầu người.
  2. Với mỗi vùng đầu được detect, dùng InsightFace trích xuất face embedding (512-D).
  3. Sau khi xử lý toàn bộ video (hoặc sample frames), áp dụng DBSCAN để phân cụm
     các embedding thành các nhóm người.
  4. Ghi video output với bounding box & nhãn cụm được vẽ trực tiếp lên từng frame.

Đầu vào : data/input_video/input5.mp4
Đầu ra  : data/input_video/input5_clustered.mp4
"""

import os
import sys
import time
import logging
import collections
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import cv2
import numpy as np
import torch
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import normalize

# ── Try importing optional heavy deps ──────────────────────────────────────────
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("ultralytics not installed → pip install ultralytics")

try:
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
except ImportError:
    INSIGHTFACE_AVAILABLE = False
    print("insightface not installed → pip install insightface onnxruntime-gpu")

# ── Paths ───────────────────────────────────────────────────────────────────────
ROOT_DIR    = Path(__file__).resolve().parent.parent          # PTZ/
MODEL_PATH  = ROOT_DIR / "models" / "best_head.pt"
INPUT_VIDEO = ROOT_DIR / "data" / "input_video" / "input5.mp4"
OUTPUT_DIR  = ROOT_DIR / "data" / "input_video"
OUTPUT_VIDEO = OUTPUT_DIR / "input5_clustered.mp4"

# ── Logging ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("FaceClustering")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  1. HEAD DETECTOR  (best_head.pt)                                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class HeadDetectorBest:
    """
    Load và sử dụng best_head.pt để detect đầu người trong frame.
    """

    def __init__(
        self,
        model_path: str | Path = MODEL_PATH,
        device: str = "cuda:0",
        conf_threshold: float = 0.45,
        iou_threshold: float  = 0.45,
    ):
        """
        Load model best_head.pt từ thư mục models/.

        Args:
            model_path     : Đường dẫn tới best_head.pt
            device         : 'cuda:0' hoặc 'cpu'
            conf_threshold : Ngưỡng confidence
            iou_threshold  : Ngưỡng IoU cho NMS
        """
        if not YOLO_AVAILABLE:
            raise ImportError("ultralytics chưa cài đặt. pip install ultralytics")

        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Không tìm thấy model: {model_path}")

        self.conf_threshold = conf_threshold
        self.iou_threshold  = iou_threshold

        # Kiểm tra GPU
        if device.startswith("cuda") and not torch.cuda.is_available():
            logger.warning("CUDA không khả dụng → chuyển sang CPU")
            device = "cpu"
        self.device = device

        logger.info(f"Đang load model: {model_path}")
        self.model = YOLO(str(model_path))
        self.model.to(self.device)
        logger.info(f"Model best_head.pt đã sẵn sàng trên {self.device}")

        # Warm-up
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        self._run_inference(dummy)
        logger.info("Warm-up hoàn tất")

    def _run_inference(self, frame: np.ndarray) -> list:
        results = self.model(
            frame,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            verbose=False,
            half=(self.device != "cpu"),
        )
        return results

    def detect(self, frame: np.ndarray) -> List[Dict]:
        """
        Detect đầu người trong frame.

        Returns:
            List[Dict] mỗi phần tử có:
                'bbox'       : [x1, y1, x2, y2] (float)
                'confidence' : float
        """
        if frame is None or frame.size == 0:
            return []

        try:
            results = self._run_inference(frame)
            detections = []

            if results and results[0].boxes is not None:
                for box in results[0].boxes:
                    xyxy = box.xyxy[0].cpu().numpy().tolist()
                    conf = float(box.conf[0])
                    detections.append({"bbox": xyxy, "confidence": conf})

            return detections
        except Exception as exc:
            logger.error(f"Lỗi detect: {exc}")
            return []


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  2. FACE EMBEDDING EXTRACTOR  (InsightFace)                                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class FaceEmbeddingExtractor:
    """
    Trích xuất face embedding 512-D từ vùng ảnh khuôn mặt / đầu người.
    """

    def __init__(
        self,
        model_name: str = "buffalo_l",
        det_size: Tuple[int, int] = (320, 320),
        ctx_id: int = 0,
    ):
        """
        Args:
            model_name : Tên InsightFace model pack
            det_size   : Độ phân giải detect khuôn mặt nội bộ của InsightFace
            ctx_id     : GPU ID (0 → GPU 0, -1 → CPU)
        """
        if not INSIGHTFACE_AVAILABLE:
            raise ImportError("insightface chưa cài đặt. pip install insightface onnxruntime-gpu")

        if ctx_id >= 0 and not torch.cuda.is_available():
            logger.warning("CUDA không khả dụng → InsightFace chạy trên CPU")
            ctx_id = -1

        logger.info(f"Đang load InsightFace ({model_name})…")
        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if ctx_id >= 0
            else ["CPUExecutionProvider"]
        )
        self.app = FaceAnalysis(
            name=model_name,
            allowed_modules=["detection", "recognition"],
            providers=providers,
        )
        self.app.prepare(ctx_id=ctx_id, det_size=det_size)
        logger.info("InsightFace sẵn sàng")

    def extract(self, frame: np.ndarray, bbox: List[float]) -> Optional[np.ndarray]:
        """
        Trích xuất embedding từ vùng bbox trong frame.

        Args:
            frame : Ảnh BGR toàn frame
            bbox  : [x1, y1, x2, y2]

        Returns:
            np.ndarray (512,) hoặc None nếu không detect được khuôn mặt
        """
        x1, y1, x2, y2 = map(int, bbox)
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return None

        roi = frame[y1:y2, x1:x2]

        # Thêm padding để InsightFace dễ detect hơn
        pad = int(max(roi.shape[:2]) * 0.15)
        roi_padded = cv2.copyMakeBorder(
            roi, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(114, 114, 114)
        )

        try:
            faces = self.app.get(roi_padded)
            if faces:
                # Chọn face có score cao nhất
                best = max(faces, key=lambda f: float(f.det_score))
                emb = best.embedding  # (512,)
                return emb / (np.linalg.norm(emb) + 1e-8)  # L2-normalize
        except Exception as exc:
            logger.debug(f"Lỗi extract embedding: {exc}")

        return None


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  3. DBSCAN CLUSTERER                                                        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class FaceDBSCANClusterer:
    """
    Phân cụm face embedding bằng DBSCAN.
    """

    def __init__(self, eps: float = 0.5, min_samples: int = 3):
        """
        Args:
            eps        : Bán kính neighbourhood trong không gian cosine distance.
                         Giá trị nhỏ hơn → cụm nhỏ hơn / chặt chẽ hơn.
            min_samples: Số điểm tối thiểu để tạo thành core point.
        """
        self.eps = eps
        self.min_samples = min_samples
        self.labels_: Optional[np.ndarray] = None
        self.embeddings_: Optional[np.ndarray] = None

    def fit(self, embeddings: np.ndarray) -> np.ndarray:
        """
        Phân cụm tập embedding.

        Args:
            embeddings : (N, 512) – mỗi hàng là một L2-normalized embedding

        Returns:
            labels (N,) – nhãn cụm; -1 là noise
        """
        if len(embeddings) == 0:
            return np.array([], dtype=int)

        # L2-normalize lần nữa cho chắc
        emb_norm = normalize(embeddings, norm="l2")

        # Cosine distance = 1 - cosine_similarity
        # DBSCAN với metric precomputed
        db = DBSCAN(
            eps=self.eps,
            min_samples=self.min_samples,
            metric="cosine",
            n_jobs=-1,
        )
        self.labels_ = db.fit_predict(emb_norm)
        self.embeddings_ = emb_norm

        n_clusters = len(set(self.labels_)) - (1 if -1 in self.labels_ else 0)
        n_noise    = int(np.sum(self.labels_ == -1))
        logger.info(
            f"DBSCAN → {n_clusters} cụm, {n_noise}/{len(embeddings)} điểm nhiễu"
        )
        return self.labels_

    def cluster_centers(self) -> Dict[int, np.ndarray]:
        """Trả về centroid (trung bình) của mỗi cụm."""
        if self.labels_ is None or self.embeddings_ is None:
            return {}
        centers = {}
        for label in set(self.labels_):
            if label == -1:
                continue
            mask = self.labels_ == label
            centers[label] = self.embeddings_[mask].mean(axis=0)
        return centers


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  4. VIDEO PROCESSOR                                                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Màu sắc cho từng cụm (BGR) – tối đa 20 cụm nổi bật
CLUSTER_COLORS = [
    (0, 204, 255),   # vàng-cyan
    (0, 102, 255),   # cam
    (51, 255, 51),   # xanh lá
    (255, 51, 51),   # xanh dương
    (255, 51, 255),  # hồng
    (0, 255, 204),   # xanh ngọc
    (204, 51, 255),  # tím
    (255, 255, 0),   # cyan
    (0, 153, 76),    # xanh lá đậm
    (255, 128, 0),   # xanh dương nhạt
    (128, 0, 255),   # tím nhạt
    (0, 255, 128),   # xanh ngọc nhạt
    (255, 0, 128),   # hồng nhạt
    (128, 255, 0),   # vàng xanh
    (0, 128, 255),   # cam nhạt
    (255, 204, 0),   # xanh dương đậm
    (102, 255, 178), # mint
    (178, 102, 255), # lavender
    (255, 178, 102), # peach
    (102, 178, 255), # sky
]
NOISE_COLOR = (120, 120, 120)  # xám – noise


def _get_color(label: int) -> Tuple[int, int, int]:
    if label == -1:
        return NOISE_COLOR
    return CLUSTER_COLORS[label % len(CLUSTER_COLORS)]


def draw_cluster_bbox(
    frame: np.ndarray,
    bbox: List[float],
    label: int,
    confidence: float,
    track_id: Optional[int] = None,
) -> None:
    """Vẽ bounding box + nhãn cụm lên frame (in-place)."""
    color = _get_color(label)
    x1, y1, x2, y2 = map(int, bbox)

    # Vẽ khung
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    # Nhãn
    cluster_text = f"Person {label}" if label != -1 else "Noise"
    text = f"{cluster_text} | {confidence:.2f}"
    if track_id is not None:
        text = f"[{track_id}] " + text

    font_scale  = 0.55
    thickness   = 1
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)

    # Nền nhãn
    cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 6, y1), color, -1)

    # Chữ
    cv2.putText(
        frame, text,
        (x1 + 3, y1 - 4),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (0, 0, 0),
        thickness,
        cv2.LINE_AA,
    )


def draw_legend(frame: np.ndarray, cluster_labels: List[int]) -> None:
    """Vẽ legend hiển thị số lượng cụm lên góc trên phải."""
    unique_labels = sorted(set(cluster_labels))
    n_clusters    = sum(1 for l in unique_labels if l != -1)

    lines = [f"Clusters: {n_clusters}"]
    for lbl in unique_labels:
        color = _get_color(lbl)
        name  = f"  Person {lbl}" if lbl != -1 else "  Noise"
        lines.append((name, color))

    h, w = frame.shape[:2]
    x_start = w - 180
    y_start = 20
    line_h  = 22

    for i, item in enumerate(lines):
        y = y_start + i * line_h
        if isinstance(item, str):
            cv2.putText(frame, item, (x_start, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        else:
            name, color = item
            cv2.rectangle(frame, (x_start, y - 12), (x_start + 12, y), color, -1)
            cv2.putText(frame, name, (x_start + 14, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  5. MAIN PIPELINE                                                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class FaceClusteringPipeline:
    """
    Pipeline toàn bộ:
      Pass 1 – Đọc video, detect đầu, trích embedding (sample mỗi sample_step frame)
      DBSCAN  – Phân cụm trên toàn bộ embedding đã thu thập
      Pass 2  – Ghi video output với bounding box & nhãn cụm
    """

    def __init__(
        self,
        head_detector      : HeadDetectorBest,
        embedding_extractor: FaceEmbeddingExtractor,
        clusterer          : FaceDBSCANClusterer,
        sample_step        : int   = 5,   # lấy 1 frame mỗi 5 frame cho pass 1
        assignment_topk    : int   = 1,   # khi assign vào pass 2 dùng nearest centroid
    ):
        self.detector   = head_detector
        self.extractor  = embedding_extractor
        self.clusterer  = clusterer
        self.sample_step = sample_step
        self.assignment_topk = assignment_topk

        # Sẽ được điền sau DBSCAN
        self._cluster_centers: Dict[int, np.ndarray] = {}

    # ── Pass 1 ────────────────────────────────────────────────────────────────

    def _pass1_collect_embeddings(
        self,
        cap: cv2.VideoCapture,
    ) -> Tuple[List[np.ndarray], List[int]]:
        """
        Duyệt qua video (sample_step frames), detect đầu & trích embedding.

        Returns:
            all_embeddings : List of (512,) vectors
            frame_indices  : Frame index tương ứng
        """
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        logger.info(
            f"Pass 1 – Thu thập embeddings (sample mỗi {self.sample_step} frame "
            f"trong {total_frames} frames)"
        )

        all_embeddings: List[np.ndarray] = []
        frame_indices:  List[int]        = []

        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % self.sample_step == 0:
                detections = self.detector.detect(frame)

                for det in detections:
                    emb = self.extractor.extract(frame, det["bbox"])
                    if emb is not None:
                        all_embeddings.append(emb)
                        frame_indices.append(frame_idx)

            frame_idx += 1

            if frame_idx % 200 == 0:
                logger.info(f"  … frame {frame_idx}/{total_frames} | "
                            f"embeddings: {len(all_embeddings)}")

        logger.info(f"Pass 1 hoàn tất: {len(all_embeddings)} embeddings từ {total_frames} frames")
        return all_embeddings, frame_indices

    # ── Nearest-centroid assignment ───────────────────────────────────────────

    def _assign_label(self, embedding: np.ndarray) -> int:
        """
        Gán nhãn cụm cho một embedding mới dựa trên centroid gần nhất.
        Nếu khoảng cách > ngưỡng → noise (-1).
        """
        if not self._cluster_centers:
            return -1

        emb = embedding / (np.linalg.norm(embedding) + 1e-8)
        best_label = -1
        best_sim   = -1.0

        for lbl, center in self._cluster_centers.items():
            sim = float(np.dot(emb, center))
            if sim > best_sim:
                best_sim   = sim
                best_label = lbl

        # cosine similarity → distance = 1 - sim
        # Ngưỡng tương đương eps của DBSCAN
        threshold = 1.0 - self.clusterer.eps
        if best_sim < threshold:
            return -1
        return best_label

    # ── Pass 2 ────────────────────────────────────────────────────────────────

    def _pass2_render(
        self,
        cap: cv2.VideoCapture,
        writer: cv2.VideoWriter,
    ) -> None:
        """
        Duyệt video lần 2, detect + assign label + vẽ lên frame + ghi output.
        """
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        logger.info(f"Pass 2 – Render output ({total_frames} frames)…")

        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        frame_idx = 0

        # Lịch sử nhãn cho mỗi bbox để giảm nhấp nháy (temporal smoothing)
        # Key: track pseudo-ID dựa trên centroid vị trí
        recent_labels: collections.deque = collections.deque(maxlen=30)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            detections = self.detector.detect(frame)
            frame_labels = []

            for det in detections:
                bbox = det["bbox"]
                conf = det["confidence"]

                emb   = self.extractor.extract(frame, bbox)
                label = self._assign_label(emb) if emb is not None else -1

                frame_labels.append(label)
                draw_cluster_bbox(frame, bbox, label, conf)

            # Tổng hợp nhãn của frame này để vẽ legend
            all_visible = frame_labels if frame_labels else [-1]
            draw_legend(frame, all_visible)

            # Overlay thông tin frame
            cv2.putText(
                frame,
                f"Frame: {frame_idx}  Heads detected: {len(detections)}",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (200, 200, 200),
                1,
                cv2.LINE_AA,
            )

            writer.write(frame)
            frame_idx += 1

            if frame_idx % 100 == 0:
                logger.info(f"  … {frame_idx}/{total_frames} frames đã ghi")

        logger.info("Pass 2 hoàn tất")

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, input_path: str | Path, output_path: str | Path) -> None:
        """
        Chạy toàn bộ pipeline.

        Args:
            input_path  : Đường dẫn video đầu vào
            output_path : Đường dẫn video đầu ra
        """
        input_path  = Path(input_path)
        output_path = Path(output_path)

        if not input_path.exists():
            raise FileNotFoundError(f"Không tìm thấy video đầu vào: {input_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(input_path))
        if not cap.isOpened():
            raise RuntimeError(f"Không mở được video: {input_path}")

        fps    = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        logger.info(f"Video: {width}×{height} @ {fps:.1f}fps | {input_path.name}")

        # ── Pass 1: thu thập embeddings ────────────────────────────────────────
        t0 = time.time()
        all_embeddings, _ = self._pass1_collect_embeddings(cap)

        if len(all_embeddings) == 0:
            logger.warning("Không trích được embedding nào. Kiểm tra lại video / model.")
            cap.release()
            return

        # ── DBSCAN clustering ──────────────────────────────────────────────────
        logger.info("Đang phân cụm DBSCAN…")
        emb_array = np.stack(all_embeddings, axis=0)  # (N, 512)
        labels    = self.clusterer.fit(emb_array)
        self._cluster_centers = self.clusterer.cluster_centers()

        t_cluster = time.time() - t0
        logger.info(f"DBSCAN hoàn tất trong {t_cluster:.1f}s")

        # ── Pass 2: render video ───────────────────────────────────────────────
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

        if not writer.isOpened():
            cap.release()
            raise RuntimeError(f"Không tạo được VideoWriter: {output_path}")

        self._pass2_render(cap, writer)

        cap.release()
        writer.release()

        total_time = time.time() - t0
        file_size  = output_path.stat().st_size / 1024 / 1024
        logger.info(
            f"\n{'='*60}\n"
            f"   Hoàn tất!\n"
            f"   Thời gian tổng: {total_time:.1f}s\n"
            f"   Output        : {output_path}  ({file_size:.1f} MB)\n"
            f"{'='*60}"
        )


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  6. ENTRY POINT                                                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Phân nhóm người trong video dựa trên khuôn mặt bằng DBSCAN"
    )
    parser.add_argument(
        "--input", type=str, default=str(INPUT_VIDEO),
        help="Đường dẫn video đầu vào"
    )
    parser.add_argument(
        "--output", type=str, default=str(OUTPUT_VIDEO),
        help="Đường dẫn video đầu ra"
    )
    parser.add_argument(
        "--model", type=str, default=str(MODEL_PATH),
        help="Đường dẫn model best_head.pt"
    )
    parser.add_argument(
        "--device", type=str, default="cuda:0",
        help="Device: cuda:0 hoặc cpu"
    )
    parser.add_argument(
        "--conf", type=float, default=0.45,
        help="Confidence threshold cho head detector"
    )
    parser.add_argument(
        "--eps", type=float, default=0.45,
        help="DBSCAN eps (cosine distance). Nhỏ hơn = cụm chặt hơn"
    )
    parser.add_argument(
        "--min-samples", type=int, default=3,
        help="DBSCAN min_samples"
    )
    parser.add_argument(
        "--sample-step", type=int, default=5,
        help="Lấy 1 frame mỗi N frame khi thu thập embeddings (Pass 1)"
    )
    parser.add_argument(
        "--face-model", type=str, default="buffalo_l",
        help="InsightFace model name: buffalo_l | buffalo_s | antelopev2"
    )

    args = parser.parse_args()

    # ── Khởi tạo các thành phần ────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  FACE CLUSTERING WITH DBSCAN")
    logger.info("=" * 60)

    head_detector = HeadDetectorBest(
        model_path=args.model,
        device=args.device,
        conf_threshold=args.conf,
    )

    face_extractor = FaceEmbeddingExtractor(
        model_name=args.face_model,
        det_size=(320, 320),
        ctx_id=0 if args.device.startswith("cuda") else -1,
    )

    clusterer = FaceDBSCANClusterer(
        eps=args.eps,
        min_samples=args.min_samples,
    )

    pipeline = FaceClusteringPipeline(
        head_detector=head_detector,
        embedding_extractor=face_extractor,
        clusterer=clusterer,
        sample_step=args.sample_step,
    )

    # ── Chạy pipeline ─────────────────────────────────────────────────────────
    pipeline.run(args.input, args.output)


if __name__ == "__main__":
    main()
