import io
from typing import Tuple, Union
import cv2
import numpy as np
from PIL import Image

from backend.app.core.config import settings
from backend.app.core.logging import logger


class ImagePreprocessor:
    """Preprocesses images for optimal local OCR recognition (deskew, scale, normalization)."""

    @classmethod
    def preprocess(
        cls, image_input: Union[bytes, Image.Image, np.ndarray]
    ) -> Tuple[np.ndarray, float]:
        """
        Converts input to a standard RGB numpy array, resizes if oversized,
        and applies deskewing if enabled.

        Returns:
            Tuple of (preprocessed_image_ndarray, detected_skew_angle)
        """
        # 1. Convert to RGB numpy array
        img_array = cls._to_numpy_rgb(image_input)

        # 2. Bounded dimension check & downscale if exceeding maximum side
        h, w = img_array.shape[:2]
        max_side = settings.OCR_MAX_IMAGE_SIDE_PX
        if max(h, w) > max_side:
            scale = max_side / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            img_array = cv2.resize(img_array, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # 3. Deskewing
        skew_angle = 0.0
        if settings.ENABLE_DESKEW:
            img_array, skew_angle = cls._deskew(img_array)

        return img_array, skew_angle

    @staticmethod
    def _to_numpy_rgb(image_input: Union[bytes, Image.Image, np.ndarray]) -> np.ndarray:
        """Ensures image is a 3-channel RGB numpy array."""
        if isinstance(image_input, bytes):
            image = Image.open(io.BytesIO(image_input)).convert("RGB")
            return np.array(image)
        elif isinstance(image_input, Image.Image):
            return np.array(image_input.convert("RGB"))
        elif isinstance(image_input, np.ndarray):
            if len(image_input.shape) == 2:  # Grayscale
                return cv2.cvtColor(image_input, cv2.COLOR_GRAY2RGB)
            elif image_input.shape[2] == 4:  # RGBA
                return cv2.cvtColor(image_input, cv2.COLOR_RGBA2RGB)
            return image_input
        else:
            raise ValueError(f"Unsupported image input type: {type(image_input)}")

    @classmethod
    def _deskew(cls, img: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Detects skew angle and rotates the image if a significant angle is found.
        Restricts correction to +/- 45 degrees to avoid accidental 90-degree rotations.
        """
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            # Threshold to isolate text blocks
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

            # Morphological horizontal dilation to merge letters into line segments
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 2))
            dilated = cv2.dilate(thresh, kernel, iterations=2)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            angles = []
            for cnt in contours:
                if cv2.contourArea(cnt) > 200:
                    (cx, cy), (w, h), ang = cv2.minAreaRect(cnt)
                    if w < h:
                        w, h = h, w
                        ang = ang + 90 if ang < 0 else ang - 90
                    # Only accept horizontal text lines with strong aspect ratio
                    if w >= 2.5 * h:
                        if -15.0 <= ang <= 15.0:
                            angles.append(ang)

            if not angles:
                return img, 0.0

            angle = float(np.median(angles))

            # Ignore negligible skew
            if abs(angle) < 0.5:
                return img, 0.0

            # Apply affine rotation around image center
            (h, w) = img.shape[:2]
            center = (w // 2, h // 2)
            rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
            deskewed = cv2.warpAffine(
                img,
                rot_mat,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            return deskewed, round(float(angle), 2)

        except Exception as err:
            logger.debug("Deskew detection skipped: %s", str(err))
            return img, 0.0
