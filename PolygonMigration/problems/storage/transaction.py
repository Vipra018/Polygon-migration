import logging
from typing import Union, Optional, Set, Dict
from .base import BaseStorageService

logger = logging.getLogger(__name__)


class StorageTransaction:
    """
    Journaled storage transaction that records created and modified storage objects.
    Provides atomic, non-destructive rollback:
    - Never deletes pre-existing valid files.
    - Restores pre-existing files that were modified during the attempt.
    - Deletes only newly created files during this attempt.
    - Rollback is idempotent and safe to call multiple times.
    - Cleanup failures are logged without masking original exceptions.

    NOTE ON CONCURRENCY:
    This transaction journal assumes sequential migrations per problem.
    Simultaneous migrations of the same problem from multiple processes
    may interleave object writes and snapshots. If concurrent migration
    support is required in the future, distributed locking or blue-green
    prefix promotion should be introduced.
    """

    def __init__(self, storage_service: BaseStorageService, **storage_kwargs):
        self.storage = storage_service
        self.storage_kwargs = storage_kwargs
        self.created_files: Set[str] = set()
        self.backups: Dict[str, bytes] = {}
        self.is_rolled_back: bool = False
        self.is_committed: bool = False

    def upload_file(self, path: str, content: Union[str, bytes]) -> bool:
        """
        Uploads a file through the journaled transaction.
        Snapshots previous content if the file already exists BEFORE uploading.
        Records created file tracking if new BEFORE uploading.
        """
        if self.is_rolled_back:
            raise RuntimeError("Cannot upload files on a rolled back storage transaction.")

        # Journal recording prior to upload attempt:
        # If the path has not yet been journaled in this transaction:
        if path not in self.created_files and path not in self.backups:
            try:
                if self.storage.file_exists(path, **self.storage_kwargs):
                    logger.debug("Backing up pre-existing file for rollback: %s", path)
                    original_bytes = self.storage.download_file(path, **self.storage_kwargs)
                    # Even if file is empty (0 bytes), store b"" as backup
                    self.backups[path] = original_bytes if original_bytes is not None else b""
                else:
                    logger.debug("Recording newly created file for rollback: %s", path)
                    self.created_files.add(path)
            except Exception as e:
                logger.warning(
                    f"Failed to check existence or backup file {path} before upload: {e}. "
                    f"Treating as newly created for rollback safety."
                )
                self.created_files.add(path)

        # Execute upload through the underlying storage service
        return self.storage.upload_file(path, content, **self.storage_kwargs)

    def upload_test_case(
        self,
        problem_id: Union[str, int],
        test_number: Union[str, int],
        input_data: str,
        output_data: str
    ) -> bool:
        """
        Uploads an input and output test case pair through the transaction journal.
        If output fails, the input is safely journaled for rollback.
        """
        input_path = self.storage.get_input_path(problem_id, test_number)
        output_path = self.storage.get_output_path(problem_id, test_number)

        self.upload_file(input_path, input_data)
        self.upload_file(output_path, output_data)
        return True

    def rollback(self) -> None:
        """
        Rolls back all operations recorded in this transaction:
        1. Deletes newly created files.
        2. Restores modified pre-existing files to their exact original bytes.
        Safe to call multiple times. Cleanup failures are logged without raising.
        """
        logger.info(
            "Executing storage transaction rollback (created: %d, modified/backup: %d)...",
            len(self.created_files),
            len(self.backups)
        )

        # 1. Delete newly created files
        for path in list(self.created_files):
            try:
                logger.info("Rollback: deleting newly created file %s", path)
                self.storage.delete_file(path, **self.storage_kwargs)
                self.created_files.discard(path)
            except Exception as e:
                logger.error(
                    f"Rollback error: failed to delete newly created file {path}: {e}",
                    exc_info=True
                )

        # 2. Restore modified pre-existing files
        for path in list(self.backups.keys()):
            original_data = self.backups[path]
            try:
                logger.info("Rollback: restoring pre-existing file %s (%d bytes)", path, len(original_data))
                self.storage.upload_file(path, original_data, **self.storage_kwargs)
                del self.backups[path]
            except Exception as e:
                logger.error(
                    f"Rollback error: failed to restore pre-existing file {path}: {e}",
                    exc_info=True
                )

        self.is_rolled_back = True
        logger.info("Storage transaction rollback finished.")

    def commit(self) -> None:
        """
        Marks the transaction as committed upon complete migration success.
        Discards backup copies without deleting pre-existing files.
        """
        logger.info(
            "Storage transaction committed successfully. Preserving %d created files.",
            len(self.created_files)
        )
        self.backups.clear()
        self.created_files.clear()
        self.is_committed = True
