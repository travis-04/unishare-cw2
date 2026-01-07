import azure.functions as func
import logging
import json
import os
import base64
import uuid
from datetime import datetime, timezone

from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient, ContentSettings

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="list_files", methods=["GET"])
def list_files(req: func.HttpRequest) -> func.HttpResponse:
    try:
        endpoint = os.environ["COSMOS_ENDPOINT"]
        key = os.environ["COSMOS_KEY"]
        db_name = os.environ["COSMOS_DB"]
        container_name = os.environ["COSMOS_CONTAINER"]

        client = CosmosClient(endpoint, credential=key)
        container = client.get_database_client(db_name).get_container_client(container_name)

        query = "SELECT c.id, c.title, c.tags, c.blobPath, c.uploadedAt FROM c"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))

        return func.HttpResponse(json.dumps(items), status_code=200, mimetype="application/json")

    except Exception as e:
        logging.exception("Cosmos query failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")


@app.route(route="files", methods=["POST"])
def upload_file(req: func.HttpRequest) -> func.HttpResponse:
    """
    POST /api/files
    Body: JSON with { title, tags, filename, contentType, contentBase64 }
    Uploads file bytes to Blob Storage and inserts metadata into Cosmos DB.
    """
    try:
        # ---- Read env vars ----
        cosmos_endpoint = os.environ["COSMOS_ENDPOINT"]
        cosmos_key = os.environ["COSMOS_KEY"]
        cosmos_db = os.environ["COSMOS_DB"]
        cosmos_container = os.environ["COSMOS_CONTAINER"]

        storage_conn = os.environ["STORAGE_CONNECTION_STRING"]
        blob_container = os.environ["BLOB_CONTAINER"]

        # ---- Parse request JSON ----
        data = req.get_json()

        title = (data.get("title") or "").strip()
        tags = data.get("tags") or []
        filename = (data.get("filename") or "").strip()
        content_type = (data.get("contentType") or "application/octet-stream").strip()
        content_b64 = data.get("contentBase64")

        if not title or not filename or not content_b64:
            return func.HttpResponse(
                json.dumps({"error": "Missing required fields: title, filename, contentBase64"}),
                status_code=400,
                mimetype="application/json",
            )

        if not isinstance(tags, list):
            return func.HttpResponse(
                json.dumps({"error": "tags must be a JSON array"}),
                status_code=400,
                mimetype="application/json",
            )

        # ---- Decode file bytes ----
        try:
            file_bytes = base64.b64decode(content_b64, validate=True)
        except Exception:
            return func.HttpResponse(
                json.dumps({"error": "contentBase64 is not valid base64"}),
                status_code=400,
                mimetype="application/json",
            )

        # ---- Upload to Blob Storage ----
        file_id = str(uuid.uuid4())
        safe_name = filename.replace("\\", "_").replace("/", "_")
        blob_name = f"{file_id}_{safe_name}"  # stored inside container
        blob_path = f"{blob_container}/{blob_name}"  # what we store in Cosmos

        blob_service = BlobServiceClient.from_connection_string(storage_conn)
        container_client = blob_service.get_container_client(blob_container)

        # Optional: ensure container exists (safe if it already exists)
        try:
            container_client.create_container()
        except Exception:
            pass

        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(
            file_bytes,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

        # ---- Insert metadata into Cosmos ----
        uploaded_at = datetime.now(timezone.utc).isoformat()

        doc = {
            "id": file_id,
            "title": title,
            "tags": tags,
            "blobPath": blob_path,
            "uploadedAt": uploaded_at,
            "filename": filename,
            "contentType": content_type,
            "sizeBytes": len(file_bytes),
        }

        cosmos = CosmosClient(cosmos_endpoint, credential=cosmos_key)
        container = cosmos.get_database_client(cosmos_db).get_container_client(cosmos_container)
        container.create_item(body=doc)

        return func.HttpResponse(json.dumps(doc), status_code=201, mimetype="application/json")

    except Exception as e:
        logging.exception("Upload failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")
