"""
Vision extraction client using LiteLLM for AI gateway functionality.

This module handles image content extraction from charts, diagrams, and figures
using OpenAI Vision API (with fallback support for other providers via LiteLLM).

LiteLLM provides:
- Unified API interface across multiple providers
- Built-in logging and cost tracking
- Automatic retries and error handling
- Guardrails for content safety and PII masking
"""

import base64
import io
import logging
from typing import Any, Optional
from pathlib import Path
from PIL import Image

import litellm
from litellm import acompletion
from litellm.integrations.custom_logger import CustomLogger

from .. import config

logger = logging.getLogger(__name__)


class VisionCostLogger(CustomLogger):
    """
    Custom logger for tracking vision API costs via LiteLLM.

    This integrates with LiteLLM's callback system to track:
    - Token usage per request
    - Estimated costs
    - Request/response metadata
    """

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Log successful vision API calls with cost tracking."""
        try:
            # Extract usage information
            usage = response_obj.usage if hasattr(response_obj, 'usage') else None
            if usage:
                prompt_tokens = getattr(usage, 'prompt_tokens', 0)
                completion_tokens = getattr(usage, 'completion_tokens', 0)
                total_tokens = getattr(usage, 'total_tokens', 0)

                # Log cost information
                logger.info(
                    f"Vision API call completed - "
                    f"Model: {kwargs.get('model', 'unknown')}, "
                    f"Prompt tokens: {prompt_tokens}, "
                    f"Completion tokens: {completion_tokens}, "
                    f"Total tokens: {total_tokens}, "
                    f"Latency: {(end_time - start_time):.2f}s"
                )
        except Exception as e:
            logger.warning(f"Failed to log vision API success: {str(e)}")

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """Log failed vision API calls for debugging."""
        logger.error(
            f"Vision API call failed - "
            f"Model: {kwargs.get('model', 'unknown')}, "
            f"Error: {str(response_obj)}, "
            f"Latency: {(end_time - start_time):.2f}s"
        )


class VisionExtractionClient:
    """
    Client for extracting content from images using vision models via LiteLLM.

    Features:
    - Automatic base64 encoding of images
    - Streaming support for large responses
    - Cost tracking and logging
    - Configurable models and providers
    - Built-in retry logic via LiteLLM
    """

    def __init__(self, enable_logging: bool = True):
        """
        Initialize vision extraction client.

        Args:
            enable_logging: Enable cost and usage logging via LiteLLM callbacks
        """
        if not config.OPENAI_API_KEY:
            raise ValueError(
                "OpenAI API key not configured. "
                "Please set OPENAI_API_KEY environment variable."
            )

        # Configure LiteLLM
        litellm.set_verbose = False  # Disable verbose logging (we use custom logger)

        # Add custom logger for cost tracking
        if enable_logging:
            litellm.callbacks = [VisionCostLogger()]

        # Set default model from config
        self.default_model = config.OPENAI_VISION_MODEL
        self.max_tokens = config.OPENAI_VISION_MAX_TOKENS
        self.timeout = config.OPENAI_VISION_TIMEOUT

        logger.info(
            f"Vision extraction client initialized - "
            f"Model: {self.default_model}, "
            f"Max tokens: {self.max_tokens}"
        )

    def _encode_image(self, img: Image.Image, file_identifier: str) -> str:
        """
        Encode PIL Image to base64 for vision API.

        Args:
            img: PIL Image object
            file_identifier: Path to identify file extension (for format detection)

        Returns:
            str: Base64 encoded image
        """
        buffer = io.BytesIO()
        file_extension = Path(file_identifier).suffix.lower()

        # Convert JPEG to RGB, save as PNG for better quality
        if file_extension in ['.jpg', '.jpeg']:
            img = img.convert('RGB')
            img_format = 'PNG'
        else:
            img_format = 'PNG'

        img.save(buffer, format=img_format)
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode('utf-8')

    async def extract_from_image(
        self,
        image_path: str,
        prompt: Optional[str] = None,
        model: Optional[str] = None,
        stream: bool = True
    ) -> str:
        """
        Extract content from image file using vision API.

        Args:
            image_path: Path to image file
            prompt: Custom prompt (uses default if not provided)
            model: Model to use (uses default if not provided)
            stream: Enable streaming for faster response

        Returns:
            str: Extracted content from image

        Raises:
            RuntimeError: If vision extraction fails
        """
        try:
            # Load and encode image
            with Image.open(image_path) as img:
                base64_image = self._encode_image(img, image_path)

            # Use provided prompt or default
            if prompt is None:
                prompt = (
                    "Extract all the details only for the charts and infographs present in the image. "
                    "Don't miss out on any details for charts or infographs present. "
                    "Provide the output in JSON format."
                )

            # Extract content
            content = await self._call_vision_api(
                base64_image=base64_image,
                prompt=prompt,
                model=model or self.default_model,
                stream=stream
            )

            return content

        except Exception as e:
            logger.error(f"Failed to extract from image {image_path}: {str(e)}")
            raise RuntimeError(f"Vision extraction failed: {str(e)}")

    async def extract_from_base64(
        self,
        base64_image: str,
        prompt: Optional[str] = None,
        model: Optional[str] = None,
        stream: bool = True
    ) -> str:
        """
        Extract content from base64-encoded image.

        Args:
            base64_image: Base64 encoded image
            prompt: Custom prompt (uses default if not provided)
            model: Model to use (uses default if not provided)
            stream: Enable streaming for faster response

        Returns:
            str: Extracted content from image

        Raises:
            RuntimeError: If vision extraction fails
        """
        try:
            # Use provided prompt or default
            if prompt is None:
                prompt = (
                    "Extract all the details only for the charts and infographs present in the image. "
                    "Don't miss out on any details for charts or infographs present. "
                    "Provide the output in JSON format."
                )

            # Extract content
            content = await self._call_vision_api(
                base64_image=base64_image,
                prompt=prompt,
                model=model or self.default_model,
                stream=stream
            )

            return content

        except Exception as e:
            logger.error(f"Failed to extract from base64 image: {str(e)}")
            raise RuntimeError(f"Vision extraction failed: {str(e)}")

    async def _call_vision_api(
        self,
        base64_image: str,
        prompt: str,
        model: str,
        stream: bool = True
    ) -> str:
        """
        Call vision API via LiteLLM with retry logic.

        Args:
            base64_image: Base64 encoded image
            prompt: Extraction prompt
            model: Model to use
            stream: Enable streaming

        Returns:
            str: Extracted text content
        """
        # Build messages
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "high"  # High detail for better extraction
                        },
                    },
                ],
            }
        ]

        # LiteLLM parameters
        params = {
            "model": model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "stream": stream,
        }

        # Add seed for reproducibility (OpenAI only)
        if "gpt" in model.lower():
            params["seed"] = 25

        try:
            if stream:
                # Stream response
                buffer = ""
                response = await acompletion(**params)

                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content is not None:
                        current_chunk = chunk.choices[0].delta.content
                        buffer += current_chunk

                return buffer
            else:
                # Non-streaming response
                response = await acompletion(**params)
                return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Vision API call failed: {str(e)}")
            raise RuntimeError(f"Vision API call failed: {str(e)}")

    async def process_multiple_images(
        self,
        image_data_list: list[dict[str, Any]],
        prompt: Optional[str] = None,
        model: Optional[str] = None
    ) -> list[tuple[str, dict[str, Any]]]:
        """
        Process multiple images in batch.

        Args:
            image_data_list: List of dicts with 'image_path' and metadata
            prompt: Custom prompt (uses default if not provided)
            model: Model to use (uses default if not provided)

        Returns:
            list: List of (extracted_content, metadata) tuples
        """
        results = []

        for image_data in image_data_list:
            try:
                # Extract content
                content = await self.extract_from_image(
                    image_path=image_data['image_path'],
                    prompt=prompt,
                    model=model
                )

                # Format metadata
                metadata = {
                    "page_number": f"[{image_data.get('page_number', 1)}]",
                    "bounding_regions": image_data.get('bounding_regions', {}),
                    "file_name": image_data.get('file_name', ''),
                    "file_id": image_data.get('file_uid', ''),
                    "image_path": image_data['image_path'],
                    "page_info": f"Page {image_data.get('page_number', 1)}",
                    "spans": image_data.get("spans", [])
                }

                results.append((content, metadata))

            except Exception as e:
                logger.error(f"Failed to process image {image_data.get('image_path', 'unknown')}: {str(e)}")
                # Return empty result for failed images
                results.append(("", image_data))

        return results
