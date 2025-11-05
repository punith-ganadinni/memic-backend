from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import Optional, Literal
import os


class Settings(BaseSettings):
    """Application configuration settings."""
    
    # Environment settings
    app_env: Literal["dev", "uat", "prod"] = Field(default="dev", env="APP_ENV")
    
    # Database settings
    database_url: str = Field(default="postgresql+psycopg://punithg@localhost:5432/memic_dev", env="DATABASE_URL")
    
    # Application settings
    app_name: str = Field(default="Memic Backend", env="APP_NAME")
    app_version: str = Field(default="1.0.0", env="APP_VERSION")
    debug: bool = Field(default=False, env="DEBUG")
    
    # Server settings
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")
    
    # API Keys and Secrets
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    jwt_secret_key: Optional[str] = Field(default=None, env="JWT_SECRET_KEY")
    encryption_key: Optional[str] = Field(default=None, env="ENCRYPTION_KEY")
    
    # JWT Settings
    jwt_algorithm: str = Field(default="HS256", env="JWT_ALGORITHM")
    jwt_expiry_hours: int = Field(default=24, env="JWT_EXPIRY_HOURS")
    
    # Third-party service keys
    stripe_secret_key: Optional[str] = Field(default=None, env="STRIPE_SECRET_KEY")
    sendgrid_api_key: Optional[str] = Field(default=None, env="SENDGRID_API_KEY")
    
    # Supabase Storage Configuration
    supabase_url: Optional[str] = Field(default=None, env="SUPABASE_URL")
    supabase_key: Optional[str] = Field(default=None, env="SUPABASE_KEY")
    supabase_bucket_name: str = Field(default="memic-documents", env="SUPABASE_BUCKET_NAME")
    
    # Azure Blob Storage Configuration (Alternative)
    azure_storage_connection_string: Optional[str] = Field(default=None, env="AZURE_STORAGE_CONNECTION_STRING")
    azure_storage_container_name: str = Field(default="memic-documents", env="AZURE_STORAGE_CONTAINER_NAME")
    
    # File Conversion Configuration
    libreoffice_path: str = Field(
        default="/Applications/LibreOffice.app/Contents/MacOS/soffice",
        env="LIBREOFFICE_PATH",
        description="Path to LibreOffice soffice executable for file conversion"
    )

    # Azure Form Recognizer / Document Intelligence Configuration
    azure_afr_endpoint: Optional[str] = Field(default=None, env="AZURE_AFR_ENDPOINT")
    azure_afr_api_key: Optional[str] = Field(default=None, env="AZURE_AFR_API_KEY")

    # Parsing Service Configuration
    parsing_service: Literal["azure_form_recognizer"] = Field(default="azure_form_recognizer", env="PARSING_SERVICE")
    
    # Azure Form Recognizer Timeout and Retry Settings
    afr_polling_timeout: int = Field(default=120, env="AFR_POLLING_TIMEOUT")
    afr_retry_attempts: int = Field(default=3, env="AFR_RETRY_ATTEMPTS")
    afr_retry_delay: int = Field(default=2, env="AFR_RETRY_DELAY")
    
    # Parsing Feature Flags (for cost control)
    enable_llm_enrichment: bool = Field(default=False, env="ENABLE_LLM_ENRICHMENT")
    enable_advanced_table_extraction: bool = Field(default=False, env="ENABLE_ADVANCED_TABLE_EXTRACTION")
    enable_section_hierarchy: bool = Field(default=False, env="ENABLE_SECTION_HIERARCHY")
    enable_vision_extraction: bool = Field(default=False, env="ENABLE_VISION_EXTRACTION")

    # Vision Extraction Configuration
    openai_vision_model: str = Field(default="gpt-4o", env="OPENAI_VISION_MODEL")
    openai_vision_timeout: int = Field(default=100, env="OPENAI_VISION_TIMEOUT")
    openai_vision_max_tokens: int = Field(default=3000, env="OPENAI_VISION_MAX_TOKENS")
    
    # Pinecone Configuration
    pinecone_api_key: Optional[str] = Field(default=None, env="PINECONE_API_KEY")
    pinecone_environment: str = Field(default="gcp-starter", env="PINECONE_ENVIRONMENT")
    pinecone_index_name: str = Field(default="memic-rag", env="PINECONE_INDEX_NAME")
    
    # Redis Configuration
    redis_url: str = Field(default="redis://localhost:6379/0", env="REDIS_URL")
    
    # Celery Configuration
    celery_broker_url: str = Field(default="redis://localhost:6379/0", env="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/0", env="CELERY_RESULT_BACKEND")
    
    # RAG Processing Configuration
    chunk_size: int = Field(default=512, env="CHUNK_SIZE")
    chunk_overlap: int = Field(default=50, env="CHUNK_OVERLAP")
    embedding_model: str = Field(default="text-embedding-ada-002", env="EMBEDDING_MODEL")
    embedding_dimension: int = Field(default=1536, env="EMBEDDING_DIMENSION")
    
    # Environment-specific settings
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    cors_origins: str = Field(default="*", env="CORS_ORIGINS")
    
    @field_validator("app_env")
    @classmethod
    def validate_environment(cls, v):
        """Validate environment is one of the allowed values."""
        allowed_envs = ["dev", "uat", "prod"]
        if v not in allowed_envs:
            raise ValueError(f"APP_ENV must be one of {allowed_envs}")
        return v
    
    @field_validator("openai_api_key", "jwt_secret_key", "encryption_key")
    @classmethod
    def validate_required_secrets(cls, v, info):
        """Validate required secrets are present based on environment."""
        # Get the current environment from the model
        env = os.getenv("APP_ENV", "dev")
        
        # In production environments, these secrets are required
        if env in ["uat", "prod"] and not v:
            raise ValueError(f"{info.field_name} is required in {env} environment")
        
        return v
    
    def get_environment_file(self) -> str:
        """Get the appropriate environment file based on APP_ENV."""
        env_files = {
            "dev": ".env.dev",
            "uat": ".env.uat", 
            "prod": ".env.prod"
        }
        return env_files.get(self.app_env, ".env.dev")
    
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env == "prod"
    
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.app_env == "dev"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()

