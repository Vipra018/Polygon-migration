import logging
from typing import Tuple, Optional, Union, List
import requests
from requests.exceptions import RequestException

from .base import BaseStorageService

logger = logging.getLogger(__name__)


class SupabaseStorageService(BaseStorageService):
    """
    Supabase Storage implementation of BaseStorageService.
    Communicates directly with the Supabase Storage REST API using standard
    authenticated HTTP requests, supporting private storage buckets.
    """

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        service_role_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        timeout: int = 20
    ):
        url = (supabase_url or "").strip()
        while "SUPABASE_URL=" in url:
            url = url.split("SUPABASE_URL=", 1)[1].strip()
        if "nhzjtmwgewtilaqmvavg" in url:
            logger.info("Normalizing project ref typo 'nhzjtmwgewtilaqmvavg' to 'nhzjtmwgewtllaqmvavg'")
            url = url.replace("nhzjtmwgewtilaqmvavg", "nhzjtmwgewtllaqmvavg")
        self.supabase_url = url.rstrip("/")

        key = (service_role_key or "").strip()
        if "SUPABASE_SERVICE_ROLE_KEY=" in key:
            key = key.split("SUPABASE_SERVICE_ROLE_KEY=", 1)[1].strip()
        self.service_role_key = key

        bucket = (bucket_name or "polygon-testcases").strip()
        if "SUPABASE_STORAGE_BUCKET=" in bucket:
            bucket = bucket.split("SUPABASE_STORAGE_BUCKET=", 1)[1].strip()
        self.bucket_name = bucket

        self.timeout = timeout

        self._validate_credentials()

    def _validate_credentials(self) -> None:
        """
        Validates that required Supabase configuration parameters are provided.
        Raises an actionable error if any are missing or placeholders.
        Never logs or exposes secret credentials.
        """
        creds = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY": self.service_role_key,
            "SUPABASE_STORAGE_BUCKET": self.bucket_name,
        }
        missing = [
            k for k, v in creds.items()
            if not v or "placeholder" in str(v).lower()
        ]
        if missing:
            raise ValueError(
                f"Supabase Storage is configured as the active provider, but the following "
                f"configurations are missing or placeholder values: {', '.join(missing)}. "
                f"Please configure them in your .env file."
            )

    @property
    def _headers(self) -> dict:
        """
        Standard authentication headers for Supabase Storage REST API using service_role key.
        """
        return {
            "Authorization": f"Bearer {self.service_role_key}",
            "apikey": self.service_role_key,
        }

    @property
    def _storage_api_base(self) -> str:
        return f"{self.supabase_url}/storage/v1"

    def _resolve_bucket(self, container_name: Optional[str] = None) -> str:
        if not container_name:
            return self.bucket_name
        # If passed legacy Azure container names or defaults, map to the configured Supabase bucket
        if container_name.lower() in ("testcases", "azure", "default"):
            return self.bucket_name
        return container_name

    # -------------------------------------------------------------------------
    # Core Granular Storage Primitives
    # -------------------------------------------------------------------------
    def upload_file(
        self,
        path: str,
        content: Union[str, bytes],
        container_name: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Uploads an arbitrary file (string or raw binary) to Supabase Storage.
        Uses x-upsert: true to support idempotent writes.
        """
        bucket = self._resolve_bucket(container_name)
        clean_path = path.lstrip("/")
        url = f"{self._storage_api_base}/object/{bucket}/{clean_path}"

        headers = self._headers.copy()
        headers["x-upsert"] = "true"

        if isinstance(content, str):
            data = content.encode("utf-8")
            headers["Content-Type"] = "text/plain; charset=utf-8"
        else:
            data = content
            headers["Content-Type"] = "application/octet-stream"

        try:
            response = requests.post(
                url,
                headers=headers,
                data=data,
                timeout=self.timeout
            )
        except RequestException as e:
            logger.error(f"Network error uploading file to Supabase at {path}: {e}")
            raise

        if response.status_code in (401, 403):
            logger.error(f"Authentication failed for Supabase Storage (HTTP {response.status_code})")
            raise PermissionError(
                f"Supabase Storage authentication failed (HTTP {response.status_code}). "
                f"Please verify SUPABASE_SERVICE_ROLE_KEY."
            )

        if not response.ok:
            logger.error(
                f"Failed to upload file to Supabase at {path}: HTTP {response.status_code} - {response.text}"
            )
            raise RuntimeError(
                f"Supabase upload failed for {path}: HTTP {response.status_code} - {response.text}"
            )

        logger.info(f"Successfully uploaded file to Supabase: {bucket}/{clean_path}")
        return True

    def download_file(
        self,
        path: str,
        container_name: Optional[str] = None,
        **kwargs
    ) -> Optional[bytes]:
        """
        Downloads and returns the raw bytes of an object from a private Supabase bucket.
        Returns None if the object does not exist.
        """
        bucket = self._resolve_bucket(container_name)
        clean_path = path.lstrip("/")
        url = f"{self._storage_api_base}/object/authenticated/{bucket}/{clean_path}"

        try:
            response = requests.get(
                url,
                headers=self._headers,
                timeout=self.timeout
            )
        except RequestException as e:
            logger.error(f"Network error downloading file from Supabase at {path}: {e}")
            raise

        if response.status_code == 404 or (
            response.status_code == 400 and "not found" in response.text.lower()
        ):
            logger.debug(f"File {path} not found in Supabase bucket {bucket}")
            return None

        if response.status_code in (401, 403):
            logger.error(f"Authentication failed for Supabase Storage (HTTP {response.status_code})")
            raise PermissionError(
                f"Supabase Storage authentication failed (HTTP {response.status_code}). "
                f"Please verify SUPABASE_SERVICE_ROLE_KEY."
            )

        if not response.ok:
            logger.error(
                f"Failed to download file from Supabase at {path}: HTTP {response.status_code} - {response.text}"
            )
            raise RuntimeError(
                f"Supabase download failed for {path}: HTTP {response.status_code} - {response.text}"
            )

        return response.content

    def file_exists(
        self,
        path: str,
        container_name: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Returns True if a file exists in the private Supabase bucket, False otherwise.
        """
        bucket = self._resolve_bucket(container_name)
        clean_path = path.lstrip("/")
        url = f"{self._storage_api_base}/object/authenticated/{bucket}/{clean_path}"

        try:
            response = requests.get(
                url,
                headers=self._headers,
                stream=True,
                timeout=self.timeout
            )
            if response.status_code == 200:
                return True
            if response.status_code == 404 or (
                response.status_code == 400 and "not found" in response.text.lower()
            ):
                return False
            if response.status_code in (401, 403):
                raise PermissionError(
                    f"Supabase Storage authentication failed (HTTP {response.status_code})."
                )
            return False
        except RequestException as e:
            logger.error(f"Error checking file existence in Supabase at {path}: {e}")
            return False

    def delete_file(
        self,
        path: str,
        container_name: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Deletes a single file from Supabase Storage.
        Returns True if deleted, False if not found.
        """
        bucket = self._resolve_bucket(container_name)
        clean_path = path.lstrip("/")

        # First attempt DELETE /object/{bucket}/{path}
        url = f"{self._storage_api_base}/object/{bucket}/{clean_path}"
        try:
            response = requests.delete(
                url,
                headers=self._headers,
                timeout=self.timeout
            )
        except RequestException as e:
            logger.error(f"Network error deleting file from Supabase at {path}: {e}")
            raise

        if response.status_code in (200, 204):
            logger.info(f"Successfully deleted file from Supabase: {bucket}/{clean_path}")
            return True

        # Fallback to batch delete endpoint if single-object delete is not routed
        batch_url = f"{self._storage_api_base}/object/{bucket}"
        try:
            headers = self._headers.copy()
            headers["Content-Type"] = "application/json"
            batch_resp = requests.delete(
                batch_url,
                headers=headers,
                json={"prefixes": [clean_path]},
                timeout=self.timeout
            )
            if batch_resp.status_code in (200, 204):
                logger.info(f"Successfully deleted file via batch endpoint from Supabase: {bucket}/{clean_path}")
                return True
        except RequestException as e:
            logger.error(f"Error in batch delete fallback for {path}: {e}")

        if response.status_code in (401, 403):
            raise PermissionError(
                f"Supabase Storage authentication failed (HTTP {response.status_code})."
            )

        logger.debug(f"File {path} not found to delete in Supabase bucket {bucket}")
        return False

    # -------------------------------------------------------------------------
    # Test Case High-Level Operations
    # -------------------------------------------------------------------------
    def upload_test_case(self, *args, **kwargs) -> bool:
        """
        Uploads an input and expected output file for a test case into Supabase Storage.
        Standard path:
            test_cases/{problem_id}/{test_number}
            test_cases/{problem_id}/{test_number}.a
        """
        if len(args) == 5:
            # Legacy: (container_name, problem_id, test_number, input_data, output_data)
            target_container, problem_id, test_number, input_data, output_data = args
        elif len(args) == 4:
            # Modern: (problem_id, test_number, input_data, output_data)
            problem_id, test_number, input_data, output_data = args
            target_container = kwargs.get("container_name") or self.bucket_name
        else:
            problem_id = kwargs.get("problem_id")
            test_number = kwargs.get("test_number")
            input_data = kwargs.get("input_data", "")
            output_data = kwargs.get("output_data", "")
            target_container = kwargs.get("container_name") or self.bucket_name

        bucket = self._resolve_bucket(target_container)
        input_path = self.get_input_path(problem_id, test_number)
        output_path = self.get_output_path(problem_id, test_number)

        # Upload input
        self.upload_file(input_path, input_data, container_name=bucket)

        # Upload output (with rollback on failure)
        try:
            self.upload_file(output_path, output_data, container_name=bucket)
        except Exception as out_err:
            logger.warning(
                f"Output upload failed for test case #{test_number} (problem {problem_id}). "
                f"Rolling back input file: {input_path}"
            )
            try:
                self.delete_file(input_path, container_name=bucket)
            except Exception as del_err:
                logger.warning(f"Failed to delete input file during rollback: {del_err}")
            raise out_err

        return True

    def download_test_case(
        self,
        problem_id: Union[str, int],
        test_number: Union[str, int],
        container_name: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Downloads and returns (input_data_str, output_data_str) as decoded UTF-8 strings.
        Returns (None, None) if either file is missing.
        """
        bucket = self._resolve_bucket(container_name)
        input_path = self.get_input_path(problem_id, test_number)
        output_path = self.get_output_path(problem_id, test_number)

        input_bytes = self.download_file(input_path, container_name=bucket)
        output_bytes = self.download_file(output_path, container_name=bucket)

        if input_bytes is None or output_bytes is None:
            return None, None

        return (
            input_bytes.decode("utf-8", errors="replace"),
            output_bytes.decode("utf-8", errors="replace")
        )

    def test_case_exists(
        self,
        problem_id: Union[str, int],
        test_number: Union[str, int],
        container_name: Optional[str] = None
    ) -> bool:
        """
        Checks whether both input and output files exist for the given test case.
        """
        bucket = self._resolve_bucket(container_name)
        input_path = self.get_input_path(problem_id, test_number)
        output_path = self.get_output_path(problem_id, test_number)

        return (
            self.file_exists(input_path, container_name=bucket)
            and self.file_exists(output_path, container_name=bucket)
        )

    def delete_test_cases(self, *args, **kwargs) -> int:
        """
        Deletes all test cases and artifacts matching only the requested problem ID.
        Prefix: test_cases/{problem_id}/
        Does not touch adjacent problems (e.g. problem 42 vs 420).
        """
        if len(args) == 2:
            first, second = args
            if isinstance(first, str) and not first.isdigit():
                target_container, problem_id = first, second
            else:
                problem_id, target_container = first, second
        elif len(args) == 1:
            problem_id = args[0]
            target_container = kwargs.get("container_name") or self.bucket_name
        else:
            problem_id = kwargs.get("problem_id")
            target_container = kwargs.get("container_name") or self.bucket_name

        bucket = self._resolve_bucket(target_container)
        folder_prefix = f"test_cases/{problem_id}"

        # List objects under prefix
        list_url = f"{self._storage_api_base}/object/list/{bucket}"
        headers = self._headers.copy()
        headers["Content-Type"] = "application/json"

        try:
            resp = requests.post(
                list_url,
                headers=headers,
                json={"prefix": folder_prefix, "limit": 1000},
                timeout=self.timeout
            )
        except RequestException as e:
            logger.error(f"Network error listing objects in Supabase bucket {bucket}: {e}")
            raise

        if not resp.ok:
            logger.error(
                f"Failed to list objects in Supabase for problem {problem_id}: HTTP {resp.status_code} - {resp.text}"
            )
            return 0

        items = resp.json()
        if not items:
            return 0

        # Construct full paths ensuring strict problem isolation
        strict_prefix = f"test_cases/{problem_id}/"
        files_to_delete: List[str] = []

        for item in items:
            name = item.get("name")
            if not name:
                continue
            full_path = f"{folder_prefix}/{name}"
            # Ensure path starts strictly with test_cases/{problem_id}/
            if full_path.startswith(strict_prefix):
                files_to_delete.append(full_path)

        if not files_to_delete:
            return 0

        logger.info(f"Deleting {len(files_to_delete)} files for problem {problem_id} from Supabase")

        # Batch delete
        del_url = f"{self._storage_api_base}/object/{bucket}"
        try:
            del_resp = requests.delete(
                del_url,
                headers=headers,
                json={"prefixes": files_to_delete},
                timeout=self.timeout
            )
            if del_resp.ok:
                return len(files_to_delete)
        except RequestException as e:
            logger.warning(f"Batch delete failed on Supabase; falling back to individual deletes: {e}")

        # Fallback to individual deletes
        deleted_count = 0
        for f in files_to_delete:
            if self.delete_file(f, container_name=bucket):
                deleted_count += 1
        return deleted_count
