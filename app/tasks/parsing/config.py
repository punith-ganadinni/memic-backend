"""
Configuration for parsing module.

This module manages all configuration for document parsing with feature flags
for cost control in a B2B environment.

This module imports settings from the main app.config to ensure centralized
configuration management.
"""

from typing import Literal
from app.config import settings

# Parsing Service Selection
# Cost: Azure Form Recognizer ~$1.50 per 1000 pages
# Future: Support for LlamaParse, AWS Textract, etc.
PARSING_SERVICE: Literal["azure_form_recognizer"] = settings.parsing_service

# Feature Flags for Cost Control
# Each flag controls a feature that incurs additional costs

# LLM Enrichment: Uses OpenAI to extract metadata (document type, summary, tags)
# Cost: ~$0.002 per document with gpt-4o-mini
# When disabled: Returns empty headers dict
ENABLE_LLM_ENRICHMENT: bool = settings.enable_llm_enrichment

# Advanced Table Extraction: Uses premium AFR features for complex tables
# Cost: May incur additional AFR costs
# When disabled: Uses standard table extraction
ENABLE_ADVANCED_TABLE_EXTRACTION: bool = settings.enable_advanced_table_extraction

# Section Hierarchy Extraction: Extracts document structure (headings, levels)
# Cost: Additional processing time and AFR API calls
# When disabled: Returns flat section list
ENABLE_SECTION_HIERARCHY: bool = settings.enable_section_hierarchy

# Vision Extraction: Extracts content from charts/diagrams using vision models
# Cost: ~$0.01-0.03 per chart/diagram (varies by complexity)
# When disabled: Figures are skipped (no additional cost)
ENABLE_VISION_EXTRACTION: bool = settings.enable_vision_extraction

# Azure Form Recognizer Configuration
AZURE_AFR_ENDPOINT: str = settings.azure_afr_endpoint or ""
AZURE_AFR_API_KEY: str = settings.azure_afr_api_key or ""

# LLM Configuration (for enrichment)
OPENAI_API_KEY: str = settings.openai_api_key or ""
OPENAI_MODEL: str = "gpt-4o-mini"  # Cost-effective choice (can be added to main config if needed)

# Vision API Configuration (for chart/diagram extraction)
OPENAI_VISION_MODEL: str = settings.openai_vision_model
OPENAI_VISION_TIMEOUT: int = settings.openai_vision_timeout
OPENAI_VISION_MAX_TOKENS: int = settings.openai_vision_max_tokens

# Parsing Timeouts (in seconds)
AFR_POLLING_TIMEOUT: int = settings.afr_polling_timeout
AFR_RETRY_ATTEMPTS: int = settings.afr_retry_attempts
AFR_RETRY_DELAY: int = settings.afr_retry_delay


def validate_config() -> dict[str, bool]:
    """
    Validate configuration and return status of required services.

    Returns:
        dict: Status of each service configuration
    """
    validation_status = {
        "azure_document_intelligence": bool(AZURE_AFR_ENDPOINT and AZURE_AFR_API_KEY),
        "llm_enrichment": bool(OPENAI_API_KEY) if ENABLE_LLM_ENRICHMENT else True,
        "vision_extraction": bool(OPENAI_API_KEY) if ENABLE_VISION_EXTRACTION else True,
    }

    return validation_status


def get_enabled_features() -> list[str]:
    """
    Get list of enabled features for logging/monitoring.

    Returns:
        list: Names of enabled features
    """
    features = []

    if ENABLE_LLM_ENRICHMENT:
        features.append("llm_enrichment")
    if ENABLE_ADVANCED_TABLE_EXTRACTION:
        features.append("advanced_table_extraction")
    if ENABLE_SECTION_HIERARCHY:
        features.append("section_hierarchy")
    if ENABLE_VISION_EXTRACTION:
        features.append("vision_extraction")

    return features
