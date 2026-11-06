import re
from typing import Any, Optional
import numpy as np

from backend.app.core.logging import logger
from backend.app.services.ocr.base import BaseOCREngine, OCRItem, OCRResult
from backend.app.services.ocr.preprocessor import ImagePreprocessor

LOGISTICS_ORIENTATION_KEYWORDS = (
    "truck", "lorry", "vehicle", "despatch", "invoice", "eway", "bill",
    "consign", "party", "weight", "kgs", "packages", "bundles", "reels",
    "pallipalayam", "erode", "tirunelveli", "salem", "chennai", "bangalore",
    "driver", "owner", "date", "total", "signature", "freight", "broker",
    "license", "phone", "loading", "destination", "security", "gate"
)

PAGE_HEADER_KEYWORDS = (
    "logistics", "solutions", "despatch", "consignment", "ctls", "transport",
    "booking", "agreement", "lorry receipt", "details"
)


class RapidPaddleOCREngine(BaseOCREngine):
    """
    Local ONNX-accelerated OCR engine utilizing PP-OCRv4 models.
    Operates completely offline with zero telemetry or network calls.
    """

    def __init__(self) -> None:
        self._engine = None
        self._initialize_engine()

    def _initialize_engine(self) -> None:
        """Lazily initializes the RapidOCR ONNX model pipeline."""
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR

                # Initialize RapidOCR with default embedded PP-OCRv4 ONNX models
                self._engine = RapidOCR()
                logger.info("Initialized local RapidOCR ONNX engine successfully.")
            except Exception as err:
                logger.error("Failed to initialize RapidOCR engine: %s", str(err))
                self._engine = None

    def is_available(self) -> bool:
        return self._engine is not None

    def _evaluate_orientation_signals(
        self, ocr_output: Optional[list], h_page: Optional[float] = None
    ) -> tuple[float, float, int, int, int, int, int]:
        """
        Evaluates structural signals from an OCR orientation output.
        Returns:
            Tuple of (score, mean_conf, horizontal_boxes, vertical_boxes, keyword_hits, numeric_hits, top_header_hits)
        """
        if not ocr_output:
            return 0.0, 0.0, 0, 0, 0, 0, 0

        valid_conf_sum = 0.0
        valid_conf_count = 0
        keyword_hits = 0
        numeric_hits = 0
        horizontal_boxes = 0
        vertical_boxes = 0
        coherent_word_count = 0
        top_header_hits = 0

        date_pat = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")
        veh_pat = re.compile(r"\b[A-Za-z]{2}\s*\d{1,2}\s*[A-Za-z]{0,3}\s*\d{4}\b")
        lr_or_qty_pat = re.compile(r"\b\d{3,7}\b")
        weight_dec_pat = re.compile(r"\b\d{1,6}\.\d{1,3}\b")
        phone_pat = re.compile(r"\b[6-9]\d{9}\b")

        for item in ocr_output:
            try:
                coords, text, conf = item
                t = str(text).strip()
                if not t:
                    continue
                t_lower = t.lower()
                c = float(conf) if conf is not None else 0.5
                valid_conf_sum += c
                valid_conf_count += 1

                # 1. Bounding box aspect ratio (horizontal text vs vertical noise)
                if coords and len(coords) >= 4:
                    xs = [float(pt[0]) for pt in coords]
                    ys = [float(pt[1]) for pt in coords]
                    bw = max(xs) - min(xs)
                    bh = max(ys) - min(ys)
                    if bw >= 1.2 * bh:
                        horizontal_boxes += 1
                    elif bh >= 1.4 * bw:
                        vertical_boxes += 1

                    # Check for genuine document header presence in the top 35% of page
                    if h_page:
                        y_mid = sum(ys) / len(ys)
                        if y_mid < 0.35 * h_page:
                            if any(k in t_lower for k in PAGE_HEADER_KEYWORDS):
                                top_header_hits += 1

                # 2. Logistics domain keywords
                words = re.findall(r"[a-z0-9]+", t_lower)
                for w in words:
                    if len(w) >= 3:
                        coherent_word_count += 1
                        if any(k in w for k in LOGISTICS_ORIENTATION_KEYWORDS):
                            keyword_hits += 1

                # 3. Numeric patterns (dates, weights, LR/quantities, vehicle plates, phones)
                if date_pat.search(t):
                    numeric_hits += 2
                if veh_pat.search(t):
                    numeric_hits += 2
                if weight_dec_pat.search(t):
                    numeric_hits += 1
                if lr_or_qty_pat.search(t):
                    numeric_hits += 1
                if phone_pat.search(t):
                    numeric_hits += 2

            except Exception:
                continue

        if not valid_conf_count:
            return 0.0, 0.0, 0, 0, 0, 0, 0

        mean_conf = valid_conf_sum / valid_conf_count

        # Aspect ratio factor: Latin logistics documents read horizontally.
        # Severely penalize orientations where text is predominantly vertical (sideways scans).
        tot_oriented = horizontal_boxes + vertical_boxes
        h_ratio = (horizontal_boxes / tot_oriented) if tot_oriented > 0 else 0.5
        if tot_oriented >= 2 and h_ratio < 0.40:
            aspect_multiplier = 0.2
        else:
            aspect_multiplier = 0.5 + (0.5 * h_ratio)

        raw_score = (
            (coherent_word_count * 1.0)
            + (keyword_hits * 12.0)
            + (numeric_hits * 8.0)
            + (horizontal_boxes * 2.0)
        )

        score = max(0.0, raw_score) * (0.3 + (mean_conf * 0.7)) * aspect_multiplier
        return score, mean_conf, horizontal_boxes, vertical_boxes, keyword_hits, numeric_hits, top_header_hits

    def _score_ocr_orientation(self, ocr_output: Optional[list]) -> float:
        """
        Scores an OCR candidate orientation based on structural signals.
        Preserved for interface compatibility.
        """
        score, _, _, _, _, _, _ = self._evaluate_orientation_signals(ocr_output)
        return score

    def _extract_with_orientation_detection(
        self, img_arr: np.ndarray
    ) -> tuple[Optional[list], int, float, float]:
        """
        Executes OCR inference with multi-orientation detection (0°, 90°, 180°, 270°).
        Applies a strict 5-condition early-exit optimization on 0° to avoid redundant passes.
        Returns:
            Tuple of (best_ocr_output, best_k, w_rot, h_rot) where k is rotation parameter for np.rot90.
        """
        h_orig, w_orig = img_arr.shape[:2]

        # 1. Run standard 0° orientation first
        out_0, _ = self._engine(img_arr)
        score_0, conf_0, h_boxes_0, v_boxes_0, kw_0, num_0, top_kw_0 = self._evaluate_orientation_signals(
            out_0, float(h_orig)
        )

        # 2. Strict Early-Exit Optimization:
        # All 5 criteria must simultaneously hold to skip evaluating remaining rotations.
        # If any single criterion fails, all 4 orientations are evaluated.
        tot_boxes_0 = h_boxes_0 + v_boxes_0
        h_ratio_0 = (h_boxes_0 / tot_boxes_0) if tot_boxes_0 > 0 else 0.0

        early_exit_eligible = bool(
            out_0
            and score_0 >= 180.0                # Condition 1: Strong structural score
            and conf_0 >= 0.88                  # Condition 2: High token recognition confidence
            and h_ratio_0 >= 0.85               # Condition 3: At least 85% horizontal text boxes
            and v_boxes_0 <= 1                  # Condition 4: Minimal vertical slicing noise (<= 1)
            and (kw_0 >= 2 or num_0 >= 2)       # Condition 5a: Verified logistics vocabulary or numbers
            and top_kw_0 >= 1                   # Condition 5b: Confirms document header is in the upper half
        )

        if early_exit_eligible:
            logger.info(
                "OCR orientation early-exit triggered at 0° (score=%.1f, conf=%.2f, h_ratio=%.2f, "
                "keywords=%d, numerics=%d, top_headers=%d). Skipping rotations 90°, 180°, 270°.",
                score_0,
                conf_0,
                h_ratio_0,
                kw_0,
                num_0,
                top_kw_0,
            )
            return out_0, 0, float(w_orig), float(h_orig)

        # 3. Full evaluation across all four orientations: k=1 (90° CCW), k=2 (180°), k=3 (270° CCW / 90° CW)
        candidates = {
            0: (out_0, score_0, float(w_orig), float(h_orig))
        }

        best_k = 0
        best_score = score_0

        for k in (1, 2, 3):
            rot_img = np.ascontiguousarray(np.rot90(img_arr, k=k))
            out_k, _ = self._engine(rot_img)
            score_k = self._score_ocr_orientation(out_k)
            h_rot, w_rot = rot_img.shape[:2]
            candidates[k] = (out_k, score_k, float(w_rot), float(h_rot))

            if score_k > (best_score * 1.10) and out_k:
                best_k = k
                best_score = score_k

            # Decisive candidate early-exit: If rotated candidate achieves strong structural score >= 180 and decisively beats 0° by 2x,
            # remaining rotations cannot possibly beat it. Skip them to save CPU time.
            if score_k >= 180.0 and score_k >= (score_0 * 2.0):
                logger.info(
                    "Decisive OCR orientation early-exit triggered at rotation k=%d (%d° CCW) "
                    "with score=%.1f (vs 0° score=%.1f). Skipping remaining rotations.",
                    k,
                    k * 90,
                    score_k,
                    score_0,
                )
                break

        logger.info(
            "OCR orientation evaluation completed (early_exit=False). Selected rotation k=%d (%d° CCW) "
            "with score=%.1f (vs 0° score=%.1f).",
            best_k,
            best_k * 90,
            best_score,
            score_0,
        )

        best_out, _, best_w, best_h = candidates[best_k]
        return best_out, best_k, best_w, best_h

    @staticmethod
    def _invert_box_coords(box: list, k: int, w_rot: float, h_rot: float) -> list[list[float]]:
        """
        Inversely transforms rotated bounding box coordinates back to the original image coordinate space.
        """
        orig_box = []
        for pt in box:
            x, y = float(pt[0]), float(pt[1])
            if k == 0:
                orig_box.append([x, y])
            elif k == 1:
                # np.rot90(img, 1) [90° CCW]: w_rot = h_orig, h_rot = w_orig
                # x_orig = h_rot - y_rot, y_orig = x_rot
                orig_box.append([h_rot - y, x])
            elif k == 2:
                # np.rot90(img, 2) [180°]: w_rot = w_orig, h_rot = h_orig
                # x_orig = w_rot - x_rot, y_orig = h_rot - y_rot
                orig_box.append([w_rot - x, h_rot - y])
            elif k == 3:
                # np.rot90(img, 3) [270° CCW / 90° CW]: w_rot = h_orig, h_rot = w_orig
                # x_orig = y_rot, y_orig = w_rot - x_rot
                orig_box.append([y, w_rot - x])
        return orig_box

    def extract(self, image_input: Any) -> OCRResult:
        """
        Executes local OCR inference on the provided image input.
        """
        if not self.is_available():
            raise RuntimeError("Local OCR engine is unavailable or failed to initialize.")

        # 1. Preprocess image (deskew, scale, color normalize)
        preprocessed_img, skew_angle = ImagePreprocessor.preprocess(image_input)

        try:
            # 2. Multi-orientation OCR inference (evaluates 0°, 90°, 180°, 270°)
            ocr_output, best_k, w_rot, h_rot = self._extract_with_orientation_detection(preprocessed_img)
        except Exception as err:
            logger.error("Error during OCR inference: %s", err.__class__.__name__)
            raise RuntimeError(f"OCR inference execution failed: {err.__class__.__name__}") from err

        # 3. Handle empty or no-text result
        if not ocr_output:
            return OCRResult(
                text="",
                lines=[],
                mean_confidence=None,
                char_count=0,
                word_count=0,
            )

        # 4. Standardize recognized items
        lines: list[OCRItem] = []
        confidences: list[float] = []
        text_lines: list[str] = []
        token_boxes: list[tuple[float, float, str]] = []

        for item in ocr_output:
            try:
                box_coords, recognized_text, conf_val = item
                text_clean = str(recognized_text).strip()
                if not text_clean:
                    continue

                # Parse confidence safely
                conf_float = round(float(conf_val), 4) if conf_val is not None else None
                if conf_float is not None:
                    confidences.append(conf_float)

                # Inverse-transform rotated bounding box back to original image coordinate space
                box_orig = self._invert_box_coords(box_coords, best_k, w_rot, h_rot)
                box_formatted = [
                    [round(float(pt[0]), 1), round(float(pt[1]), 1)] for pt in box_orig
                ]

                lines.append(
                    OCRItem(
                        text=text_clean,
                        confidence=conf_float,
                        box=box_formatted,
                    )
                )
                text_lines.append(text_clean)

                # Reading-order midpoint in upright coordinates (where text lines are horizontal)
                if box_coords and len(box_coords) >= 4:
                    y_mid_upright = (float(box_coords[0][1]) + float(box_coords[2][1])) / 2.0
                    x_mid_upright = (float(box_coords[0][0]) + float(box_coords[2][0])) / 2.0
                    token_boxes.append((y_mid_upright, x_mid_upright, text_clean))
                else:
                    token_boxes.append((0.0, 0.0, text_clean))
            except (ValueError, TypeError, IndexError) as parse_err:
                logger.debug("Skipping unparseable OCR token: %s", str(parse_err))
                continue

        # 5. Cluster items into spatial reading lines (top-to-bottom, left-to-right)
        token_boxes.sort(key=lambda t: t[0])
        clustered_text_lines: list[str] = []
        curr_cluster: list[tuple[float, str]] = []
        curr_cluster_y: Optional[float] = None

        for y, x, txt in token_boxes:
            if curr_cluster_y is None or abs(y - curr_cluster_y) <= 14.0:
                curr_cluster.append((x, txt))
                curr_cluster_y = y if curr_cluster_y is None else (curr_cluster_y + y) / 2.0
            else:
                curr_cluster.sort(key=lambda t: t[0])
                clustered_text_lines.append("   ".join(t[1] for t in curr_cluster))
                curr_cluster = [(x, txt)]
                curr_cluster_y = y

        if curr_cluster:
            curr_cluster.sort(key=lambda t: t[0])
            clustered_text_lines.append("   ".join(t[1] for t in curr_cluster))

        full_text = "\n".join(clustered_text_lines) if clustered_text_lines else "\n".join(text_lines)
        char_count = len(full_text)
        word_count = len(full_text.split())
        mean_conf = (
            round(sum(confidences) / len(confidences), 4) if confidences else None
        )

        return OCRResult(
            text=full_text,
            lines=lines,
            mean_confidence=mean_conf,
            char_count=char_count,
            word_count=word_count,
        )
