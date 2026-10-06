# Azure hosting notes (future)

Same container image; only config changes.

## Minimum services

- **Azure Container Registry** — push the image.
- **Azure Container Apps** (or App Service) — run the image.
- **Azure Database for PostgreSQL Flexible Server** — set `DATABASE_URL`.
- **Azure Blob Storage** — create a container, e.g. `documents`.
  Set env:
  ```
  STORAGE_BACKEND=azure_blob
  AZURE_STORAGE_CONNECTION_STRING=<from-portal>
  AZURE_STORAGE_CONTAINER=documents
  ```
  Uncomment `azure-storage-blob` in `requirements.txt` and rebuild.
- **Azure Key Vault** — mount secrets as env vars.
- **Azure Communication Services** or SendGrid — email.

## SAS-URL upgrade

`AzureBlobBackend.get_url()` currently returns the raw blob URL. For
production, replace with:
```python
from azure.storage.blob import generate_blob_sas, BlobSasPermissions
sas = generate_blob_sas(
    account_name=...,
    container_name=self.container,
    blob_name=key,
    account_key=...,
    permission=BlobSasPermissions(read=True),
    expiry=datetime.utcnow() + timedelta(seconds=ttl_seconds or 3600),
)
return f"{blob_client.url}?{sas}"
```
