"""
Google Drive Store
===================
Quiz data ko Google Drive ki ek folder mein ek JSON file ke roop mein
save/load karta hai, taaki Render pe naya deploy hone par bhi (jab local
filesystem reset ho jata hai) purane quizzes na khoyein.

Yeh do environment variables use karta hai:
- GOOGLE_SERVICE_ACCOUNT_JSON : Service account ki poori JSON key, ek
  single-line string ke roop mein.
- GDRIVE_FOLDER_ID            : Us Google Drive folder ki ID jise
  service account ke saath share kiya gaya hai.

Agar yeh dono set nahi hain, ya kisi bhi step par koi error aata hai,
to yeh module chup chaap None/False return karta hai — kabhi bhi bot ko
crash nahi karega. Bot phir local JSON file par fallback kar leta hai.
"""

import os
import io
import json

DRIVE_FILE_NAME = "quiz_store.json"

_drive_service = None  # lazy-loaded, cache karte hain taaki baar baar login na karna pade
_drive_unavailable_reason = None


def _get_service():
    """Google Drive service object banata/return karta hai. Fail hone par
    None return karta hai (exception kabhi bahar nahi jaane deta)."""
    global _drive_service, _drive_unavailable_reason

    if _drive_service is not None:
        return _drive_service
    if _drive_unavailable_reason is not None:
        return None  # pehle hi fail ho chuka hai, baar baar try nahi karte

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")

    if not creds_json or not folder_id:
        _drive_unavailable_reason = "GOOGLE_SERVICE_ACCOUNT_JSON ya GDRIVE_FOLDER_ID set nahi hai"
        print(f"[gdrive_store] Drive configure nahi hai: {_drive_unavailable_reason}")
        return None

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
        print("[gdrive_store] Drive service successfully ban gaya.")
        return _drive_service
    except Exception as e:
        _drive_unavailable_reason = f"Drive service banane me error: {e}"
        print(f"[gdrive_store] {_drive_unavailable_reason}")
        return None


def _find_file_id(service, folder_id):
    """Folder ke andar quiz_store.json dhundta hai. Nahi mile to None."""
    query = (
        f"name = '{DRIVE_FILE_NAME}' and '{folder_id}' in parents "
        "and trashed = false"
    )
    results = service.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


def load_from_drive():
    """Drive se quiz data load karta hai. Kuch bhi fail ho to None return
    karta hai (dict nahi, taaki caller fallback kar sake)."""
    service = _get_service()
    if service is None:
        return None

    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    try:
        from googleapiclient.http import MediaIoBaseDownload

        file_id = _find_file_id(service, folder_id)
        if not file_id:
            return None  # file abhi tak Drive pe bani hi nahi hai

        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        buffer.seek(0)
        data = json.loads(buffer.read().decode("utf-8"))
        if isinstance(data, dict):
            return data
        return None
    except Exception as e:
        print(f"[gdrive_store] Drive se load karne me error (local file use hogi): {e}")
        return None


def save_to_drive(data):
    """Quiz data ko Drive pe save karta hai (naya banata hai ya update
    karta hai). Success par True, fail par False return karta hai."""
    service = _get_service()
    if service is None:
        return False

    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    try:
        from googleapiclient.http import MediaIoBaseUpload

        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype="application/json", resumable=False)

        file_id = _find_file_id(service, folder_id)
        if file_id:
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            metadata = {"name": DRIVE_FILE_NAME, "parents": [folder_id]}
            service.files().create(body=metadata, media_body=media, fields="id").execute()
        return True
    except Exception as e:
        print(f"[gdrive_store] Drive pe save karne me error (sirf local file save hui): {e}")
        return False


def is_configured():
    """Batata hai ki Drive setup ho paya ya nahi (logging/debug ke liye)."""
    return _get_service() is not None
