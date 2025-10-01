import os
from typing import Tuple, Optional

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError
import pytesseract


# Ensure Tesseract path on Windows if available
try:
    if os.name == 'nt':
        t_path = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
        if os.path.exists(t_path):
            pytesseract.pytesseract.tesseract_cmd = t_path
except Exception:
    pass


def open_image_or_error(path: str) -> Image.Image:
    """Open image robustly or raise UnidentifiedImageError/Exception."""
    img = Image.open(path)
    img.load()
    return img


def preprocess_for_ocr(pil_img: Image.Image) -> Image.Image:
    """Lightweight preprocessing to improve OCR quality without OpenCV."""
    pil_gray = pil_img.convert('L')
    w, h = pil_gray.size
    # Avoid zero-size
    pil_gray = pil_gray.resize((max(1, w * 2), max(1, h * 2)))
    pil_blur = pil_gray.filter(ImageFilter.GaussianBlur(radius=1))
    pil_autocontrast = ImageOps.autocontrast(pil_blur)
    pil_thresh = pil_autocontrast.point(lambda p: 255 if p > 160 else 0)
    return pil_thresh


def perform_ocr(pil_img: Image.Image, fallback_to_original: bool = True) -> Tuple[str, Image.Image]:
    """Run OCR with preprocessing; optionally fallback to original image.

    Returns (text, processed_image_used)
    """
    try:
        processed = preprocess_for_ocr(pil_img)
        text = pytesseract.image_to_string(processed, config='--oem 3 --psm 6')
        return text, processed
    except Exception:
        if fallback_to_original:
            text = pytesseract.image_to_string(pil_img, config='--oem 3 --psm 6')
            return text, pil_img
        raise


def ocr_image_file(path: str) -> Tuple[str, Image.Image]:
    """Convenience: open an image from path, then OCR it. Returns (text, processed_image)."""
    pil_img = open_image_or_error(path)
    return perform_ocr(pil_img)


