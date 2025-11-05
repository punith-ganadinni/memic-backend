"""
Azure Document Intelligence client wrapper.

This module provides a clean interface to Azure Document Intelligence (upgraded from Form Recognizer)
with retry logic, error handling, and cost tracking.

Key differences from old SDK:
- Uses DocumentIntelligenceClient instead of DocumentAnalysisClient
- Supports figure extraction via result.figures (required for vision pipeline)
- Updated async patterns for better performance
"""

import asyncio
import logging
from typing import Any, Optional

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError

from .. import config

logger = logging.getLogger(__name__)


class AzureFormRecognizerClient:
    """
    Wrapper for Azure Document Intelligence with retry logic and error handling.

    Cost per 1000 pages (as of 2025):
    - Read model: ~$1.50
    - Layout model: ~$10.00
    - Prebuilt models: Varies by type

    We use the 'prebuilt-layout' model for comprehensive extraction including figures.
    """

    def __init__(self):
        """Initialize Azure Document Intelligence client."""
        if not config.AZURE_AFR_ENDPOINT or not config.AZURE_AFR_API_KEY:
            raise ValueError(
                "Azure Document Intelligence credentials not configured. "
                "Please set AZURE_AFR_ENDPOINT and AZURE_AFR_API_KEY"
            )

        self.endpoint = config.AZURE_AFR_ENDPOINT
        self.client = DocumentIntelligenceClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(config.AZURE_AFR_API_KEY),
        )

        logger.info(f"Azure Document Intelligence client initialized: {self.endpoint}")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def close(self):
        """Close the client connection."""
        if self.client:
            await self.client.close()

    async def analyze_document(
        self,
        file_content: bytes,
        model_id: str = "prebuilt-layout",
    ) -> Any:
        """
        Analyze document using Azure Document Intelligence.

        Args:
            file_content: Document bytes
            model_id: Model to use (default: prebuilt-layout)

        Returns:
            Analyzed document result with support for figures extraction

        Raises:
            RuntimeError: If analysis fails after retries
        """
        for attempt in range(config.AFR_RETRY_ATTEMPTS):
            try:
                logger.info(
                    f"Starting Document Intelligence analysis with model '{model_id}' "
                    f"(attempt {attempt + 1}/{config.AFR_RETRY_ATTEMPTS})"
                )

                # Begin analysis (async operation using new SDK)
                poller = await self.client.begin_analyze_document(
                    model_id=model_id,
                    body=file_content,
                    content_type="application/octet-stream",
                )

                # Wait for completion with timeout
                result = await asyncio.wait_for(
                    poller.result(),
                    timeout=config.AFR_POLLING_TIMEOUT,
                )

                logger.info(
                    f"Document Intelligence analysis completed successfully. "
                    f"Figures detected: {len(result.figures) if hasattr(result, 'figures') and result.figures else 0}"
                )
                return result

            except asyncio.TimeoutError:
                logger.error(
                    f"Document Intelligence analysis timeout after {config.AFR_POLLING_TIMEOUT}s "
                    f"(attempt {attempt + 1})"
                )
                if attempt < config.AFR_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(config.AFR_RETRY_DELAY * (attempt + 1))
                    continue
                raise RuntimeError("Document Intelligence analysis timed out after all retries")

            except HttpResponseError as e:
                logger.error(f"Document Intelligence HTTP error: {e.status_code} - {e.message}")
                if e.status_code == 429:  # Rate limit
                    if attempt < config.AFR_RETRY_ATTEMPTS - 1:
                        wait_time = config.AFR_RETRY_DELAY * (2 ** attempt)
                        logger.info(f"Rate limited, waiting {wait_time}s before retry")
                        await asyncio.sleep(wait_time)
                        continue
                raise RuntimeError(f"Document Intelligence HTTP error: {e.message}")

            except Exception as e:
                logger.error(f"Document Intelligence analysis failed: {str(e)}")
                if attempt < config.AFR_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(config.AFR_RETRY_DELAY)
                    continue
                raise RuntimeError(f"Document Intelligence analysis failed: {str(e)}")

        raise RuntimeError("Document Intelligence analysis failed after all retry attempts")

    def extract_sections_from_result(
        self, result: Any, include_tables: bool = True, include_figures: bool = True
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
        """
        Extract sections, page info, and figures from Document Intelligence result.

        Args:
            result: Document Intelligence analysis result
            include_tables: Whether to include table extraction
            include_figures: Whether to include figure metadata extraction

        Returns:
            tuple: (sections list, page_info dict, figures list)
        """
        sections = []
        page_info = {}
        figures = []

        # Extract page dimensions
        for page in result.pages:
            page_info[str(page.page_number)] = {
                "width": page.width,
                "height": page.height,
                "unit": page.unit,
                "angle": page.angle if hasattr(page, "angle") else 0,
            }

        # Extract paragraphs
        if hasattr(result, "paragraphs") and result.paragraphs:
            for para in result.paragraphs:
                section = self._create_section_from_paragraph(para)
                sections.append(section)

        # Extract tables (if enabled)
        if include_tables and hasattr(result, "tables") and result.tables:
            for table in result.tables:
                section = self._create_section_from_table(table)
                sections.append(section)

        # Extract figures metadata (if enabled) - NEW!
        if include_figures and hasattr(result, "figures") and result.figures:
            for figure in result.figures:
                figure_metadata = self._create_metadata_from_figure(figure)
                figures.append(figure_metadata)

        # Sort by page number and offset
        sections.sort(key=lambda x: (x.get("page_number", 0), x.get("offset", 0)))

        logger.info(
            f"Extracted {len(sections)} sections, {len(figures)} figures from {len(page_info)} pages"
        )

        return sections, page_info, figures

    def _create_section_from_paragraph(self, paragraph: Any) -> dict[str, Any]:
        """
        Create section dict from AFR paragraph.

        Args:
            paragraph: AFR paragraph object

        Returns:
            dict: Section with content, viewport, and metadata
        """
        # Extract bounding box if available
        viewport = []
        if hasattr(paragraph, "bounding_regions") and paragraph.bounding_regions:
            region = paragraph.bounding_regions[0]
            if hasattr(region, "polygon"):
                # Convert polygon to flat list [x1, y1, x2, y2, ...]
                viewport = [coord for point in region.polygon for coord in (point.x, point.y)]

        # Determine page number
        page_number = 1
        if hasattr(paragraph, "bounding_regions") and paragraph.bounding_regions:
            page_number = paragraph.bounding_regions[0].page_number

        return {
            "content": paragraph.content,
            "type": "paragraph",
            "viewport": viewport,
            "offset": paragraph.spans[0].offset if paragraph.spans else 0,
            "page_number": page_number,
            "role": getattr(paragraph, "role", None),  # Heading levels (title, sectionHeading, etc.)
        }

    def _create_section_from_table(self, table: Any) -> dict[str, Any]:
        """
        Create section dict from AFR table.

        Args:
            table: AFR table object

        Returns:
            dict: Section with HTML table content and metadata
        """
        # Extract bounding box if available
        viewport = []
        if hasattr(table, "bounding_regions") and table.bounding_regions:
            region = table.bounding_regions[0]
            if hasattr(region, "polygon"):
                viewport = [coord for point in region.polygon for coord in (point.x, point.y)]

        # Determine page number
        page_number = 1
        if hasattr(table, "bounding_regions") and table.bounding_regions:
            page_number = table.bounding_regions[0].page_number

        # Convert table to HTML
        html_content = self._table_to_html(table)

        return {
            "content": html_content,
            "type": "table",
            "viewport": viewport,
            "offset": table.spans[0].offset if table.spans else 0,
            "page_number": page_number,
            "row_count": table.row_count,
            "column_count": table.column_count,
        }

    def _table_to_html(self, table: Any) -> str:
        """
        Convert AFR table to HTML format.

        Args:
            table: AFR table object

        Returns:
            str: HTML table string
        """
        html_rows = [[] for _ in range(table.row_count)]

        for cell in table.cells:
            row_idx = cell.row_index
            tag = "th" if cell.kind == "columnHeader" else "td"

            cell_html = f"<{tag}>{cell.content}</{tag}>"

            # Handle colspan and rowspan
            if cell.column_span and cell.column_span > 1:
                cell_html = f"<{tag} colspan='{cell.column_span}'>{cell.content}</{tag}>"
            if cell.row_span and cell.row_span > 1:
                cell_html = f"<{tag} rowspan='{cell.row_span}'>{cell.content}</{tag}>"

            html_rows[row_idx].append(cell_html)

        # Build HTML
        rows_html = "\n".join(
            f"  <tr>{''.join(cells)}</tr>" for cells in html_rows if cells
        )

        return f"<table>\n{rows_html}\n</table>"

    def _create_metadata_from_figure(self, figure: Any) -> dict[str, Any]:
        """
        Create metadata dict from Document Intelligence figure.

        Args:
            figure: Document Intelligence figure object

        Returns:
            dict: Figure metadata with bounding regions for image cropping
        """
        # Extract bounding regions (can have multiple regions if figure spans multiple areas)
        bounding_regions = []
        if hasattr(figure, "bounding_regions") and figure.bounding_regions:
            for region in figure.bounding_regions:
                region_dict = {
                    "page_number": region.page_number,
                    "polygon": []
                }
                if hasattr(region, "polygon") and region.polygon:
                    # Convert polygon to flat list [x1, y1, x2, y2, ...]
                    region_dict["polygon"] = [coord for point in region.polygon for coord in (point.x, point.y)]
                bounding_regions.append(region_dict)

        # Extract caption if available
        caption = ""
        if hasattr(figure, "caption") and figure.caption:
            caption = figure.caption.content if hasattr(figure.caption, "content") else str(figure.caption)

        # Extract spans for offset tracking
        spans = []
        if hasattr(figure, "spans") and figure.spans:
            for span in figure.spans:
                spans.append({
                    "offset": span.offset,
                    "length": span.length
                })

        return {
            "bounding_regions": bounding_regions,
            "caption": caption,
            "spans": spans,
            "id": getattr(figure, "id", None),
        }
