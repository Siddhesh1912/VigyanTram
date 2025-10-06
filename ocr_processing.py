import os
from typing import Tuple, Optional

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError
import pytesseract
import cv2
import numpy as np


# Ensure Tesseract path on Windows
if os.name == 'nt':
    pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"


def open_image_or_error(path: str) -> Image.Image:
    """Open image robustly or raise UnidentifiedImageError/Exception."""
    img = Image.open(path)
    img.load()
    return img


def preprocess_for_ocr(pil_img: Image.Image) -> Image.Image:
    """Lightweight preprocessing to improve OCR quality without OpenCV."""
    # Convert PIL image to OpenCV format
    img = np.array(pil_img.convert('RGB'))
    img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    h, w = img.shape
    # Upscale 3x for better OCR resolution
    img = cv2.resize(img, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)
    # Bilateral filter for denoising while preserving edges
    img = cv2.bilateralFilter(img, d=9, sigmaColor=75, sigmaSpace=75)
    # CLAHE for local contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    img = clahe.apply(img)
    # Strong sharpening kernel
    kernel = np.array([[0, -1, 0], [-1, 5,-1], [0, -1, 0]])
    img = cv2.filter2D(img, -1, kernel)
    # Adaptive thresholding
    img = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
    # Convert back to PIL Image
    pil_out = Image.fromarray(img)
    return pil_out


def perform_ocr(pil_img: Image.Image, fallback_to_original: bool = True) -> Tuple[str, Image.Image]:
    """Run OCR with preprocessing; optionally fallback to original image.

    Returns (text, processed_image_used)
    """
    print(f"[DEBUG] Tesseract cmd: {pytesseract.pytesseract.tesseract_cmd}")
    try:
        processed = preprocess_for_ocr(pil_img)
        text = pytesseract.image_to_string(processed, config='--oem 3 --psm 6')
        return text, processed
    except Exception as e:
        print(f"[DEBUG] OCR failed on processed: {e}")
        if fallback_to_original:
            try:
                text = pytesseract.image_to_string(pil_img, config='--oem 3 --psm 6')
                return text, pil_img
            except Exception as e2:
                print(f"[DEBUG] OCR failed on original: {e2}")
                raise e2
        raise


def ocr_image_file(path: str) -> Tuple[str, Image.Image]:
    """Convenience: open an image from path, then OCR it. Returns (text, processed_image)."""
    pil_img = open_image_or_error(path)
    return perform_ocr(pil_img)


