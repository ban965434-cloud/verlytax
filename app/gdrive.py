"""
Verlytax OS v4 — Google Drive Back-Office Engine (Brain)

Auto-creates carrier folder structure in Google Drive on trial activation.
Mirrors the manual folder layout from Delta's notes.

Folder structure created per carrier:
  {ROOT_FOLDER}/
  └── {YYYY-MM} {Month Name}/         ← monthly folder (shared across all carriers)
      └── MC#{mc_number} - {name}/    ← carrier root
          ├── Carrier Packet/
          ├── BOL + POD/
          ├── Invoices/
          └── Compliance/

Required env vars:
  GOOGLE_SERVICE_ACCOUNT_JSON  — base64-encoded service account JSON key
  GOOGLE_DRIVE_ROOT_FOLDER_ID  — ID of the DispatchClients root folder in Drive
"""

import os
import json
import base64
from datetime import datetime


def _get_drive_service():
    """
    Build Google Drive API client from service account JSON stored in env.
    Returns None gracefully if credentials are not configured.
    """
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        return None

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        # Accept raw JSON string OR base64-encoded JSON
        try:
            creds_dict = json.loads(raw)
        except json.JSONDecodeError:
            creds_dict = json.loads(base64.b64decode(raw).decode("utf-8"))

        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    """
    Find an existing folder by name under parent_id, or create it.
    Returns the folder ID.
    """
    query = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def create_carrier_drive_folder(carrier_name: str, mc_number: str) -> dict:
    """
    Brain auto-creates the full carrier folder structure in Google Drive.
    Called by Brain on trial activation.

    Returns:
        {"status": "created", "folder_id": "...", "folder_name": "..."}
        {"status": "skipped", "reason": "..."}
        {"status": "error", "reason": "..."}
    """
    root_folder_id = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
    if not root_folder_id:
        return {"status": "skipped", "reason": "GOOGLE_DRIVE_ROOT_FOLDER_ID not configured"}

    service = _get_drive_service()
    if not service:
        return {"status": "skipped", "reason": "Google Drive credentials not configured"}

    try:
        now = datetime.utcnow()
        month_folder_name = now.strftime("%m-%B")   # e.g. "03-March"

        # 1. Get or create monthly folder under root
        month_folder_id = _get_or_create_folder(service, month_folder_name, root_folder_id)

        # 2. Create carrier folder under month
        carrier_folder_name = f"MC#{mc_number} - {carrier_name}"
        carrier_folder_id = _get_or_create_folder(service, carrier_folder_name, month_folder_id)

        # 3. Create subfolders inside carrier folder
        subfolders = ["Carrier Packet", "BOL + POD", "Invoices", "Compliance"]
        for subfolder in subfolders:
            _get_or_create_folder(service, subfolder, carrier_folder_id)

        return {
            "status": "created",
            "folder_id": carrier_folder_id,
            "folder_name": carrier_folder_name,
            "month_folder": month_folder_name,
        }

    except Exception as e:
        return {"status": "error", "reason": str(e)}


def ensure_top_level_structure() -> dict:
    """
    Brain one-time setup — creates the top-level folder structure if it doesn't exist.
    Call once on first deploy.

    Creates under ROOT:
      - Broker/Carrier Packet
      - Company Profile & Docs
      - Miscellaneous
      - 01-January ... 12-December (monthly folders)
    """
    root_folder_id = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
    if not root_folder_id:
        return {"status": "skipped", "reason": "GOOGLE_DRIVE_ROOT_FOLDER_ID not configured"}

    service = _get_drive_service()
    if not service:
        return {"status": "skipped", "reason": "Google Drive credentials not configured"}

    try:
        top_level = [
            "Broker/Carrier Packet",
            "Company Profile & Docs",
            "Miscellaneous",
            "SOPs",                  # Delta uploads SOP PDFs here
            "Transcripts",           # Erin/Retell call transcripts
            "Training + Media",      # Screenshots, training pictures, recordings
            "01-January", "02-February", "03-March", "04-April",
            "05-May", "06-June", "07-July", "08-August",
            "09-September", "10-October", "11-November", "12-December",
        ]
        created = []
        for folder_name in top_level:
            _get_or_create_folder(service, folder_name, root_folder_id)
            created.append(folder_name)

        return {"status": "ok", "folders_created": created}
    except Exception as e:
        return {"status": "error", "reason": str(e)}
