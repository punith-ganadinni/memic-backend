"""
Setup Verification Script

This script verifies that all required services and configurations are in place
before running the parsing pipeline tests.

Usage:
    python tests/verify_setup.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env files
# Try to load environment-specific .env file first, then fallback to .env
try:
    from dotenv import load_dotenv
    
    app_env = os.getenv("APP_ENV", "dev")
    env_file = f".env.{app_env}"
    env_path = Path(__file__).parent.parent / env_file
    
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment variables from {env_file}")
    else:
        # Fallback to .env
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            print(f"Loaded environment variables from .env")
except ImportError:
    # python-dotenv not installed, will rely on environment variables being set
    pass


def print_header(text: str):
    """Print a formatted header"""
    print(f"\n{'='*80}")
    print(f"  {text}")
    print(f"{'='*80}\n")


def print_check(name: str, passed: bool, details: str = ""):
    """Print a check result"""
    icon = "✓" if passed else "✗"
    status = "PASS" if passed else "FAIL"
    print(f"[{icon}] {name:.<50} {status}")
    if details:
        print(f"    {details}")


def check_env_var(var_name: str) -> tuple[bool, str]:
    """Check if an environment variable is set"""
    value = os.getenv(var_name)
    if value:
        # Mask sensitive values
        if "KEY" in var_name or "SECRET" in var_name:
            display_value = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
        else:
            display_value = value
        return True, f"Set: {display_value}"
    return False, "Not set"


def check_file_exists(file_path: Path) -> tuple[bool, str]:
    """Check if a file exists"""
    if file_path.exists():
        size = file_path.stat().st_size
        return True, f"Found ({size:,} bytes)"
    return False, "Not found"


def check_service_running(service_name: str, check_command: str) -> tuple[bool, str]:
    """Check if a service is running"""
    import subprocess
    try:
        result = subprocess.run(
            check_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return True, "Running"
        return False, "Not running"
    except Exception as e:
        return False, f"Check failed: {str(e)}"


def check_azure_form_recognizer():
    """Check Azure Form Recognizer configuration"""
    print_header("Azure Form Recognizer Configuration")

    # Check via environment variables (direct)
    endpoint_ok, endpoint_details = check_env_var("AZURE_AFR_ENDPOINT")
    key_ok, key_details = check_env_var("AZURE_AFR_API_KEY")

    # Also check via config to verify config is reading correctly
    config_ok = False
    try:
        from app.config import settings
        config_endpoint = settings.azure_afr_endpoint
        config_key = settings.azure_afr_api_key
        
        if config_endpoint and config_key:
            config_ok = True
            if not endpoint_ok:
                # Config has it but env var check didn't - means .env was loaded by config
                endpoint_ok = True
                endpoint_details = f"Set via config: {config_endpoint[:30]}..."
            if not key_ok:
                key_ok = True
                key_details = "Set via config: ***"
    except Exception as e:
        # Config check failed, but that's ok - we'll rely on env var check
        pass

    print_check("AZURE_AFR_ENDPOINT", endpoint_ok, endpoint_details)
    print_check("AZURE_AFR_API_KEY", key_ok, key_details)

    if endpoint_ok and key_ok:
        print("\n✓ Azure Form Recognizer is configured!")
        print("  You can proceed with parsing tests.")
    else:
        print("\n✗ Azure Form Recognizer is NOT configured!")
        print("  Please follow AZURE_FORM_RECOGNIZER_SETUP.md to set it up.")
        print("  Required steps:")
        print("    1. Create Azure Form Recognizer resource in Azure Portal")
        print("    2. Copy Endpoint and API Key")
        print("    3. Add to .env file (or .env.dev/.env.uat/.env.prod):")
        print("       AZURE_AFR_ENDPOINT=https://your-resource.cognitiveservices.azure.com/")
        print("       AZURE_AFR_API_KEY=your_api_key_here")
        print("    4. Set APP_ENV if using environment-specific files:")
        print("       export APP_ENV=dev  # or uat, prod")

    return endpoint_ok and key_ok


def check_services():
    """Check required services"""
    print_header("Required Services")

    # Check Redis
    redis_ok, redis_details = check_service_running(
        "Redis",
        "redis-cli ping 2>/dev/null"
    )
    print_check("Redis", redis_ok, redis_details)

    # Check Celery worker
    celery_ok, celery_details = check_service_running(
        "Celery Worker",
        "ps aux | grep 'celery.*worker' | grep -v grep"
    )
    print_check("Celery Worker", celery_ok, celery_details)

    # Check FastAPI server
    import httpx
    try:
        response = httpx.get("http://localhost:8000/", timeout=5)
        fastapi_ok = response.status_code in [200, 404]  # 404 is ok, means server is running
        fastapi_details = f"Responding (HTTP {response.status_code})"
    except Exception as e:
        fastapi_ok = False
        fastapi_details = f"Not responding: {str(e)}"

    print_check("FastAPI Server", fastapi_ok, fastapi_details)

    if not redis_ok:
        print("\n  To start Redis:")
        print("    redis-server")

    if not celery_ok:
        print("\n  To start Celery worker:")
        print("    celery -A app.celery_app worker --loglevel=info -Q files,conversion,parsing,chunking,embedding")

    if not fastapi_ok:
        print("\n  To start FastAPI server:")
        print("    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")

    return redis_ok and celery_ok and fastapi_ok


def check_test_files():
    """Check test files availability"""
    print_header("Test Files")

    base_path = Path(__file__).parent.parent / "test_data"

    test_files = [
        base_path / "pdf" / "sample.pdf",
        base_path / "office" / "file_example_PPT_1MB.ppt",
        base_path / "office" / "file_example_XLSX_5000.xlsx",
    ]

    all_ok = True
    for file_path in test_files:
        ok, details = check_file_exists(file_path)
        print_check(f"{file_path.name}", ok, details)
        all_ok = all_ok and ok

    return all_ok


def check_python_dependencies():
    """Check required Python packages"""
    print_header("Python Dependencies")

    required_packages = [
        "httpx",
        "azure-ai-formrecognizer",
        "azure-storage-blob",
        "celery",
        "fastapi",
    ]

    all_ok = True
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
            print_check(package, True, "Installed")
        except ImportError:
            print_check(package, False, "Not installed")
            all_ok = False

    if not all_ok:
        print("\n  To install missing packages:")
        print("    pip install -r requirements.txt")

    return all_ok


def check_azure_storage():
    """Check Azure Blob Storage configuration"""
    print_header("Azure Blob Storage Configuration")

    connection_ok, connection_details = check_env_var("AZURE_STORAGE_CONNECTION_STRING")
    container_ok, container_details = check_env_var("AZURE_STORAGE_CONTAINER_NAME")

    print_check("AZURE_STORAGE_CONNECTION_STRING", connection_ok, connection_details)
    print_check("AZURE_STORAGE_CONTAINER_NAME", container_ok, container_details)

    return connection_ok and container_ok


def main():
    """Run all verification checks"""
    print_header("Memic Backend - Setup Verification")
    print("This script verifies that all required components are configured")
    print("and ready for testing the parsing pipeline.")

    # Run all checks
    checks = {
        "Azure Form Recognizer": check_azure_form_recognizer(),
        "Azure Blob Storage": check_azure_storage(),
        "Required Services": check_services(),
        "Test Files": check_test_files(),
        "Python Dependencies": check_python_dependencies(),
    }

    # Print summary
    print_header("Verification Summary")

    all_passed = all(checks.values())

    for check_name, passed in checks.items():
        icon = "✓" if passed else "✗"
        print(f"{icon} {check_name}")

    print()

    if all_passed:
        print("🎉 All checks passed! You're ready to run the parsing tests.")
        print()
        print("Next steps:")
        print("  1. Run the test script:")
        print("     python tests/test_parsing_pipeline.py")
        print()
        print("  2. Or follow the manual testing guide:")
        print("     See TESTING_GUIDE.md")
        return 0
    else:
        print("⚠️  Some checks failed. Please fix the issues above before proceeding.")
        print()
        print("For detailed setup instructions, see:")
        print("  - AZURE_FORM_RECOGNIZER_SETUP.md (for AFR setup)")
        print("  - TESTING_GUIDE.md (for testing guide)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
