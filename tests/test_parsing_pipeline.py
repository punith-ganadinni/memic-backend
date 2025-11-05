"""
End-to-End Test Script for File Parsing Pipeline

This script tests the complete file upload and parsing pipeline using the API endpoints.
It uploads test files, monitors the parsing process, and validates the results.

Usage:
    python tests/test_parsing_pipeline.py

Requirements:
    - FastAPI server running (default: http://localhost:8000)
    - Celery worker running
    - Azure Form Recognizer configured
    - Valid project_id (will be created if needed)
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
import httpx
import json
from datetime import datetime

# Add parent directory to path for imports
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

# Verify Azure Form Recognizer configuration
try:
    from app.config import settings
    if not settings.azure_afr_endpoint or not settings.azure_afr_api_key:
        print("WARNING: Azure Form Recognizer not configured!")
        print("Please set AZURE_AFR_ENDPOINT and AZURE_AFR_API_KEY in your .env file")
    else:
        print(f"Azure Form Recognizer configured: {settings.azure_afr_endpoint[:30]}...")
except Exception as e:
    print(f"WARNING: Could not verify config: {e}")


class ParsingPipelineTest:
    """Test harness for the file parsing pipeline"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.client = httpx.Client(timeout=30.0)
        self.async_client = None
        self.project_id: Optional[str] = None
        self.org_id: Optional[str] = None
        self.access_token: Optional[str] = None
        self.test_results: List[Dict] = []

    async def __aenter__(self):
        self.async_client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.async_client:
            await self.async_client.aclose()
        self.client.close()

    def print_header(self, text: str):
        """Print a formatted header"""
        print(f"\n{'='*80}")
        print(f"  {text}")
        print(f"{'='*80}\n")

    def print_step(self, step: str):
        """Print a test step"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {step}")

    def print_success(self, message: str):
        """Print a success message"""
        print(f"  ✓ {message}")

    def print_error(self, message: str):
        """Print an error message"""
        print(f"  ✗ {message}")

    def print_info(self, message: str):
        """Print an info message"""
        print(f"  ℹ {message}")

    async def authenticate(self, email: str, password: str) -> bool:
        """Authenticate and get access token"""
        self.print_step(f"Authenticating as {email}...")

        try:
            login_data = {
                "email": email,
                "password": password
            }

            response = await self.async_client.post(
                f"{self.base_url}/api/v1/auth/login",
                json=login_data
            )

            if response.status_code != 200:
                self.print_error(f"Login failed: {response.status_code}")
                self.print_error(f"Response: {response.text}")
                return False

            token_data = response.json()
            self.access_token = token_data.get("access_token")
            
            if not self.access_token:
                self.print_error("No access token in response")
                return False

            self.print_success("Authentication successful")
            return True

        except Exception as e:
            self.print_error(f"Authentication failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authorization headers"""
        if not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}

    async def setup_project(self) -> bool:
        """Get existing organization and project"""
        self.print_step("Getting existing organization and project...")

        try:
            # Get user's organizations
            headers = self.get_auth_headers()
            orgs_response = await self.async_client.get(
                f"{self.base_url}/api/v1/organizations/",
                headers=headers
            )

            if orgs_response.status_code != 200:
                self.print_error(f"Failed to get organizations: {orgs_response.status_code}")
                self.print_error(f"Response: {orgs_response.text}")
                return False

            orgs = orgs_response.json()
            if not orgs:
                self.print_error("No organizations found. Please create an organization first.")
                return False

            # Use first organization
            org = orgs[0]
            self.org_id = str(org["id"])
            self.print_success(f"Using organization: {org['name']} ({self.org_id})")

            # Get projects in this organization
            projects_response = await self.async_client.get(
                f"{self.base_url}/api/v1/organizations/{self.org_id}/projects/",
                headers=headers
            )

            if projects_response.status_code != 200:
                self.print_error(f"Failed to get projects: {projects_response.status_code}")
                self.print_error(f"Response: {projects_response.text}")
                return False

            projects = projects_response.json()
            if not projects:
                self.print_error("No projects found. Please create a project first.")
                return False

            # Use first project
            project = projects[0]
            self.project_id = str(project["id"])
            self.print_success(f"Using project: {project['name']} ({self.project_id})")

            return True

        except Exception as e:
            self.print_error(f"Failed to setup project: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    async def upload_file_via_presigned_url(self, file_path: Path) -> Optional[str]:
        """
        Upload a file using the presigned URL flow

        Returns:
            file_id if successful, None otherwise
        """
        self.print_step(f"Uploading file: {file_path.name}")

        try:
            # Step 1: Initialize upload
            file_size = file_path.stat().st_size
            init_payload = {
                "file_name": file_path.name,
                "file_size": file_size,
                "content_type": self._get_content_type(file_path)
            }

            self.print_info(f"Initializing upload (size: {file_size} bytes)...")
            headers = self.get_auth_headers()
            headers["X-Org-ID"] = self.org_id
            
            init_response = await self.async_client.post(
                f"{self.base_url}/api/v1/projects/{self.project_id}/files/init",
                json=init_payload,
                headers=headers
            )

            if init_response.status_code != 200:
                self.print_error(f"Failed to initialize upload: {init_response.status_code}")
                self.print_error(f"Response: {init_response.text}")
                return None

            init_data = init_response.json()
            file_id = init_data.get("file_id")
            presigned_url = init_data.get("upload_url")

            self.print_success(f"Upload initialized: file_id={file_id}")

            # Step 2: Upload to presigned URL
            self.print_info("Uploading file to Azure Blob Storage...")
            with open(file_path, 'rb') as f:
                file_content = f.read()

                # Upload to Azure Blob (presigned URL)
                upload_response = await self.async_client.put(
                    presigned_url,
                    content=file_content,
                    headers={
                        "x-ms-blob-type": "BlockBlob",
                        "Content-Type": self._get_content_type(file_path)
                    }
                )

                if upload_response.status_code not in [200, 201]:
                    self.print_error(f"Failed to upload to blob storage: {upload_response.status_code}")
                    return None

            self.print_success("File uploaded to blob storage")

            # Step 3: Confirm upload and trigger pipeline
            self.print_info("Confirming upload and triggering pipeline...")
            headers = self.get_auth_headers()
            headers["X-Org-ID"] = self.org_id
            
            confirm_response = await self.async_client.post(
                f"{self.base_url}/api/v1/projects/{self.project_id}/files/{file_id}/confirm",
                headers=headers
            )

            if confirm_response.status_code != 200:
                self.print_error(f"Failed to confirm upload: {confirm_response.status_code}")
                self.print_error(f"Response: {confirm_response.text}")
                return None

            self.print_success("Upload confirmed, pipeline started")
            return file_id

        except Exception as e:
            self.print_error(f"Upload failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    async def monitor_file_status(self, file_id: str, timeout: int = 300) -> Dict:
        """
        Monitor file processing status until completion or failure

        Args:
            file_id: The file ID to monitor
            timeout: Maximum time to wait in seconds

        Returns:
            Dict with final status and metadata
        """
        self.print_step(f"Monitoring file status: {file_id}")

        start_time = time.time()
        last_status = None

        while time.time() - start_time < timeout:
            try:
                headers = self.get_auth_headers()
                headers["X-Org-ID"] = self.org_id
                
                response = await self.async_client.get(
                    f"{self.base_url}/api/v1/projects/{self.project_id}/files/{file_id}",
                    headers=headers
                )

                if response.status_code != 200:
                    self.print_error(f"Failed to get file status: {response.status_code}")
                    return {"status": "error", "error": "API error"}

                data = response.json()
                current_status = data.get("status")

                # Print status change
                if current_status != last_status:
                    self.print_info(f"Status: {current_status}")
                    last_status = current_status

                # Check for terminal states
                # Note: Status can be "parsing_complete" when parsing finishes
                # or "completed" when full pipeline finishes
                if current_status in ["completed", "parsing_complete", "parsing_completed"]:
                    self.print_success(f"Processing completed successfully! (Status: {current_status})")
                    return data

                if current_status in ["failed", "error", "parsing_failed", "conversion_failed"]:
                    error_msg = data.get("error_message", "Unknown error")
                    self.print_error(f"Processing failed: {error_msg}")
                    return data
                
                # Check intermediate states
                if current_status == "conversion_complete":
                    self.print_info("Conversion completed, parsing in progress...")
                elif current_status == "parsing_started":
                    self.print_info("Parsing started...")
                elif current_status == "conversion_started":
                    self.print_info("Conversion started...")

                # Wait before next poll
                await asyncio.sleep(2)

            except Exception as e:
                self.print_error(f"Error monitoring status: {str(e)}")
                return {"status": "error", "error": str(e)}

        self.print_error(f"Timeout after {timeout} seconds")
        return {"status": "timeout", "last_status": last_status}

    async def validate_parsing_output(self, file_id: str) -> Dict:
        """
        Validate the enriched JSON output from parsing and verify it's in blob storage

        Returns:
            Dict with validation results
        """
        self.print_step(f"Validating parsing output for {file_id}")

        try:
            # Get file details to find enriched JSON URL
            headers = self.get_auth_headers()
            headers["X-Org-ID"] = self.org_id
            
            response = await self.async_client.get(
                f"{self.base_url}/api/v1/projects/{self.project_id}/files/{file_id}",
                headers=headers
            )

            if response.status_code != 200:
                return {"valid": False, "error": "Failed to get file details"}

            file_data = response.json()
            enriched_json_url = file_data.get("enriched_json_url")
            enriched_file_path = file_data.get("enriched_file_path")

            if not enriched_json_url:
                return {"valid": False, "error": "No enriched JSON URL found in file record"}

            self.print_success(f"Found enriched JSON URL: {enriched_json_url}")
            if enriched_file_path:
                self.print_info(f"Enriched JSON blob path: {enriched_file_path}")

            # Download enriched JSON from blob storage
            self.print_info("Downloading enriched JSON from blob storage...")
            json_response = await self.async_client.get(enriched_json_url)
            if json_response.status_code != 200:
                return {"valid": False, "error": f"Failed to download enriched JSON: HTTP {json_response.status_code}"}

            enriched_data = json_response.json()
            json_size = len(json_response.content)
            self.print_success(f"Downloaded enriched JSON ({json_size:,} bytes)")

            # Validate structure
            validation_results = {
                "valid": True,
                "checks": {},
                "blob_storage": {
                    "url": enriched_json_url,
                    "path": enriched_file_path,
                    "size_bytes": json_size
                }
            }

            # Check required top-level keys
            required_keys = ["sections", "metadata"]
            for key in required_keys:
                exists = key in enriched_data
                validation_results["checks"][f"has_{key}"] = exists
                if not exists:
                    validation_results["valid"] = False
                    self.print_error(f"Missing required key: {key}")
                else:
                    self.print_success(f"Found key: {key}")

            # Validate sections
            if "sections" in enriched_data:
                sections = enriched_data["sections"]
                validation_results["checks"]["section_count"] = len(sections)
                self.print_info(f"Found {len(sections)} sections")

                # Check first section structure
                if sections:
                    first_section = sections[0]
                    section_keys = ["content", "type"]
                    for key in section_keys:
                        exists = key in first_section
                        validation_results["checks"][f"section_has_{key}"] = exists
                        if exists:
                            value = first_section.get(key)
                            display_value = value[:50] + "..." if isinstance(value, str) and len(value) > 50 else value
                            self.print_success(f"Section has {key}: {display_value}")

            # Validate metadata
            if "metadata" in enriched_data:
                metadata = enriched_data["metadata"]
                parser_name = metadata.get("parser")
                parsing_service = metadata.get("parsing_service")
                
                self.print_success(f"Parser used: {parser_name}")
                self.print_success(f"Service: {parsing_service}")
                
                # Verify Azure Document Intelligence was used
                if parsing_service == "azure_form_recognizer":
                    self.print_success("Confirmed: Azure Document Intelligence (Form Recognizer) was used")
                else:
                    self.print_error(f"Unexpected parsing service: {parsing_service}")
                
                validation_results["checks"]["parser"] = parser_name
                validation_results["checks"]["parsing_service"] = parsing_service
                validation_results["checks"]["total_sections"] = metadata.get("total_sections", 0)

            # Validate page_info if present
            if "page_info" in enriched_data:
                page_info = enriched_data["page_info"]
                page_count = len(page_info)
                validation_results["checks"]["page_count"] = page_count
                self.print_info(f"Found page info for {page_count} pages")

            # Validate enriched_metadata structure
            if "enriched_metadata" in enriched_data:
                enriched_metadata = enriched_data["enriched_metadata"]
                if enriched_metadata:
                    self.print_info("Found enriched metadata (LLM-extracted)")
                    validation_results["checks"]["has_enriched_metadata"] = True
                else:
                    self.print_info("No enriched metadata (LLM enrichment may be disabled)")

            return validation_results

        except Exception as e:
            self.print_error(f"Validation failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"valid": False, "error": str(e)}

    async def test_file(self, file_path: Path) -> Dict:
        """
        Test a single file through the complete pipeline

        Returns:
            Dict with test results
        """
        self.print_header(f"Testing: {file_path.name}")

        test_result = {
            "file_name": file_path.name,
            "file_size": file_path.stat().st_size,
            "start_time": datetime.now().isoformat(),
            "success": False
        }

        # Upload file
        file_id = await self.upload_file_via_presigned_url(file_path)
        if not file_id:
            test_result["error"] = "Upload failed"
            test_result["end_time"] = datetime.now().isoformat()
            return test_result

        test_result["file_id"] = file_id

        # Monitor processing (waits for conversion -> parsing -> completion)
        final_status = await self.monitor_file_status(file_id, timeout=600)  # 10 min timeout for conversion + parsing
        test_result["final_status"] = final_status.get("status")

        # Accept both "completed" and "parsing_complete" as success
        # (parsing_complete means parsing finished, which is what we're testing)
        acceptable_statuses = ["completed", "parsing_complete", "parsing_completed"]
        if final_status.get("status") not in acceptable_statuses:
            test_result["error"] = final_status.get("error", f"Processing did not complete. Status: {final_status.get('status')}")
            test_result["end_time"] = datetime.now().isoformat()
            return test_result

        # Validate output
        validation = await self.validate_parsing_output(file_id)
        test_result["validation"] = validation
        test_result["success"] = validation.get("valid", False)
        test_result["end_time"] = datetime.now().isoformat()

        return test_result

    def _get_content_type(self, file_path: Path) -> str:
        """Get content type based on file extension"""
        extension = file_path.suffix.lower()
        content_types = {
            '.pdf': 'application/pdf',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
        }
        return content_types.get(extension, 'application/octet-stream')

    async def run_all_tests(self, test_files: List[Path], email: str, password: str):
        """Run tests for all provided files"""
        self.print_header("File Parsing Pipeline - End-to-End Tests")

        # Authenticate
        if not await self.authenticate(email, password):
            self.print_error("Authentication failed. Exiting.")
            return

        # Setup (get existing org and project)
        if not await self.setup_project():
            self.print_error("Failed to setup project. Exiting.")
            return

        # Test each file
        for file_path in test_files:
            if not file_path.exists():
                self.print_error(f"File not found: {file_path}")
                continue

            result = await self.test_file(file_path)
            self.test_results.append(result)

        # Print summary
        self.print_summary()

    def print_summary(self):
        """Print test results summary"""
        self.print_header("Test Results Summary")

        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r.get("success"))
        failed = total - passed

        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print()

        for result in self.test_results:
            status_icon = "✓" if result.get("success") else "✗"
            print(f"{status_icon} {result['file_name']}")
            if result.get("file_id"):
                print(f"    File ID: {result['file_id']}")
            print(f"    Status: {result.get('final_status', 'N/A')}")

            if result.get("validation"):
                validation = result["validation"]
                if validation.get("checks"):
                    print(f"    Sections: {validation['checks'].get('section_count', 'N/A')}")
                    print(f"    Parser: {validation['checks'].get('parser', 'N/A')}")
                    print(f"    Service: {validation['checks'].get('parsing_service', 'N/A')}")
                    if validation['checks'].get('page_count'):
                        print(f"    Pages: {validation['checks'].get('page_count')}")
                
                # Show blob storage info
                if validation.get("blob_storage"):
                    blob_info = validation["blob_storage"]
                    print(f"    Enriched JSON Size: {blob_info.get('size_bytes', 0):,} bytes")
                    if blob_info.get("path"):
                        print(f"    Blob Path: {blob_info['path']}")

            if result.get("error"):
                print(f"    Error: {result['error']}")
            print()

        # Save results to file
        results_file = Path(__file__).parent.parent / "test_results" / f"parsing_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        results_file.parent.mkdir(exist_ok=True)

        with open(results_file, 'w') as f:
            json.dump(self.test_results, f, indent=2)

        print(f"Detailed results saved to: {results_file}")


async def main():
    """Main entry point"""
    # Authentication credentials
    email = "punith@memic.ai"
    password = "12345678"

    # Define test files
    base_path = Path(__file__).parent.parent / "test_data"

    test_files = [
        base_path / "pdf" / "sample.pdf",
        base_path / "office" / "file_example_PPT_1MB.ppt",
        base_path / "office" / "file_example_XLSX_5000.xlsx",
    ]

    # Run tests
    async with ParsingPipelineTest() as test_harness:
        await test_harness.run_all_tests(test_files, email, password)


if __name__ == "__main__":
    asyncio.run(main())
