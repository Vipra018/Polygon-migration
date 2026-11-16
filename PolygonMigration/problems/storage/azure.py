import os
import logging
from typing import Tuple, Optional, Union
from azure.identity import UsernamePasswordCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError, ClientAuthenticationError

from .base import BaseStorageService

logger = logging.getLogger(__name__)

class AzureStorageService(BaseStorageService):
    """
    Azure Blob Storage implementation of BaseStorageService.
    Preserves the existing authentication mechanism while adding download,
    existence checking, and corrected file paths (without zero-padding).
    """

    def __init__(
        self,
        account_url: Optional[str] = None,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        container_name: Optional[str] = None
    ):
        self.account_url = account_url
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.username = username
        self.password = password
        self.container_name = container_name
        self.blob_service_client = None

        # Validate credentials at runtime when storage is initialized
        self._validate_credentials()
        self._authenticate()

    def _validate_credentials(self):
        """
        Ensures all required Azure credentials are provided and non-placeholder.
        Raises an actionable error if any are missing.
        """
        creds = {
            "AZURE_STORAGE_ACCOUNT_URL": self.account_url,
            "AZURE_TENANT_ID": self.tenant_id,
            "AZURE_CLIENT_ID": self.client_id,
            "AZURE_USERNAME": self.username,
            "AZURE_PASSWORD": self.password,
        }
        missing = [
            k for k, v in creds.items()
            if not v or "placeholder" in str(v).lower()
        ]
        if missing:
            raise ValueError(
                f"Azure Blob Storage is configured as the active provider, but the following "
                f"credentials are missing or placeholder values: {', '.join(missing)}. "
                f"Please configure them in your .env file."
            )

    def _authenticate(self):
        """
        Initializes the BlobServiceClient using UsernamePasswordCredential.
        """
        logger.info("Attempting Azure authentication...")
        try:
            credential = UsernamePasswordCredential(
                tenant_id=self.tenant_id,
                client_id=self.client_id,
                username=self.username,
                password=self.password
            )
            self.blob_service_client = BlobServiceClient(
                account_url=self.account_url,
                credential=credential
            )
            logger.info("Azure authentication successful. BlobServiceClient created.")
        except ClientAuthenticationError as e:
            logger.error(f"Azure Authentication Failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during Azure BlobServiceClient initialization: {e}")
            raise

    def upload_test_case(self, *args, **kwargs) -> bool:
        """
        Supports both modern interface:
            upload_test_case(problem_id, test_number, input_data, output_data)
        and legacy signature:
            upload_test_case(container_name, db_problem_id, test_number, input_data, output_data)

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
            target_container = kwargs.get("container_name") or self.container_name
        else:
            problem_id = kwargs.get("problem_id")
            test_number = kwargs.get("test_number")
            input_data = kwargs.get("input_data", "")
            output_data = kwargs.get("output_data", "")
            target_container = kwargs.get("container_name") or self.container_name

        if not target_container:
            raise ValueError("Target Azure container name must be specified.")

        input_path = self.get_input_path(problem_id, test_number)
        output_path = self.get_output_path(problem_id, test_number)

        try:
            # Upload input
            in_client = self.blob_service_client.get_blob_client(
                container=target_container, blob=input_path
            )
            in_client.upload_blob(input_data.encode("utf-8"), overwrite=True)
            logger.info(f"Uploaded input to {input_path}")

            # Upload output
            try:
                out_client = self.blob_service_client.get_blob_client(
                    container=target_container, blob=output_path
                )
                out_client.upload_blob(output_data.encode("utf-8"), overwrite=True)
                logger.info(f"Uploaded output to {output_path}")
            except Exception as out_err:
                logger.warning(
                    f"Output upload failed for test case #{test_number} (problem {problem_id}). "
                    f"Rolling back input blob: {input_path}"
                )
                try:
                    in_client.delete_blob()
                except Exception as del_err:
                    logger.warning(f"Failed to delete input blob during test case rollback: {del_err}")
                raise out_err

            return True
        except Exception as e:
            logger.error(f"Error uploading test case #{test_number} for problem {problem_id}: {e}")
            raise

    def download_test_case(
        self,
        problem_id: Union[str, int],
        test_number: Union[str, int],
        container_name: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Downloads the input and expected output for a given test case from Azure.
        Returns (input_str, output_str) or (None, None) if not found.
        """
        target_container = container_name or self.container_name
        if not target_container:
            raise ValueError("Target Azure container name must be specified.")

        input_path = self.get_input_path(problem_id, test_number)
        output_path = self.get_output_path(problem_id, test_number)

        try:
            in_client = self.blob_service_client.get_blob_client(
                container=target_container, blob=input_path
            )
            out_client = self.blob_service_client.get_blob_client(
                container=target_container, blob=output_path
            )

            input_data = in_client.download_blob().readall().decode("utf-8")
            output_data = out_client.download_blob().readall().decode("utf-8")
            return input_data, output_data
        except ResourceNotFoundError:
            logger.warning(f"Test case #{test_number} for problem {problem_id} not found in Azure.")
            return None, None
        except Exception as e:
            logger.error(f"Error downloading test case #{test_number} for problem {problem_id}: {e}")
            raise

    def test_case_exists(
        self,
        problem_id: Union[str, int],
        test_number: Union[str, int],
        container_name: Optional[str] = None
    ) -> bool:
        """
        Checks whether both the input and output blobs exist in the container.
        """
        target_container = container_name or self.container_name
        if not target_container:
            raise ValueError("Target Azure container name must be specified.")

        input_path = self.get_input_path(problem_id, test_number)
        output_path = self.get_output_path(problem_id, test_number)

        try:
            in_client = self.blob_service_client.get_blob_client(
                container=target_container, blob=input_path
            )
            out_client = self.blob_service_client.get_blob_client(
                container=target_container, blob=output_path
            )
            return in_client.exists() and out_client.exists()
        except Exception as e:
            logger.error(f"Error checking existence for test #{test_number} of problem {problem_id}: {e}")
            return False

    def delete_test_cases(self, *args, **kwargs) -> int:
        """
        Supports both modern interface:
            delete_test_cases(problem_id, container_name=None)
        and legacy signature:
            empty_blob(container_name, problem_id)
        """
        if len(args) == 2:
            # Legacy: (container_name, problem_id) or (problem_id, container_name)
            first, second = args
            if isinstance(first, str) and not first.isdigit():
                target_container, problem_id = first, second
            else:
                problem_id, target_container = first, second
        elif len(args) == 1:
            problem_id = args[0]
            target_container = kwargs.get("container_name") or self.container_name
        else:
            problem_id = kwargs.get("problem_id")
            target_container = kwargs.get("container_name") or self.container_name

        if not target_container:
            raise ValueError("Target Azure container name must be specified.")

        prefix = f"test_cases/{problem_id}/"
        deleted_count = 0
        try:
            container_client = self.blob_service_client.get_container_client(target_container)
            blobs_to_delete = [
                blob.name for blob in container_client.list_blobs(name_starts_with=prefix)
            ]
            for blob_name in blobs_to_delete:
                logger.info(f"Deleting blob: {blob_name}")
                container_client.delete_blob(blob_name)
                deleted_count += 1
            logger.info(f"Deleted {deleted_count} blobs for problem {problem_id} in {target_container}")
            return deleted_count
        except Exception as e:
            logger.error(f"Error deleting test cases for problem {problem_id}: {e}")
            raise

    def upload_file(
        self,
        path: str,
        content: Union[str, bytes],
        container_name: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Uploads an arbitrary file (e.g. custom checker binary or source) to the given path.
        """
        target_container = container_name or self.container_name
        if not target_container:
            raise ValueError("Target Azure container name must be specified.")
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=target_container, blob=path
            )
            data = content.encode("utf-8") if isinstance(content, str) else content
            blob_client.upload_blob(data, overwrite=True)
            logger.info(f"Successfully uploaded file to {path}")
            return True
        except Exception as e:
            logger.error(f"Error uploading file to {path}: {e}")
            raise

    def file_exists(
        self,
        path: str,
        container_name: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Returns True if a blob exists at the specified path in Azure, False otherwise.
        """
        target_container = container_name or self.container_name
        if not target_container:
            raise ValueError("Target Azure container name must be specified.")
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=target_container, blob=path
            )
            return blob_client.exists()
        except Exception as e:
            logger.error(f"Error checking if blob exists at {path}: {e}")
            return False

    def download_file(
        self,
        path: str,
        container_name: Optional[str] = None,
        **kwargs
    ) -> Optional[bytes]:
        """
        Downloads and returns the raw bytes of a blob from Azure.
        Returns None if the blob does not exist.
        """
        target_container = container_name or self.container_name
        if not target_container:
            raise ValueError("Target Azure container name must be specified.")
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=target_container, blob=path
            )
            return blob_client.download_blob().readall()
        except ResourceNotFoundError:
            logger.warning(f"File {path} not found in container {target_container}")
            return None
        except Exception as e:
            logger.error(f"Error downloading file from {path}: {e}")
            raise

    def delete_file(
        self,
        path: str,
        container_name: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Deletes a single blob from Azure at the given path.
        Returns True on success, False if the blob was not found.
        """
        target_container = container_name or self.container_name
        if not target_container:
            raise ValueError("Target Azure container name must be specified.")
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=target_container, blob=path
            )
            blob_client.delete_blob()
            logger.info(f"Successfully deleted file from {path}")
            return True
        except ResourceNotFoundError:
            logger.warning(f"File {path} to delete was not found in container {target_container}")
            return False
        except Exception as e:
            logger.error(f"Error deleting file from {path}: {e}")
            raise

    # -------------------------------------------------------------------------
    # Backward Compatibility Aliases for Legacy AzureBlobManager
    # -------------------------------------------------------------------------
    def empty_blob(self, container_name: str, problem_id: Union[str, int]) -> int:
        """Legacy alias for delete_test_cases."""
        return self.delete_test_cases(container_name, problem_id)
