import azure.functions as func
import logging
import json
import os
import base64
import uuid
from datetime import datetime, timezone
import requests

from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient, ContentSettings

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Connects Azure Cosmos Storage
def get_cosmos_container():
    endpoint = os.environ["COSMOS_ENDPOINT"]
    key = os.environ["COSMOS_KEY"]
    db_name = os.environ["COSMOS_DB"]
    container_name = os.environ["COSMOS_CONTAINER"]

    client = CosmosClient(endpoint, credential=key)
    return client.get_database_client(db_name).get_container_client(container_name)

# Connects Azure Blob Storage
def get_blob_container_client():
    storage_conn = os.environ["STORAGE_CONNECTION_STRING"]
    blob_container = os.environ["BLOB_CONTAINER"]

    blob_service = BlobServiceClient.from_connection_string(storage_conn)
    return blob_service.get_container_client(blob_container)

# Azure AI Search Helpers
def get_search_config():
    return {
        "endpoint": os.environ["SEARCH_ENDPOINT"].rstrip("/"),
        "key": os.environ["SEARCH_ADMIN_KEY"],
        "index": os.environ["SEARCH_INDEX"],
        "api_version": "2023-07-01-Preview"
    }

def search_headers():
    cfg = get_search_config()
    return {
        "Content-Type": "application/json",
        "api-key": cfg["key"]
    }

def ai_search_index(action: str, doc: dict):
    """
    action: mergeOrUpload | merge | delete
    doc: must include at least {"id": "..."} for delete, and fields for merge/mergeOrUpload
    """
    cfg = get_search_config()
    url = f'{cfg["endpoint"]}/indexes/{cfg["index"]}/docs/index?api-version={cfg["api_version"]}'
    payload = {"value": [{"@search.action": action, **doc}]}

    # Best-effort indexing: if Search is down, API shouldn't fully fail CW2 demo
    try:
        resp = requests.post(url, headers=search_headers(), json=payload, timeout=10)
        if resp.status_code >= 400:
            logging.warning("AI Search index action failed (%s): %s", resp.status_code, resp.text)
    except Exception as e:
        logging.warning("AI Search request failed: %s", str(e))

# REST API and CRUD Operations
@app.route(route="list_files", methods=["GET"])  # Lists all files
def list_files(req: func.HttpRequest) -> func.HttpResponse:
    try:
        endpoint = os.environ["COSMOS_ENDPOINT"]
        key = os.environ["COSMOS_KEY"]
        db_name = os.environ["COSMOS_DB"]
        container_name = os.environ["COSMOS_CONTAINER"]

        client = CosmosClient(endpoint, credential=key)
        container = client.get_database_client(db_name).get_container_client(container_name)

        query = "SELECT c.id, c.title, c.description, c.institution, c.tags, c.blobPath, c.uploadedAt FROM c"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))

        return func.HttpResponse(json.dumps(items), status_code=200, mimetype="application/json")

    except Exception as e:
        logging.exception("Cosmos query failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")


@app.route(route="files", methods=["POST"])  # Upload new files
def upload_file(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # Reads environmental variables from Azure
        cosmos_endpoint = os.environ["COSMOS_ENDPOINT"]
        cosmos_key = os.environ["COSMOS_KEY"]
        cosmos_db = os.environ["COSMOS_DB"]
        cosmos_container = os.environ["COSMOS_CONTAINER"]

        storage_conn = os.environ["STORAGE_CONNECTION_STRING"]
        blob_container = os.environ["BLOB_CONTAINER"]

        # JSON Parse Request
        data = req.get_json()

        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        tags = data.get("tags") or []
        institution = (data.get("institution") or "").strip()
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

        try:
            file_bytes = base64.b64decode(content_b64, validate=True)
        except Exception:
            return func.HttpResponse(
                json.dumps({"error": "contentBase64 is not valid base64"}),
                status_code=400,
                mimetype="application/json",
            )

        # Upload File to Blob Storage
        file_id = str(uuid.uuid4())
        safe_name = filename.replace("\\", "_").replace("/", "_")
        blob_name = f"{file_id}_{safe_name}"
        blob_path = f"{blob_container}/{blob_name}"

        blob_service = BlobServiceClient.from_connection_string(storage_conn)
        container_client = blob_service.get_container_client(blob_container)

        # Exception Error Handling, Checking if Container exists
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

        # Inserts metadata into CosmosDB
        uploaded_at = datetime.now(timezone.utc).isoformat()

        doc = {
            "id": file_id,
            "title": title,
            "description": description,
            "institution": institution,
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

        # Index Metadata into Azure AI Search (Advanced Feature)
        ai_search_index("mergeOrUpload", {
            "id": doc["id"],
            "title": doc.get("title"),
            "description": doc.get("description"),
            "institution": doc.get("institution"),
            "tags": doc.get("tags"),
            "uploadedAt": doc.get("uploadedAt"),
            "blobPath": doc.get("blobPath"),
        })

        return func.HttpResponse(json.dumps(doc), status_code=201, mimetype="application/json")

    except Exception as e:
        logging.exception("Upload failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")


@app.route(route="files/{id}", methods=["PATCH"])  # Updating/Editting Details of File
def update_file(req: func.HttpRequest) -> func.HttpResponse:
    try:
        file_id = req.route_params.get("id")
        if not file_id:
            return func.HttpResponse(
                json.dumps({"error": "Missing id in route"}),
                status_code=400,
                mimetype="application/json",
            )

        # JSON Parse Request
        data = req.get_json()

        title = data.get("title")
        description = data.get("description")
        tags = data.get("tags")
        institution = data.get("institution")

        if tags is not None and not isinstance(tags, list):
            return func.HttpResponse(
                json.dumps({"error": "tags must be a JSON array"}),
                status_code=400,
                mimetype="application/json",
            )

        container = get_cosmos_container()

        # Partition key is "/id", set in Azure
        item = container.read_item(item=file_id, partition_key=file_id)

        if title is not None:
            item["title"] = str(title).strip()

        if description is not None:
            item["description"] = str(description).strip()

        if tags is not None:
            item["tags"] = [str(t).strip() for t in tags if str(t).strip()]

        if institution is not None:
            item["institution"] = str(institution).strip()

        updated = container.replace_item(item=file_id, body=item)

        # Update Metadata in Azure AI Search (Advanced Feature)
        ai_search_index("merge", {
            "id": updated["id"],
            "title": updated.get("title"),
            "description": updated.get("description"),
            "institution": updated.get("institution"),
            "tags": updated.get("tags"),
        })

        return func.HttpResponse(json.dumps(updated), status_code=200, mimetype="application/json")

    except Exception as e:
        logging.exception("Update failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")


@app.route(route="files/{id}", methods=["DELETE"])  # Delete File by ID
def delete_file(req: func.HttpRequest) -> func.HttpResponse:
    try:
        file_id = req.route_params.get("id")
        if not file_id:
            return func.HttpResponse(
                json.dumps({"error": "Missing id in route"}),
                status_code=400,
                mimetype="application/json",
            )

        cosmos_container = get_cosmos_container()

        # Reads item by id, to ensure it matches
        item = cosmos_container.read_item(item=file_id, partition_key=file_id)
        blob_path = item.get("blobPath") or ""

        blob_name = blob_path.split("/", 1)[1] if "/" in blob_path else ""

        if blob_name:
            blob_container_client = get_blob_container_client()
            blob_client = blob_container_client.get_blob_client(blob_name)
            try:
                blob_client.delete_blob()
            except Exception:
                logging.warning("Blob delete failed or blob missing for id=%s", file_id)

        cosmos_container.delete_item(item=file_id, partition_key=file_id)

        # Remove from Azure AI Search Index (Advanced Feature)
        ai_search_index("delete", {"id": file_id})

        return func.HttpResponse(
            json.dumps({"deleted": True, "id": file_id}),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logging.exception("Delete failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")


@app.route(route="search", methods=["GET"])  # Search Files (Metadata Only)
def search_files(req: func.HttpRequest) -> func.HttpResponse:
    try:
        q = req.params.get("q")
        if not q:
            return func.HttpResponse(
                json.dumps({"error": "Missing query parameter: q"}),
                status_code=400,
                mimetype="application/json",
            )

        cfg = get_search_config()
        url = f'{cfg["endpoint"]}/indexes/{cfg["index"]}/docs/search?api-version={cfg["api_version"]}'

        res = requests.post(
            url,
            headers=search_headers(),
            json={
                "search": q,
                "searchFields": "title,description,institution,tags",
                "top": 20
            },
            timeout=10
        )

        if res.status_code >= 400:
            logging.warning("AI Search query failed (%s): %s", res.status_code, res.text)
            return func.HttpResponse(
                json.dumps({"error": "Search query failed", "details": res.text}),
                status_code=500,
                mimetype="application/json",
            )

        results = res.json().get("value", [])
        return func.HttpResponse(json.dumps(results), status_code=200, mimetype="application/json")

    except Exception as e:
        logging.exception("Search failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, mimetype="application/json")
