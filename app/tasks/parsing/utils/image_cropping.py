"""
Image cropping utilities for extracting figures from PDFs.

This module handles:
- Cropping images/figures from PDFs based on bounding boxes
- Converting cropped regions to PIL Images for vision processing
- Saving cropped images to disk for debugging and processing
"""

import os
import uuid
import logging
from io import BytesIO
from typing import Any
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)


def crop_and_save_images_from_figures(
    file_name: str,
    document_bytes: bytes,
    figures: list[dict[str, Any]],
    file_id: str,
    output_dir: str,
    dpi: int = 300
) -> list[dict[str, Any]]:
    """
    Crop images/figures from PDF based on bounding boxes from Azure Document Intelligence.

    This function:
    1. Opens the PDF from bytes
    2. For each figure, extracts the bounding box
    3. Crops the image from the PDF at high resolution
    4. Saves the cropped image to disk
    5. Returns metadata for vision processing

    Args:
        file_name: Original filename (for logging)
        document_bytes: PDF document as bytes
        figures: List of figure metadata dicts from Document Intelligence
                 Each dict should have 'bounding_regions', 'spans', etc.
        file_id: Document ID (for organizing output)
        output_dir: Directory to save cropped images
        dpi: Resolution for cropping (300 is good quality, 150 for faster processing)

    Returns:
        List[dict]: List of cropped image metadata for vision processing
                   Each dict contains: image_path, file_name, file_uid,
                   bounding_regions, page_number, spans
    """
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Open PDF from bytes
    document_stream = BytesIO(document_bytes)
    pdf_document = fitz.open(stream=document_stream, filetype="pdf")

    result = []

    logger.info(f"Processing {len(figures)} figures from {file_name}")

    for figure_idx, figure in enumerate(figures):
        # Each figure can span multiple regions (usually 1)
        bounding_regions = figure.get('bounding_regions', [])

        if not bounding_regions:
            logger.warning(f"Figure {figure_idx} has no bounding regions, skipping")
            continue

        for region in bounding_regions:
            try:
                page_number = region['page_number'] - 1  # Convert to 0-indexed
                polygon = region['polygon']  # Flat list: [x1, y1, x2, y2, x3, y3, x4, y4]

                # Validate polygon has 8 points (4 corners)
                if len(polygon) < 8:
                    logger.warning(
                        f"Invalid polygon for figure {figure_idx} on page {page_number + 1}: "
                        f"expected 8 points, got {len(polygon)}"
                    )
                    continue

                # Calculate bounding box from polygon
                # Polygon format: [x1, y1, x2, y2, x3, y3, x4, y4]
                # We need min/max to get rectangle
                x_coords = polygon[0::2]  # Every even index (x coordinates)
                y_coords = polygon[1::2]  # Every odd index (y coordinates)

                x0 = min(x_coords) * 72  # Convert to points (72 points per inch)
                y0 = min(y_coords) * 72
                x1 = max(x_coords) * 72
                y1 = max(y_coords) * 72

                # Load page and crop
                page = pdf_document.load_page(page_number)

                # Create transformation matrix for DPI scaling
                mat = fitz.Matrix(dpi / 72, dpi / 72)

                # Create rectangle for clipping
                clip_rect = fitz.Rect(x0, y0, x1, y1)

                # Get pixmap (image) of the cropped region
                pix = page.get_pixmap(matrix=mat, clip=clip_rect)

                # Convert to PIL Image
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                # Generate unique filename
                output_filename = f"{str(uuid.uuid4())}_page_{page_number + 1}.jpg"
                output_path = os.path.join(output_dir, output_filename)

                # Save cropped image
                img.save(output_path, "JPEG", quality=95)

                logger.debug(
                    f"Cropped figure from page {page_number + 1} "
                    f"(size: {pix.width}x{pix.height}) -> {output_filename}"
                )

                # Store metadata for vision processing
                result.append({
                    'file_name': file_name,
                    'image_path': output_path,
                    'file_uid': file_id,
                    'bounding_regions': region,
                    'page_number': page_number + 1,  # Convert back to 1-indexed
                    'spans': figure.get('spans', []),
                    'caption': figure.get('caption', '')
                })

            except Exception as e:
                logger.error(
                    f"Failed to crop figure {figure_idx} on page {page_number + 1}: {str(e)}"
                )
                # Continue processing other figures
                continue

    # Close PDF
    pdf_document.close()

    logger.info(f"Successfully cropped {len(result)} images from {len(figures)} figures")

    return result


def cleanup_cropped_images(image_paths: list[str]) -> None:
    """
    Clean up cropped images after processing.

    Args:
        image_paths: List of image file paths to delete
    """
    deleted_count = 0

    for image_path in image_paths:
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
                deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete image {image_path}: {str(e)}")

    if deleted_count > 0:
        logger.debug(f"Cleaned up {deleted_count} cropped images")


def get_temp_image_dir(file_id: str) -> str:
    """
    Get temporary directory for storing cropped images.

    Args:
        file_id: Document ID

    Returns:
        str: Path to temporary directory
    """
    temp_dir = os.path.join("/tmp", "memic_vision", file_id)
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir
