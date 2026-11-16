import logging
from typing import Optional
from django.conf import settings
from .base import BaseStorageService
from .azure import AzureStorageService
from .supabase import SupabaseStorageService

logger = logging.getLogger(__name__)

def get_storage_service(provider: Optional[str] = None) -> BaseStorageService:
    """
    Factory function to retrieve the configured cloud storage service adapter.
    Selects provider based on settings.STORAGE_PROVIDER or the explicit 'provider' argument.
    Currently supports: 'azure', 'supabase'.
    """
    selected_provider = (
        provider or getattr(settings, "STORAGE_PROVIDER", "azure")
    ).strip().lower()

    logger.debug(f"Initializing cloud storage service for provider: '{selected_provider}'")

    if selected_provider == "azure":
        return AzureStorageService(
            account_url=getattr(settings, "AZURE_STORAGE_ACCOUNT_URL", None),
            tenant_id=getattr(settings, "AZURE_TENANT_ID", None),
            client_id=getattr(settings, "AZURE_CLIENT_ID", None),
            username=getattr(settings, "AZURE_USERNAME", None),
            password=getattr(settings, "AZURE_PASSWORD", None),
            container_name=getattr(settings, "AZURE_CONTAINER_NAME", None),
        )

    if selected_provider == "supabase":
        return SupabaseStorageService(
            supabase_url=getattr(settings, "SUPABASE_URL", None),
            service_role_key=getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", None),
            bucket_name=getattr(settings, "SUPABASE_STORAGE_BUCKET", "polygon-testcases"),
        )

    raise ValueError(
        f"Unsupported storage provider '{selected_provider}'. "
        f"Currently supported providers: azure, supabase."
    )
