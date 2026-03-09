#!/usr/bin/env python3
"""Open webcam and count visible faces in real time."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import statistics
import sys
import time
from urllib.request import urlretrieve

import cv2

try:
    import mediapipe as mp
except ImportError:
    mp = None


MODEL_PROTO_URL = (
    "https://raw.githubusercontent.com/opencv/opencv/master/"
    "samples/dnn/face_detector/deploy.prototxt"
)
MODEL_WEIGHT_URL = (
    "https://raw.githubusercontent.com/opencv/opencv_3rdparty/"
    "dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel"
)
YUNET_MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
HAND_LANDMARKER_TASK_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)


def parse_args() -> argparse.Namespace:
    default_model_dir = Path(__file__).resolve().parent / "models"
    parser = argparse.ArgumentParser(
        description="Open webcam and estimate how many faces are in front of camera."
    )
    parser.add_argument(
        "--backend",
        choices=["dnn", "yunet", "haar"],
        default="yunet",
        help="Face detector backend. Recommended: yunet.",
    )
    parser.add_argument("--camera", type=int, default=0, help="Webcam index, default: 0")
    parser.add_argument("--width", type=int, default=1280, help="Capture width")
    parser.add_argument("--height", type=int, default=720, help="Capture height")
    parser.add_argument(
        "--detect-width",
        type=int,
        default=0,
        help="Resize frame width before detection. 0 means full frame (more accurate).",
    )
    parser.add_argument(
        "--conf-thres",
        type=float,
        default=0.45,
        help="Detector confidence threshold. Increase to reduce false positives.",
    )
    parser.add_argument(
        "--nms-thres",
        type=float,
        default=0.3,
        help="NMS threshold for overlapped boxes.",
    )
    parser.add_argument(
        "--min-face",
        type=int,
        default=25,
        help="Ignore tiny face boxes smaller than this value.",
    )
    parser.add_argument(
        "--smooth",
        type=int,
        default=5,
        help="Median window size for stable face count display.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=default_model_dir,
        help="Directory to store face detector model files.",
    )
    parser.add_argument(
        "--track-iou",
        type=float,
        default=0.2,
        help="IoU threshold for matching detections to existing tracks.",
    )
    parser.add_argument(
        "--track-max-missing",
        type=int,
        default=12,
        help="How many consecutive frames a track can survive without detection.",
    )
    parser.add_argument(
        "--track-min-hits",
        type=int,
        default=2,
        help="Track becomes valid for counting only after this many matched hits.",
    )
    parser.add_argument(
        "--track-max-center-dist",
        type=float,
        default=0.45,
        help="Normalized center distance threshold for track matching.",
    )
    parser.add_argument(
        "--track-max-scale-change",
        type=float,
        default=2.2,
        help="Maximum allowed area scale change when matching tracks.",
    )
    parser.add_argument(
        "--count-max-missing",
        type=int,
        default=2,
        help="Count tracks only if missing frames are <= this threshold.",
    )
    parser.add_argument(
        "--face-min-ar",
        type=float,
        default=0.55,
        help="Minimum face box aspect ratio (w/h).",
    )
    parser.add_argument(
        "--face-max-ar",
        type=float,
        default=1.6,
        help="Maximum face box aspect ratio (w/h).",
    )
    parser.add_argument(
        "--face-min-area-ratio",
        type=float,
        default=0.00025,
        help="Minimum face box area ratio against full frame area.",
    )
    parser.add_argument(
        "--face-max-area-ratio",
        type=float,
        default=0.45,
        help="Maximum face box area ratio against full frame area.",
    )
    parser.add_argument(
        "--enable-gesture",
        action="store_true",
        help="Enable hand gesture digit recognition (requires mediapipe).",
    )
    parser.add_argument(
        "--gesture-max-hands",
        type=int,
        default=2,
        help="Maximum number of hands for gesture recognition.",
    )
    parser.add_argument(
        "--gesture-min-detection-conf",
        type=float,
        default=0.5,
        help="Minimum detection confidence for mediapipe hands.",
    )
    parser.add_argument(
        "--gesture-min-tracking-conf",
        type=float,
        default=0.5,
        help="Minimum tracking confidence for mediapipe hands.",
    )
    parser.add_argument(
        "--gesture-smooth",
        type=int,
        default=3,
        help="Median window size for stable gesture number display.",
    )
    parser.add_argument(
        "--gesture-model-path",
        type=Path,
        default=Path(__file__).resolve().parent / "models" / "hand_landmarker.task",
        help="Path to mediapipe hand landmarker .task model (for tasks backend).",
    )
    parser.add_argument(
        "--collect-data",
        action="store_true",
        help="Collect training samples while running (image + yolo labels).",
    )
    parser.add_argument(
        "--collect-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "datasets" / "face_collect",
        help="Output directory for collected samples.",
    )
    parser.add_argument(
        "--collect-interval",
        type=float,
        default=0.6,
        help="Seconds between automatic sample saves.",
    )
    parser.add_argument(
        "--collect-max-samples",
        type=int,
        default=0,
        help="Maximum auto-collected samples. 0 means unlimited.",
    )
    parser.add_argument(
        "--collect-face-crops",
        action="store_true",
        help="Also save each detected face crop.",
    )
    parser.add_argument(
        "--collect-allow-empty",
        action="store_true",
        help="Allow saving frames without face boxes.",
    )
    parser.add_argument(
        "--stdout-json",
        action="store_true",
        help="Print one JSON object per frame to stdout (JSON Lines).",
    )
    return parser.parse_args()


def ensure_file(path: Path, url: str, min_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size >= min_bytes:
        return

    print(f"Downloading model: {path.name}", file=sys.stderr)
    urlretrieve(url, str(path))
    if path.stat().st_size < min_bytes:
        raise RuntimeError(f"Downloaded file looks invalid: {path}")


def make_dnn_detector(model_dir: Path) -> cv2.dnn_Net:
    proto_path = model_dir / "deploy.prototxt"
    weight_path = model_dir / "res10_300x300_ssd_iter_140000.caffemodel"
    ensure_file(proto_path, MODEL_PROTO_URL, min_bytes=1000)
    ensure_file(weight_path, MODEL_WEIGHT_URL, min_bytes=1_000_000)
    return cv2.dnn.readNetFromCaffe(str(proto_path), str(weight_path))


def make_yunet_detector(model_dir: Path, conf_thres: float, nms_thres: float):
    model_path = model_dir / "face_detection_yunet_2023mar.onnx"
    ensure_file(model_path, YUNET_MODEL_URL, min_bytes=100_000)
    return cv2.FaceDetectorYN_create(
        str(model_path),
        "",
        (320, 320),
        score_threshold=conf_thres,
        nms_threshold=nms_thres,
        top_k=5000,
    )


def make_haar_detector() -> cv2.CascadeClassifier:
    detector = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    if detector.empty():
        raise RuntimeError("Failed to load haarcascade_frontalface_default.xml")
    return detector


def nms_boxes(boxes: list[list[int]], scores: list[float], nms_thres: float) -> list[list[int]]:
    if not boxes:
        return []

    idxs = cv2.dnn.NMSBoxes(boxes, scores, score_threshold=0.0, nms_threshold=nms_thres)
    if len(idxs) == 0:
        return []

    return [boxes[i] for i in idxs.flatten().tolist()]


def detect_faces_dnn(
    detector: cv2.dnn_Net,
    frame,
    conf_thres: float,
    nms_thres: float,
    min_face: int,
) -> list[list[int]]:
    h, w = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(
        frame,
        scalefactor=1.0,
        size=(300, 300),
        mean=(104.0, 177.0, 123.0),
        swapRB=False,
        crop=False,
    )
    detector.setInput(blob)
    out = detector.forward()

    boxes: list[list[int]] = []
    scores: list[float] = []
    for i in range(out.shape[2]):
        conf = float(out[0, 0, i, 2])
        if conf < conf_thres:
            continue

        x1 = max(0, int(out[0, 0, i, 3] * w))
        y1 = max(0, int(out[0, 0, i, 4] * h))
        x2 = min(w - 1, int(out[0, 0, i, 5] * w))
        y2 = min(h - 1, int(out[0, 0, i, 6] * h))
        bw = x2 - x1
        bh = y2 - y1
        if bw < min_face or bh < min_face:
            continue

        boxes.append([x1, y1, bw, bh])
        scores.append(conf)
    return nms_boxes(boxes, scores, nms_thres=nms_thres)


def detect_faces_haar(detector: cv2.CascadeClassifier, frame, min_face: int) -> list[list[int]]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = detector.detectMultiScale(
        gray,
        scaleFactor=1.08,
        minNeighbors=6,
        minSize=(min_face, min_face),
    )
    return [[int(x), int(y), int(w), int(h)] for (x, y, w, h) in faces]


def detect_faces_yunet(detector, frame, min_face: int) -> list[list[int]]:
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(frame)
    if faces is None:
        return []

    boxes: list[list[int]] = []
    for face in faces:
        x, y, bw, bh = (int(v) for v in face[:4])
        x = max(0, x)
        y = max(0, y)
        bw = min(bw, w - x)
        bh = min(bh, h - y)
        if bw < min_face or bh < min_face:
            continue
        boxes.append([x, y, bw, bh])
    return boxes


def box_iou(box1: list[int], box2: list[int]) -> float:
    x1, y1, w1, h1 = box1
    x2, y2, w2, h2 = box2
    xa = max(x1, x2)
    ya = max(y1, y2)
    xb = min(x1 + w1, x2 + w2)
    yb = min(y1 + h1, y2 + h2)
    inter_w = max(0, xb - xa)
    inter_h = max(0, yb - ya)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0

    union = (w1 * h1) + (w2 * h2) - inter
    if union <= 0:
        return 0.0
    return inter / union


@dataclass
class FaceTrack:
    track_id: int
    bbox: list[int]
    hits: int = 1
    age: int = 1
    missing: int = 0
    vx: float = 0.0
    vy: float = 0.0


def box_center(box: list[int]) -> tuple[float, float]:
    x, y, w, h = box
    return x + (w / 2.0), y + (h / 2.0)


def box_area(box: list[int]) -> float:
    _, _, w, h = box
    return float(max(0, w) * max(0, h))


def box_diag(box: list[int]) -> float:
    _, _, w, h = box
    return max(1.0, (w * w + h * h) ** 0.5)


def normalized_center_distance(box1: list[int], box2: list[int]) -> float:
    c1x, c1y = box_center(box1)
    c2x, c2y = box_center(box2)
    dx = c1x - c2x
    dy = c1y - c2y
    dist = (dx * dx + dy * dy) ** 0.5
    norm = max(box_diag(box1), box_diag(box2))
    return dist / norm


def filter_face_boxes(
    boxes: list[list[int]],
    frame_w: int,
    frame_h: int,
    min_ar: float,
    max_ar: float,
    min_area_ratio: float,
    max_area_ratio: float,
) -> list[list[int]]:
    frame_area = max(1.0, float(frame_w * frame_h))
    filtered: list[list[int]] = []
    for x, y, w, h in boxes:
        if w <= 1 or h <= 1:
            continue
        ar = w / float(h)
        area_ratio = (w * h) / frame_area
        if ar < min_ar or ar > max_ar:
            continue
        if area_ratio < min_area_ratio or area_ratio > max_area_ratio:
            continue
        filtered.append([x, y, w, h])
    return filtered


class FaceTracker:
    def __init__(
        self,
        iou_thres: float,
        max_missing: int,
        min_hits: int,
        max_center_dist: float,
        max_scale_change: float,
        count_max_missing: int,
    ) -> None:
        self.iou_thres = iou_thres
        self.max_missing = max_missing
        self.min_hits = min_hits
        self.max_center_dist = max_center_dist
        self.max_scale_change = max(1.01, max_scale_change)
        self.count_max_missing = max(0, count_max_missing)
        self.next_id = 1
        self.tracks: dict[int, FaceTrack] = {}

    def update(self, detections: list[list[int]]) -> list[FaceTrack]:
        track_ids = list(self.tracks.keys())
        candidates: list[tuple[float, int, int]] = []
        for track_id in track_ids:
            track_box = self.tracks[track_id].bbox
            for det_idx, det_box in enumerate(detections):
                iou = box_iou(track_box, det_box)
                center_dist = normalized_center_distance(track_box, det_box)
                area_ratio = box_area(det_box) / max(1.0, box_area(track_box))
                if iou < self.iou_thres and center_dist > self.max_center_dist:
                    continue
                if area_ratio > self.max_scale_change or area_ratio < (1.0 / self.max_scale_change):
                    continue

                # Hybrid score: prefer higher IoU and closer center distance.
                score = iou + max(0.0, 1.0 - (center_dist / max(1e-6, self.max_center_dist)))
                candidates.append((score, track_id, det_idx))

        candidates.sort(reverse=True, key=lambda item: item[0])
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()

        for _, track_id, det_idx in candidates:
            if track_id in matched_tracks or det_idx in matched_dets:
                continue
            track = self.tracks[track_id]
            old_cx, old_cy = box_center(track.bbox)
            new_cx, new_cy = box_center(detections[det_idx])
            track.vx = new_cx - old_cx
            track.vy = new_cy - old_cy
            track.bbox = detections[det_idx]
            track.hits += 1
            track.age += 1
            track.missing = 0
            matched_tracks.add(track_id)
            matched_dets.add(det_idx)

        for track_id in track_ids:
            if track_id in matched_tracks:
                continue
            track = self.tracks[track_id]
            track.age += 1
            track.missing += 1
            # Predict next position to keep up with motion during brief detector miss.
            x, y, w, h = track.bbox
            predicted_x = int(x + track.vx)
            predicted_y = int(y + track.vy)
            track.bbox = [predicted_x, predicted_y, w, h]
            track.vx *= 0.8
            track.vy *= 0.8

        stale_ids = [
            track_id
            for track_id, track in self.tracks.items()
            if track.missing > self.max_missing
        ]
        for track_id in stale_ids:
            del self.tracks[track_id]

        for det_idx, det_box in enumerate(detections):
            if det_idx in matched_dets:
                continue
            track_id = self.next_id
            self.next_id += 1
            self.tracks[track_id] = FaceTrack(track_id=track_id, bbox=det_box)

        return self.valid_tracks()

    def valid_tracks(self) -> list[FaceTrack]:
        tracks = [
            track
            for track in self.tracks.values()
            if track.hits >= self.min_hits and track.missing <= self.count_max_missing
        ]
        tracks.sort(key=lambda item: item.track_id)
        return tracks


@dataclass
class HandGestureState:
    label: str
    count: int
    bbox: tuple[int, int, int, int]


class HandGestureRecognizer:
    def __init__(
        self,
        max_hands: int,
        min_detection_conf: float,
        min_tracking_conf: float,
        model_path: Path | None = None,
    ) -> None:
        if mp is None:
            raise RuntimeError("mediapipe is not installed")

        self.backend = ""
        self.model_path = model_path
        self.mp_hands = None
        self.drawer = None
        self.hands = None
        self.task_vision = None
        self.task_landmarker = None
        self.task_connections = []
        self.video_ts_ms = 0
        self._init_backend(
            max_hands=max_hands,
            min_detection_conf=min_detection_conf,
            min_tracking_conf=min_tracking_conf,
            model_path=model_path,
        )

    def _init_backend(
        self,
        max_hands: int,
        min_detection_conf: float,
        min_tracking_conf: float,
        model_path: Path | None,
    ) -> None:
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
            self.mp_hands = mp.solutions.hands
            self.drawer = mp.solutions.drawing_utils
            self.hands = self.mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=max(1, max_hands),
                min_detection_confidence=min_detection_conf,
                min_tracking_confidence=min_tracking_conf,
            )
            self.backend = "solutions"
            return

        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        self.task_vision = mp_vision
        task_model_path = model_path
        if task_model_path is None:
            task_model_path = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"
        ensure_file(task_model_path, HAND_LANDMARKER_TASK_URL, min_bytes=1_000_000)

        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(task_model_path)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=max(1, max_hands),
            min_hand_detection_confidence=min_detection_conf,
            min_hand_presence_confidence=min_tracking_conf,
            min_tracking_confidence=min_tracking_conf,
        )
        self.task_landmarker = mp_vision.HandLandmarker.create_from_options(options)
        self.task_connections = list(mp_vision.HandLandmarksConnections.HAND_CONNECTIONS)
        self.backend = "tasks"

    def close(self) -> None:
        if self.backend == "solutions" and self.hands is not None:
            self.hands.close()
        if self.backend == "tasks" and self.task_landmarker is not None:
            self.task_landmarker.close()

    def infer(self, frame) -> tuple[int, list[HandGestureState]]:
        if self.backend == "solutions":
            return self._infer_solutions(frame)
        return self._infer_tasks(frame)

    def _infer_solutions(self, frame) -> tuple[int, list[HandGestureState]]:
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.hands.process(rgb)
        if not result.multi_hand_landmarks or not result.multi_handedness:
            return 0, []

        states: list[HandGestureState] = []
        for landmarks, handedness in zip(result.multi_hand_landmarks, result.multi_handedness):
            label = handedness.classification[0].label
            xs = [lm.x for lm in landmarks.landmark]
            ys = [lm.y for lm in landmarks.landmark]
            x1 = max(0, int(min(xs) * w) - 10)
            y1 = max(0, int(min(ys) * h) - 10)
            x2 = min(w - 1, int(max(xs) * w) + 10)
            y2 = min(h - 1, int(max(ys) * h) + 10)
            count = self._count_fingers(landmarks.landmark, label)
            states.append(HandGestureState(label=label, count=count, bbox=(x1, y1, x2, y2)))

            self.drawer.draw_landmarks(frame, landmarks, self.mp_hands.HAND_CONNECTIONS)

        total = sum(item.count for item in states)
        return total, states

    def _infer_tasks(self, frame) -> tuple[int, list[HandGestureState]]:
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        now_ms = int(time.time() * 1000)
        if now_ms <= self.video_ts_ms:
            now_ms = self.video_ts_ms + 1
        self.video_ts_ms = now_ms

        result = self.task_landmarker.detect_for_video(mp_image, self.video_ts_ms)
        if not result.hand_landmarks:
            return 0, []

        states: list[HandGestureState] = []
        for landmarks, handedness in zip(result.hand_landmarks, result.handedness):
            label = "Unknown"
            if handedness:
                category = handedness[0]
                label = category.category_name or category.display_name or "Unknown"

            xs = [lm.x for lm in landmarks]
            ys = [lm.y for lm in landmarks]
            x1 = max(0, int(min(xs) * w) - 10)
            y1 = max(0, int(min(ys) * h) - 10)
            x2 = min(w - 1, int(max(xs) * w) + 10)
            y2 = min(h - 1, int(max(ys) * h) + 10)

            count = self._count_fingers(landmarks, label)
            states.append(HandGestureState(label=label, count=count, bbox=(x1, y1, x2, y2)))
            self._draw_task_landmarks(frame, landmarks, w, h)

        total = sum(item.count for item in states)
        return total, states

    def _draw_task_landmarks(self, frame, landmarks, width: int, height: int) -> None:
        points = []
        for lm in landmarks:
            px = min(width - 1, max(0, int(lm.x * width)))
            py = min(height - 1, max(0, int(lm.y * height)))
            points.append((px, py))
            cv2.circle(frame, (px, py), 2, (255, 170, 0), -1)

        for conn in self.task_connections:
            if conn.start >= len(points) or conn.end >= len(points):
                continue
            cv2.line(frame, points[conn.start], points[conn.end], (255, 120, 0), 1)

    def _count_fingers(self, landmarks, hand_label: str) -> int:
        lm = landmarks
        if len(lm) < 21:
            return 0
        count = 0

        # Thumb opening direction depends on left/right hand.
        if hand_label.lower().startswith("right"):
            if lm[4].x < lm[3].x:
                count += 1
        else:
            if lm[4].x > lm[3].x:
                count += 1

        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
            if lm[tip].y < lm[pip].y:
                count += 1
        return count


class DatasetCollector:
    def __init__(
        self,
        out_dir: Path,
        interval_sec: float,
        max_samples: int,
        save_face_crops: bool,
        allow_empty: bool,
    ) -> None:
        self.out_dir = out_dir
        self.images_dir = out_dir / "images"
        self.labels_dir = out_dir / "labels"
        self.crops_dir = out_dir / "face_crops"
        self.interval_sec = max(0.0, interval_sec)
        self.max_samples = max(0, max_samples)
        self.save_face_crops = save_face_crops
        self.allow_empty = allow_empty
        self.last_save_time = 0.0
        self.sample_count = 0

        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.labels_dir.mkdir(parents=True, exist_ok=True)
        if self.save_face_crops:
            self.crops_dir.mkdir(parents=True, exist_ok=True)

    def _to_yolo(self, box: list[int], w: int, h: int) -> tuple[float, float, float, float]:
        x, y, bw, bh = box
        cx = x + (bw / 2.0)
        cy = y + (bh / 2.0)
        return cx / w, cy / h, bw / w, bh / h

    def _normalize_boxes(self, boxes: list[list[int]], w: int, h: int) -> list[list[int]]:
        normalized: list[list[int]] = []
        for x, y, bw, bh in boxes:
            x = max(0, min(x, w - 1))
            y = max(0, min(y, h - 1))
            bw = max(0, min(bw, w - x))
            bh = max(0, min(bh, h - y))
            if bw > 1 and bh > 1:
                normalized.append([x, y, bw, bh])
        return normalized

    def maybe_save(self, frame, boxes: list[list[int]], force: bool = False) -> bool:
        if self.max_samples > 0 and self.sample_count >= self.max_samples:
            return False

        now = time.time()
        if (not force) and self.interval_sec > 0 and (now - self.last_save_time) < self.interval_sec:
            return False

        h, w = frame.shape[:2]
        boxes = self._normalize_boxes(boxes, w, h)
        if (not self.allow_empty) and len(boxes) == 0:
            return False

        stem = f"{int(now * 1000)}_{self.sample_count:06d}"
        image_path = self.images_dir / f"{stem}.jpg"
        label_path = self.labels_dir / f"{stem}.txt"

        cv2.imwrite(str(image_path), frame)
        with label_path.open("w", encoding="utf-8") as f:
            for box in boxes:
                cx, cy, bw, bh = self._to_yolo(box, w, h)
                f.write(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")

        if self.save_face_crops and boxes:
            for idx, (x, y, bw, bh) in enumerate(boxes):
                crop = frame[y : y + bh, x : x + bw]
                if crop.size > 0:
                    crop_path = self.crops_dir / f"{stem}_{idx:02d}.jpg"
                    cv2.imwrite(str(crop_path), crop)

        self.sample_count += 1
        self.last_save_time = now
        return True


def main() -> int:
    args = parse_args()
    if args.backend == "dnn":
        detector = make_dnn_detector(args.model_dir)
    elif args.backend == "yunet":
        detector = make_yunet_detector(args.model_dir, args.conf_thres, args.nms_thres)
    else:
        detector = make_haar_detector()

    hand_recognizer = None
    if args.enable_gesture:
        if mp is None:
            print(
                "Gesture mode requires mediapipe. Install with: pip install mediapipe",
                file=sys.stderr,
            )
            return 1
        hand_recognizer = HandGestureRecognizer(
            max_hands=args.gesture_max_hands,
            min_detection_conf=args.gesture_min_detection_conf,
            min_tracking_conf=args.gesture_min_tracking_conf,
            model_path=args.gesture_model_path,
        )
        print(f"Gesture backend: {hand_recognizer.backend}", file=sys.stderr)

    collector = None
    if args.collect_data:
        collector = DatasetCollector(
            out_dir=args.collect_dir,
            interval_sec=args.collect_interval,
            max_samples=args.collect_max_samples,
            save_face_crops=args.collect_face_crops,
            allow_empty=args.collect_allow_empty,
        )
        print(f"Collecting data to: {args.collect_dir}", file=sys.stderr)
        print("Press 'c' to save one sample immediately.", file=sys.stderr)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"Failed to open webcam index {args.camera}", file=sys.stderr)
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    prev_time = time.time()
    history = deque(maxlen=max(1, args.smooth))
    gesture_history = deque(maxlen=max(1, args.gesture_smooth))
    tracker = FaceTracker(
        iou_thres=max(0.0, min(1.0, args.track_iou)),
        max_missing=max(0, args.track_max_missing),
        min_hits=max(1, args.track_min_hits),
        max_center_dist=max(0.05, args.track_max_center_dist),
        max_scale_change=max(1.01, args.track_max_scale_change),
        count_max_missing=max(0, args.count_max_missing),
    )

    print("Press 'q' to quit.", file=sys.stderr)
    frame_index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Failed to read frame from webcam.", file=sys.stderr)
            break

        detect_frame = frame
        scale = 1.0
        h, w = frame.shape[:2]
        if args.detect_width > 0 and args.detect_width < w:
            scale = args.detect_width / float(w)
            detect_frame = cv2.resize(frame, (args.detect_width, int(h * scale)))

        if args.backend == "dnn":
            boxes = detect_faces_dnn(
                detector,
                detect_frame,
                conf_thres=args.conf_thres,
                nms_thres=args.nms_thres,
                min_face=args.min_face,
            )
        elif args.backend == "yunet":
            boxes = detect_faces_yunet(detector, detect_frame, args.min_face)
        else:
            boxes = detect_faces_haar(detector, detect_frame, args.min_face)

        if scale != 1.0:
            inv_scale = 1.0 / scale
            boxes = [
                [
                    int(x * inv_scale),
                    int(y * inv_scale),
                    int(bw * inv_scale),
                    int(bh * inv_scale),
                ]
                for (x, y, bw, bh) in boxes
            ]

        boxes = filter_face_boxes(
            boxes,
            frame_w=w,
            frame_h=h,
            min_ar=args.face_min_ar,
            max_ar=args.face_max_ar,
            min_area_ratio=args.face_min_area_ratio,
            max_area_ratio=args.face_max_area_ratio,
        )

        tracks = tracker.update(boxes)
        raw_face_count = len(boxes)
        tracked_face_count = len(tracks)
        history.append(tracked_face_count)
        face_count = int(statistics.median(history))

        boxes_for_collect = [track.bbox for track in tracks if track.missing <= 1]
        if not boxes_for_collect:
            boxes_for_collect = boxes
        saved_now = False
        if collector is not None:
            saved_now = collector.maybe_save(frame, boxes_for_collect, force=False)

        gesture_raw = 0
        gesture_value = 0
        hand_states: list[HandGestureState] = []
        if hand_recognizer is not None:
            gesture_raw, hand_states = hand_recognizer.infer(frame)
            gesture_history.append(gesture_raw)
            gesture_value = int(statistics.median(gesture_history))

        for track in tracks:
            x, y, bw, bh = track.bbox
            if track.missing == 0:
                color = (30, 200, 30)
                tag = f"ID {track.track_id}"
            else:
                color = (0, 170, 255)
                tag = f"ID {track.track_id} hold:{track.missing}"
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
            cv2.putText(
                frame,
                tag,
                (x, max(20, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
                cv2.LINE_AA,
            )

        for state in hand_states:
            x1, y1, x2, y2 = state.bbox
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 150, 40), 2)
            cv2.putText(
                frame,
                f"{state.label}:{state.count}",
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 150, 40),
                2,
                cv2.LINE_AA,
            )

        now = time.time()
        fps = 1.0 / max(1e-6, now - prev_time)
        prev_time = now

        cv2.putText(
            frame,
            f"Faces: {face_count} (det:{raw_face_count}, track:{tracked_face_count})",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (30, 220, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"FPS: {fps:.1f}",
            (20, 75),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 200, 70),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"backend: {args.backend}",
            (20, 108),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (200, 255, 200),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"track miss:{args.track_max_missing} iou:{args.track_iou:.2f}",
            (20, 136),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (200, 220, 255),
            2,
            cv2.LINE_AA,
        )
        if hand_recognizer is not None:
            cv2.putText(
                frame,
                f"gesture: {gesture_value} (raw:{gesture_raw})",
                (20, 164),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 180, 90),
                2,
                cv2.LINE_AA,
            )
        if collector is not None:
            save_color = (80, 255, 120) if saved_now else (160, 200, 255)
            cv2.putText(
                frame,
                f"collect: {collector.sample_count}",
                (20, 192),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                save_color,
                2,
                cv2.LINE_AA,
            )

        if args.stdout_json:
            payload = {
                "frame": frame_index,
                "timestamp_ms": int(now * 1000),
                "faces": {
                    "value": face_count,
                    "raw": raw_face_count,
                    "tracked": tracked_face_count,
                },
                "gesture": {
                    "value": gesture_value,
                    "raw": gesture_raw,
                    "hands": [
                        {
                            "label": state.label,
                            "count": state.count,
                            "bbox": [state.bbox[0], state.bbox[1], state.bbox[2], state.bbox[3]],
                        }
                        for state in hand_states
                    ],
                },
            }
            print(json.dumps(payload, ensure_ascii=False), flush=True)

        cv2.imshow("Face Counter", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("c") and collector is not None:
            collector.maybe_save(frame, boxes_for_collect, force=True)
        if key in (ord("q"), 27):
            break
        frame_index += 1

    cap.release()
    if hand_recognizer is not None:
        hand_recognizer.close()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
