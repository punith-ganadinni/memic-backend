"""
PDF document parser.

Extracts text, tables, viewport coordinates, and figure content from PDF documents
using Azure Document Intelligence and vision models.
"""

import logging
from typing import Any

from .base_parser import BaseParser
from .utils.afr_client import AzureFormRecognizerClient
from .utils.vision_client import VisionExtractionClient
from .utils.image_cropping import (
    crop_and_save_images_from_figures,
    cleanup_cropped_images,
    get_temp_image_dir
)
from . import config

logger = logging.getLogger(__name__)


class PDFParser(BaseParser):
    """
    Parser for PDF documents.

    Uses Azure Document Intelligence to extract:
    - Text paragraphs with viewport coordinates
    - Tables in HTML format
    - Page dimensions and layout
    - Figures (charts, diagrams) with bounding boxes
    - Optional: Figure content via vision models (if enabled)
    - Optional: Section hierarchy (if enabled)
    """

    def __init__(self, file_content: bytes, filename: str, document_id: str):
        """
        Initialize PDF parser.

        Args:
            file_content: PDF file bytes
            filename: Original filename
            document_id: Unique document identifier
        """
        super().__init__(file_content, filename, document_id)
        self.afr_client = AzureFormRecognizerClient()
        self.vision_client = None

        # Initialize vision client if enabled
        if config.ENABLE_VISION_EXTRACTION:
            try:
                self.vision_client = VisionExtractionClient(enable_logging=True)
                logger.info("Vision extraction enabled for PDF parsing")
            except Exception as e:
                logger.warning(f"Failed to initialize vision client: {str(e)}. Vision extraction disabled.")
                self.vision_client = None

    async def parse(self) -> dict[str, Any]:
        """
        Parse PDF document into enriched JSON with optional vision extraction.

        Returns:
            dict: Enriched JSON with sections, page_info, enriched_metadata, metadata

        Raises:
            RuntimeError: If parsing fails
        """
        cropped_image_paths = []

        try:
            logger.info(f"Starting PDF parsing for: {self.filename}")

            # Step 1: Analyze document with Azure Document Intelligence
            afr_result = await self.afr_client.analyze_document(
                file_content=self.file_content,
                model_id="prebuilt-layout",
            )

            # Step 2: Extract sections, page info, and figures
            sections, page_info, figures = self.afr_client.extract_sections_from_result(
                result=afr_result,
                include_tables=True,
                include_figures=True,
            )

            logger.info(
                f"Extracted {len(sections)} sections and {len(figures)} figures from PDF"
            )

            # Step 3: Optional vision extraction for figures
            if self.vision_client and figures:
                vision_sections = await self._process_figures_with_vision(figures)
                if vision_sections:
                    sections.extend(vision_sections)
                    logger.info(f"Added {len(vision_sections)} vision-extracted sections")

            # Step 4: Optional LLM enrichment
            enriched_metadata = {}
            if sections:
                text_content = self._extract_text_from_sections(sections)
                enriched_metadata = await self._enrich_with_llm(text_content)

            # Step 5: Create enriched JSON structure
            enriched_json = self._create_enriched_json_structure(
                sections=sections,
                page_info=page_info,
                enriched_metadata=enriched_metadata,
                additional_metadata={
                    "total_pages": len(page_info),
                    "total_sections": len(sections),
                    "total_figures": len(figures),
                    "vision_extraction_enabled": config.ENABLE_VISION_EXTRACTION,
                },
            )

            logger.info(f"PDF parsing completed successfully for: {self.filename}")
            return enriched_json

        except Exception as e:
            logger.error(f"PDF parsing failed for {self.filename}: {str(e)}")
            raise RuntimeError(f"PDF parsing failed: {str(e)}")

        finally:
            # Cleanup cropped images
            if cropped_image_paths:
                cleanup_cropped_images(cropped_image_paths)

    async def _process_figures_with_vision(
        self, figures: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Process figures with vision extraction.

        Args:
            figures: List of figure metadata from Document Intelligence

        Returns:
            list: List of vision-extracted sections
        """
        if not figures:
            return []

        try:
            # Create temporary directory for cropped images
            temp_dir = get_temp_image_dir(self.document_id)

            # Crop images from PDF
            cropped_images = crop_and_save_images_from_figures(
                file_name=self.filename,
                document_bytes=self.file_content,
                figures=figures,
                file_id=self.document_id,
                output_dir=temp_dir,
                dpi=300  # High quality for vision processing
            )

            if not cropped_images:
                logger.warning("No images were cropped from figures")
                return []

            # Process images with vision API
            vision_results = await self.vision_client.process_multiple_images(
                image_data_list=cropped_images
            )

            # Convert to section format
            vision_sections = []
            for content, metadata in vision_results:
                if content:  # Only add if content was extracted
                    # Parse page number from metadata
                    page_number_str = metadata.get("page_number", "[1]")
                    page_number = int(page_number_str.strip("[]"))

                    # Get bounding regions
                    bounding_regions = metadata.get("bounding_regions", {})
                    viewport = []
                    if isinstance(bounding_regions, dict) and "polygon" in bounding_regions:
                        viewport = bounding_regions["polygon"]

                    vision_sections.append({
                        "content": content,
                        "type": "figure",
                        "viewport": viewport,
                        "page_number": page_number,
                        "metadata": {
                            "extraction_method": "vision",
                            "model": config.OPENAI_VISION_MODEL,
                            "caption": metadata.get("caption", ""),
                        }
                    })

            # Store image paths for cleanup
            self.cropped_image_paths = [img["image_path"] for img in cropped_images]

            return vision_sections

        except Exception as e:
            logger.error(f"Vision processing failed: {str(e)}")
            # Return empty list on failure - document can still be parsed without vision
            return []
