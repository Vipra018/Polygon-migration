"""
Legacy AzureTestcase module refactored to use the modern AzureStorageService adapter.
Maintains 100% backward compatibility for existing code.
"""
from problems.storage.azure import AzureStorageService

class AzureBlobManager(AzureStorageService):
    """
    Backward-compatible alias of AzureStorageService.
    Inherits all capabilities including:
    - upload_test_case (without zero-padding)
    - download_test_case
    - test_case_exists
    - delete_test_cases / empty_blob
    """
    pass

__all__ = ["AzureBlobManager"]
