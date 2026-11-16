from abc import ABC, abstractmethod
from typing import Tuple, Optional, Union
import logging

logger = logging.getLogger(__name__)

class BaseStorageService(ABC):
    """
    Abstract storage interface for competitive programming test cases and problem artifacts.
    Enforces the required directory structure:
        test_cases/{problem_id}/{test_number}
        test_cases/{problem_id}/{test_number}.a
    """

    def get_input_path(self, problem_id: Union[str, int], test_number: Union[str, int]) -> str:
        """
        Returns the standardized relative storage path for a test case input.
        Does not use zero-padding.
        """
        return f"test_cases/{problem_id}/{test_number}"

    def get_output_path(self, problem_id: Union[str, int], test_number: Union[str, int]) -> str:
        """
        Returns the standardized relative storage path for a test case output.
        Does not use zero-padding.
        """
        return f"test_cases/{problem_id}/{test_number}.a"

    def get_custom_checker_path(self, problem_id: Union[str, int], filename: str) -> str:
        """
        Returns the standardized relative storage path for a custom checker file.
        """
        return f"test_cases/{problem_id}/{filename}"

    @abstractmethod
    def upload_test_case(
        self,
        problem_id: Union[str, int],
        test_number: Union[str, int],
        input_data: str,
        output_data: str
    ) -> bool:
        """
        Uploads a single test case's input and expected output.
        Returns True on success, False or raises on failure.
        """
        pass

    @abstractmethod
    def download_test_case(
        self,
        problem_id: Union[str, int],
        test_number: Union[str, int]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Downloads and returns a tuple of (input_data, output_data) as strings.
        Returns (None, None) if the test case does not exist.
        """
        pass

    @abstractmethod
    def test_case_exists(
        self,
        problem_id: Union[str, int],
        test_number: Union[str, int]
    ) -> bool:
        """
        Returns True if both input and output files exist in storage, False otherwise.
        """
        pass

    @abstractmethod
    def delete_test_cases(
        self,
        problem_id: Union[str, int]
    ) -> int:
        """
        Deletes all test cases and artifacts for the given problem ID.
        Returns the count of deleted files/blobs.
        """
        pass

    @abstractmethod
    def upload_file(
        self,
        path: str,
        content: Union[str, bytes],
        **kwargs
    ) -> bool:
        """
        Uploads an arbitrary file (e.g., custom checker binary or source) to the given path.
        """
        pass

    @abstractmethod
    def file_exists(
        self,
        path: str,
        **kwargs
    ) -> bool:
        """
        Returns True if a file exists at the given relative path in storage, False otherwise.
        """
        pass

    @abstractmethod
    def download_file(
        self,
        path: str,
        **kwargs
    ) -> Optional[bytes]:
        """
        Downloads and returns the exact raw bytes of a file from storage.
        Returns None if the file does not exist.
        """
        pass

    @abstractmethod
    def delete_file(
        self,
        path: str,
        **kwargs
    ) -> bool:
        """
        Deletes a single file at the given relative path from storage.
        Returns True if deleted, False if not found.
        """
        pass
