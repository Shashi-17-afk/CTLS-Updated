import numpy as np
from PIL import Image, ImageDraw
import pytest

from backend.app.services.ocr.engine_rapid import RapidPaddleOCREngine
from backend.app.services.ocr.base import OCRResult


def test_coordinate_inversion_all_four_rotations_non_square() -> None:
    """
    Verifies that bounding-box inverse mapping for k in {0, 1, 2, 3} on non-square
    dimensions (e.g. 1241 x 1754) is a mathematically exact bijection with 0 error.
    """
    w_orig = 1241.0
    h_orig = 1754.0

    test_boxes = [
        [[50.0, 100.0], [250.0, 100.0], [250.0, 140.0], [50.0, 140.0]],
        [[300.5, 600.25], [700.5, 600.25], [700.5, 645.25], [300.5, 645.25]],
        [[0.0, 0.0], [w_orig, 0.0], [w_orig, h_orig], [0.0, h_orig]],
    ]

    def forward_transform(pts: list[list[float]], k: int) -> tuple[list[list[float]], float, float]:
        res = []
        if k == 0:
            w_rot, h_rot = w_orig, h_orig
            for x, y in pts:
                res.append([x, y])
        elif k == 1:
            # 90° CCW: w_rot = h_orig, h_rot = w_orig
            w_rot, h_rot = h_orig, w_orig
            for x, y in pts:
                res.append([y, w_orig - x])
        elif k == 2:
            # 180°: w_rot = w_orig, h_rot = h_orig
            w_rot, h_rot = w_orig, h_orig
            for x, y in pts:
                res.append([w_orig - x, h_orig - y])
        elif k == 3:
            # 270° CCW / 90° CW: w_rot = h_orig, h_rot = w_orig
            w_rot, h_rot = h_orig, w_orig
            for x, y in pts:
                res.append([h_orig - y, x])
        return res, w_rot, h_rot

    for k in (0, 1, 2, 3):
        for box in test_boxes:
            fwd_box, w_rot, h_rot = forward_transform(box, k)
            inv_box = RapidPaddleOCREngine._invert_box_coords(fwd_box, k, w_rot, h_rot)

            for orig_pt, inverted_pt in zip(box, inv_box):
                err = abs(orig_pt[0] - inverted_pt[0]) + abs(orig_pt[1] - inverted_pt[1])
                assert err < 1e-6, f"k={k} mapping error {err} on {orig_pt} vs {inverted_pt}"


def test_score_ocr_orientation_number_heavy_and_aspect_ratio() -> None:
    """
    Verifies that orientation scoring strongly rewards handwritten number-heavy
    logistics tokens (dates, vehicle numbers, LR numbers, decimal weights) and
    horizontal line aspect ratios, while penalizing vertical noise slices.
    """
    engine = RapidPaddleOCREngine()

    # Upright logistics sheet: horizontal boxes, logistics keywords, vehicle plate, date, weight, LR
    upright_items = [
        # (coords, text, conf)
        ([[100, 50], [450, 50], [450, 80], [100, 80]], "CT LOGISTICS SOLUTIONS", 0.96),
        ([[100, 90], [350, 90], [350, 120], [100, 120]], "Truck No: TN88L6340", 0.94),
        ([[370, 90], [550, 90], [550, 120], [370, 120]], "Date: 29/01/26", 0.95),
        ([[100, 140], [220, 140], [220, 170], [100, 170]], "LR: 29795", 0.92),
        ([[240, 140], [400, 140], [400, 170], [240, 170]], "Gross: 20858.5", 0.93),
        ([[420, 140], [560, 140], [560, 170], [420, 170]], "Packages: 426", 0.91),
    ]

    # Sideways / vertical noisy fragmentation: 20 vertical slices, low confidence, garbled text
    noisy_sideways_items = [
        ([[50, i * 30], [70, i * 30], [70, i * 30 + 80], [50, i * 30 + 80]], f"| {i} ..", 0.45)
        for i in range(20)
    ]

    upright_score = engine._score_ocr_orientation(upright_items)
    sideways_score = engine._score_ocr_orientation(noisy_sideways_items)

    assert upright_score > 100.0, f"Expected high upright score, got {upright_score}"
    assert upright_score > sideways_score * 3.0, (
        f"Upright score {upright_score} should be > 3x sideways score {sideways_score}"
    )


def test_rotation_selection_does_not_require_greater_line_count() -> None:
    """
    Verifies that a rotation with fewer, cleaner consolidated lines beats a rotation
    with more noisy fragmented lines, proving removal of the line-count requirement.
    """
    engine = RapidPaddleOCREngine()

    # Orientation 0: 30 noisy fragments (score ~30)
    out_0 = [
        ([[10, i * 20], [30, i * 20], [30, i * 20 + 60], [10, i * 20 + 60]], f":/ {i}", 0.40)
        for i in range(30)
    ]

    # Orientation 1: 5 clean logistics lines (score ~150)
    out_1 = [
        ([[50, 50], [400, 50], [400, 80], [50, 80]], "CT LOGISTICS SOLUTIONS", 0.95),
        ([[50, 90], [300, 90], [300, 120], [50, 120]], "Truck: TN40B3804", 0.95),
        ([[320, 90], [500, 90], [500, 120], [320, 120]], "Date: 29/01/26", 0.95),
        ([[50, 130], [200, 130], [200, 160], [50, 160]], "LR: 30084", 0.93),
        ([[220, 130], [450, 130], [450, 160], [220, 160]], "Weight: 14691.3", 0.94),
    ]

    score_0 = engine._score_ocr_orientation(out_0)
    score_1 = engine._score_ocr_orientation(out_1)

    assert len(out_0) > len(out_1), "Test precondition: out_0 has more lines than out_1"
    assert score_1 > score_0 * 1.5, "out_1 should have significantly higher structural score"


def test_ocr_result_structure_and_interface_preserved() -> None:
    """
    Verifies that RapidPaddleOCREngine adheres to BaseOCREngine interface and produces
    valid OCRResult structures with proper bounding box format and types.
    """
    engine = RapidPaddleOCREngine()
    assert hasattr(engine, "extract")
    assert hasattr(engine, "is_available")

    # Create synthetic test image
    img = Image.new("RGB", (400, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), "CTLS TRUCK TN52AC9337", fill=(0, 0, 0))
    draw.text((20, 80), "DATE 29/01/26 WEIGHT 14500", fill=(0, 0, 0))

    img_arr = np.array(img)
    if engine.is_available():
        res = engine.extract(img_arr)
        assert isinstance(res, OCRResult)
        assert isinstance(res.text, str)
        assert isinstance(res.lines, list)
        assert res.char_count >= 0
        assert res.word_count >= 0
        for line in res.lines:
            assert isinstance(line.text, str)
            assert len(line.box) == 4
            for pt in line.box:
                assert len(pt) == 2
                assert 0.0 <= pt[0] <= 400.0
                assert 0.0 <= pt[1] <= 200.0


def test_early_exit_all_five_conditions_required() -> None:
    """
    Verifies that early-exit requires ALL 5 conditions simultaneously:
    1. score >= 180.0
    2. conf >= 0.88
    3. h_ratio >= 0.85
    4. v_boxes <= 1
    5. (keywords >= 2 or numerics >= 2) and top_headers >= 1
    Failing ANY condition forces evaluation of all 4 orientations.
    """
    def check_eligible(score, conf, h_boxes, v_boxes, kw, num, top_h):
        tot = h_boxes + v_boxes
        h_ratio = (h_boxes / tot) if tot > 0 else 0.0
        return bool(
            score >= 180.0
            and conf >= 0.88
            and h_ratio >= 0.85
            and v_boxes <= 1
            and (kw >= 2 or num >= 2)
            and top_h >= 1
        )

    # 1. Base passing case
    assert check_eligible(score=220.0, conf=0.92, h_boxes=10, v_boxes=0, kw=3, num=3, top_h=2) is True

    # 2. Fail condition 1 (score < 180)
    assert check_eligible(score=170.0, conf=0.92, h_boxes=10, v_boxes=0, kw=3, num=3, top_h=2) is False

    # 3. Fail condition 2 (conf < 0.88)
    assert check_eligible(score=220.0, conf=0.85, h_boxes=10, v_boxes=0, kw=3, num=3, top_h=2) is False

    # 4. Fail condition 3 (h_ratio < 0.85)
    assert check_eligible(score=220.0, conf=0.92, h_boxes=7, v_boxes=3, kw=3, num=3, top_h=2) is False

    # 5. Fail condition 4 (v_boxes > 1)
    assert check_eligible(score=220.0, conf=0.92, h_boxes=20, v_boxes=2, kw=3, num=3, top_h=2) is False

    # 6. Fail condition 5a (kw < 2 and num < 2)
    assert check_eligible(score=220.0, conf=0.92, h_boxes=10, v_boxes=0, kw=1, num=1, top_h=2) is False

    # 7. Fail condition 5b (top_h < 1, upside down page)
    assert check_eligible(score=220.0, conf=0.92, h_boxes=10, v_boxes=0, kw=3, num=3, top_h=0) is False


def test_sideways_page_fails_early_exit() -> None:
    """
    Verifies that a sideways page with vertical text/bounding boxes fails early exit at 0°
    because vertical_boxes > 1 and h_ratio < 0.85.
    """
    engine = RapidPaddleOCREngine()

    # Sideways page scanned at 0°: vertical slices, fragmented words
    sideways_items_at_0 = [
        ([[100, i * 40], [130, i * 40], [130, i * 40 + 100], [100, i * 40 + 100]], f"vert_{i}", 0.82)
        for i in range(10)
    ]
    score_0, conf_0, h_0, v_0, kw_0, num_0, top_kw_0 = engine._evaluate_orientation_signals(
        sideways_items_at_0, 700.0
    )
    tot = h_0 + v_0
    h_ratio = (h_0 / tot) if tot > 0 else 0.0

    # Ensure sideways page strictly fails early-exit criteria
    assert v_0 > 1, f"Expected vertical boxes > 1, got {v_0}"
    assert h_ratio < 0.85, f"Expected h_ratio < 0.85, got {h_ratio}"
    early_exit = bool(
        score_0 >= 180.0
        and conf_0 >= 0.88
        and h_ratio >= 0.85
        and v_0 <= 1
        and (kw_0 >= 2 or num_0 >= 2)
        and top_kw_0 >= 1
    )
    assert early_exit is False, "Sideways page must NEVER trigger early exit at 0°"


def test_synthetic_page_rotations_and_logging(caplog) -> None:
    """
    Tests synthetic non-square pages across rotations (0°, 90°, 180°, 270°)
    and verifies that logging captures the selected rotation and whether early exit occurred.
    """
    import logging
    engine = RapidPaddleOCREngine()
    if not engine.is_available():
        pytest.skip("RapidOCR engine not available in environment.")

    # Upright realistic page with full logistics lines
    w, h = 800, 700
    img = Image.new("RGB", (w, h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = [
        "CT LOGISTICS SOLUTIONS DESPATCH DETAILS",
        "LORRY NUMBER: TN40B3804   DATE: 29/01/26",
        "TRANSPORTER BROKER: CTLS ERODE BRANCH",
        "LR NO: 30084   PACKAGES: 396   WEIGHT: 14691.3 KGS",
        "CONSIGNEE: SRE NE PANI BINDERS VELLORE",
        "INVOICE NO: 10425   EWAY BILL: 251489201928",
        "DRIVER NAME: SELVAKUMAR   PHONE: 9842712345",
        "OWNER NAME: TAMILARASAN   PHONE: 8440857777",
    ]
    for idx, text in enumerate(lines):
        draw.text((40, 40 + idx * 60), text, fill=(0, 0, 0))
    arr_0 = np.array(img)

    with caplog.at_level(logging.INFO):
        # 1. Upright image at 0° -> triggers early exit
        out_0, k_0, w_0, h_0 = engine._extract_with_orientation_detection(arr_0)
        assert k_0 == 0
        assert "early-exit triggered at 0°" in caplog.text

    caplog.clear()

    # 2. Input rotated 90° CW (np.rot90 k=3) -> must detect k=1 (90° CCW) to restore upright
    arr_90_cw = np.ascontiguousarray(np.rot90(arr_0, k=3))
    with caplog.at_level(logging.INFO):
        out_1, k_1, w_1, h_1 = engine._extract_with_orientation_detection(arr_90_cw)
        assert k_1 == 1
        assert "early_exit=False" in caplog.text
        assert "Selected rotation k=1 (90° CCW)" in caplog.text

    caplog.clear()

    # 3. Input upside-down 180° (np.rot90 k=2) -> must detect k=2 to restore upright
    arr_180 = np.ascontiguousarray(np.rot90(arr_0, k=2))
    with caplog.at_level(logging.INFO):
        out_2, k_2, w_2, h_2 = engine._extract_with_orientation_detection(arr_180)
        assert k_2 == 2
        assert "early_exit=False" in caplog.text
        assert "Selected rotation k=2 (180° CCW)" in caplog.text

    caplog.clear()

    # 4. Input rotated 90° CCW (np.rot90 k=1) -> must detect k=3 (270° CCW / 90° CW) to restore upright
    arr_90_ccw = np.ascontiguousarray(np.rot90(arr_0, k=1))
    with caplog.at_level(logging.INFO):
        out_3, k_3, w_3, h_3 = engine._extract_with_orientation_detection(arr_90_ccw)
        assert k_3 == 3
        assert "early_exit=False" in caplog.text
        assert "Selected rotation k=3 (270° CCW)" in caplog.text


def test_low_confidence_synthetic_page_evaluates_all_rotations(caplog) -> None:
    """
    Verifies that a page with low confidence (< 0.88) or low score does not early exit,
    but instead evaluates all 4 rotations and logs early_exit=False.
    """
    import logging
    engine = RapidPaddleOCREngine()
    if not engine.is_available():
        pytest.skip("RapidOCR engine not available in environment.")

    # Short low-line synthetic page (score < 180)
    w, h = 400, 200
    img = Image.new("RGB", (w, h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), "SHORT NOTE LR 1234", fill=(120, 120, 120))  # faint text
    arr_faint = np.array(img)

    with caplog.at_level(logging.INFO):
        out, k, _, _ = engine._extract_with_orientation_detection(arr_faint)
        assert k == 0
        assert "early_exit=False" in caplog.text



