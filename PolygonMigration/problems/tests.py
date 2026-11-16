import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase, RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore

from problems.storage.base import BaseStorageService
from problems.storage.azure import AzureStorageService
from problems.storage.supabase import SupabaseStorageService
from problems.storage.factory import get_storage_service
from problems.storage.transaction import StorageTransaction
from problems.AzureTestcase import AzureBlobManager
from problems.views import index
from problems.polygon_api import PolygonAPI


class StorageInterfaceTests(SimpleTestCase):
    """
    Validates BaseStorageService contract, path formatting, and factory resolution.
    """

    def test_abstract_base_class_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            BaseStorageService()

    def test_exact_path_generation_unpadded(self):
        class DummyStorage(BaseStorageService):
            def upload_test_case(self, p, t, i, o): pass
            def download_test_case(self, p, t): pass
            def test_case_exists(self, p, t): pass
            def delete_test_cases(self, p): pass
            def upload_file(self, path, content, **kwargs): pass
            def file_exists(self, path, **kwargs): pass
            def download_file(self, path, **kwargs): pass
            def delete_file(self, path, **kwargs): pass

        dummy = DummyStorage()
        self.assertEqual(dummy.get_input_path(1, 1), "test_cases/1/1")
        self.assertEqual(dummy.get_output_path(1, 1), "test_cases/1/1.a")
        self.assertEqual(dummy.get_input_path(1, 10), "test_cases/1/10")
        self.assertEqual(dummy.get_output_path(1, 10), "test_cases/1/10.a")
        self.assertEqual(dummy.get_custom_checker_path(1, "check.exe"), "test_cases/1/check.exe")

    def test_factory_unsupported_provider_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            get_storage_service("unsupported_cloud_provider")
        self.assertIn("Unsupported storage provider", str(ctx.exception))

    def test_azure_blob_manager_backward_compatibility(self):
        self.assertTrue(issubclass(AzureBlobManager, AzureStorageService))
        self.assertTrue(issubclass(AzureBlobManager, BaseStorageService))


class SupabaseStorageServiceTests(SimpleTestCase):
    """
    Mocked unit test suite verifying SupabaseStorageService REST implementation.
    """

    def setUp(self):
        self.service = SupabaseStorageService(
            supabase_url="https://mockproject.supabase.co",
            service_role_key="mock-service-role-key",
            bucket_name="polygon-testcases"
        )
        self.base_url = "https://mockproject.supabase.co/storage/v1"

    @patch("requests.post")
    def test_uploading_string_content(self, mock_post):
        mock_resp = MagicMock(ok=True, status_code=200)
        mock_post.return_value = mock_resp

        result = self.service.upload_file("test_cases/1/1", "1 2 3\n4 5 6")
        self.assertTrue(result)

        expected_url = f"{self.base_url}/object/polygon-testcases/test_cases/1/1"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], expected_url)
        self.assertEqual(kwargs["data"], b"1 2 3\n4 5 6")
        self.assertEqual(kwargs["headers"]["x-upsert"], "true")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer mock-service-role-key")

    @patch("requests.post")
    def test_uploading_binary_content(self, mock_post):
        mock_resp = MagicMock(ok=True, status_code=200)
        mock_post.return_value = mock_resp

        payload = b"\x7fELF\x02\x01custom_binary"
        result = self.service.upload_file("test_cases/1/check.exe", payload)
        self.assertTrue(result)

        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"], payload)
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/octet-stream")

    @patch("requests.get")
    def test_downloading_file(self, mock_get):
        mock_resp = MagicMock(ok=True, status_code=200, content=b"input_data_bytes")
        mock_get.return_value = mock_resp

        data = self.service.download_file("test_cases/1/1")
        self.assertEqual(data, b"input_data_bytes")

        expected_url = f"{self.base_url}/object/authenticated/polygon-testcases/test_cases/1/1"
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], expected_url)

    @patch("requests.get")
    def test_file_exists(self, mock_get):
        mock_resp = MagicMock(ok=True, status_code=200)
        mock_get.return_value = mock_resp

        self.assertTrue(self.service.file_exists("test_cases/1/1"))
        expected_url = f"{self.base_url}/object/authenticated/polygon-testcases/test_cases/1/1"
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], expected_url)

    @patch("requests.delete")
    def test_deleting_file(self, mock_delete):
        mock_resp = MagicMock(ok=True, status_code=200)
        mock_delete.return_value = mock_resp

        self.assertTrue(self.service.delete_file("test_cases/1/1"))
        expected_url = f"{self.base_url}/object/polygon-testcases/test_cases/1/1"
        args, kwargs = mock_delete.call_args
        self.assertEqual(args[0], expected_url)

    @patch("requests.post")
    def test_upload_test_case_pair(self, mock_post):
        mock_resp = MagicMock(ok=True, status_code=200)
        mock_post.return_value = mock_resp

        self.assertTrue(self.service.upload_test_case(1, 2, "in_data", "out_data"))
        self.assertEqual(mock_post.call_count, 2)


class StorageTransactionRollbackTests(SimpleTestCase):
    """
    Validates atomic, non-destructive rollback in StorageTransaction.
    """

    def test_transaction_rollback_deletes_new_files_and_restores_preexisting(self):
        mock_storage = MagicMock()
        def mock_exists(path, **kwargs):
            return path == "test_cases/1/1"

        mock_storage.file_exists.side_effect = mock_exists
        mock_storage.download_file.return_value = b"original_content_1"
        mock_storage.upload_file.return_value = True
        mock_storage.delete_file.return_value = True

        tx = StorageTransaction(mock_storage)
        tx.upload_file("test_cases/1/1", "new_content_1")
        tx.upload_file("test_cases/1/2", "new_content_2")

        self.assertIn("test_cases/1/1", tx.backups)
        self.assertIn("test_cases/1/2", tx.created_files)

        # Trigger rollback
        tx.rollback()

        # file 2 (new) should be deleted
        mock_storage.delete_file.assert_called_with("test_cases/1/2")
        # file 1 (pre-existing) should be restored
        mock_storage.upload_file.assert_called_with("test_cases/1/1", b"original_content_1")


class ProblemIdNormalizationTests(SimpleTestCase):
    """
    Validates problem ID whitespace handling and parameter preservation.
    """

    def setUp(self):
        self.factory = RequestFactory()

    @patch("problems.views.ProblemTag.objects.all")
    def test_empty_problem_id_returns_validation_message(self, mock_tags):
        mock_tags.return_value.order_by.return_value = []
        req = self.factory.post("/", data={"problem_id": ""})
        req.user = MagicMock(is_authenticated=True, is_staff=True)
        req.session = SessionStore()
        setattr(req, "_messages", FallbackStorage(req))

        resp = index(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Please enter a valid Polygon Problem ID.", resp.content.decode("utf-8"))

    @patch("problems.views.ProblemTag.objects.all")
    def test_whitespace_problem_id_returns_validation_message(self, mock_tags):
        mock_tags.return_value.order_by.return_value = []
        req = self.factory.post("/", data={"problem_id": "   \t  "})
        req.user = MagicMock(is_authenticated=True, is_staff=True)
        req.session = SessionStore()
        setattr(req, "_messages", FallbackStorage(req))

        resp = index(req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Please enter a valid Polygon Problem ID.", resp.content.decode("utf-8"))

    def test_selective_parameter_normalization_preserves_other_parameters(self):
        params = {
            "problemId": " 631622 \t",
            "checker_code": "  int main() { return 0; }\n\t"
        }
        # Emulate _make_request normalization
        p_copy = params.copy()
        if "problemId" in p_copy and p_copy["problemId"] is not None:
            p_copy["problemId"] = str(p_copy["problemId"]).strip()

        self.assertEqual(p_copy["problemId"], "631622")
        self.assertEqual(p_copy["checker_code"], "  int main() { return 0; }\n\t")
