import base64
import io
from typing import Optional
from PIL import Image


class LRImageCropper:
    """Service to crop and encode bounding box image snippets for human-in-the-loop verification (FR4)."""

    @staticmethod
    def crop_bounding_box_base64(
        image_input: Image.Image,
        bbox: list[float],
        padding_px: int = 6,
    ) -> Optional[str]:
        """Crops a rectangular bounding box from PIL Image and returns Base64 PNG data URL."""
        if not image_input or not bbox or len(bbox) < 4:
            return None

        width, height = image_input.size
        x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]

        # Apply padding and clamp to image dimensions
        left = max(0, int(min(x1, x2) - padding_px))
        top = max(0, int(min(y1, y2) - padding_px))
        right = min(width, int(max(x1, x2) + padding_px))
        bottom = min(height, int(max(y1, y2) + padding_px))

        if right <= left or bottom <= top:
            return None

        try:
            cropped = image_input.crop((left, top, right, bottom))
            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG", optimize=True)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return f"data:image/png;base64,{encoded}"
        except Exception:
            return None

