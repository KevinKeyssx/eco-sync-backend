"""
Google Drive API client — handles OAuth2 authentication and file operations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# File extensions considered "waste" by default
WASTE_EXTENSIONS = {
    '.tmp', '.temp', '.bak', '.old', '.log', '.cache',
    '.dmg', '.iso', '.exe', '.msi', '.deb', '.rpm',
    '.DS_Store', '.thumbs.db',
}

LARGE_FILE_THRESHOLD_MB = 100  # Files bigger than this are flagged


class GoogleDriveClient:
    """Wrapper around the Google Drive API v3."""

    def __init__(self, access_token: str) -> None:
        creds = Credentials(token=access_token)
        self._service = build("drive", "v3", credentials=creds)

    def get_storage_quota(self) -> dict[str, Any]:
        """Return storage quota info."""
        about = self._service.about().get(fields="storageQuota,user").execute()
        quota = about.get("storageQuota", {})
        user = about.get("user", {})
        return {
            "total_bytes": int(quota.get("limit", 0)),
            "used_bytes": int(quota.get("usage", 0)),
            "trash_bytes": int(quota.get("usageInDriveTrash", 0)),
            "user_email": user.get("emailAddress", ""),
            "user_name": user.get("displayName", ""),
        }

    def list_all_files(self) -> list[dict[str, Any]]:
        """List all files owned by the user with relevant metadata."""
        all_files: list[dict[str, Any]] = []
        page_token = None
        fields = "nextPageToken, files(id,name,mimeType,size,modifiedTime,viewedByMeTime,md5Checksum,trashed,ownedByMe,parents)"

        while True:
            response = (
                self._service.files()
                .list(
                    q="'me' in owners and trashed=false",
                    spaces="drive",
                    fields=fields,
                    pageSize=1000,
                    pageToken=page_token,
                    orderBy="modifiedTime desc",
                )
                .execute()
            )
            files = response.get("files", [])
            all_files.extend(files)
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info("Fetched %d files from Google Drive.", len(all_files))
        return all_files

    def scan_for_waste(self) -> dict[str, Any]:
        """Analyze all files and classify waste."""
        files = self.list_all_files()
        quota = self.get_storage_quota()
        now = datetime.now(timezone.utc)
        one_year_ago = now - timedelta(days=365)

        # Group by md5 to find duplicates
        md5_groups: dict[str, list[dict]] = {}
        for f in files:
            md5 = f.get("md5Checksum")
            if md5:
                md5_groups.setdefault(md5, []).append(f)

        duplicate_ids = set()
        for md5, group in md5_groups.items():
            if len(group) > 1:
                # Keep the newest, mark rest as duplicates
                sorted_group = sorted(group, key=lambda x: x.get("modifiedTime", ""), reverse=True)
                for dup in sorted_group[1:]:
                    duplicate_ids.add(dup["id"])

        results: list[dict[str, Any]] = []
        total_waste_bytes = 0

        for f in files:
            file_id = f["id"]
            name = f.get("name", "Unknown")
            size_bytes = int(f.get("size", 0))
            size_mb = size_bytes / (1024 * 1024)
            mime_type = f.get("mimeType", "")
            modified = f.get("modifiedTime", "")
            viewed = f.get("viewedByMeTime", "")

            # Determine waste category
            waste_category = None
            waste_reason = ""

            if file_id in duplicate_ids:
                waste_category = "duplicado"
                waste_reason = "Archivo duplicado (mismo contenido)"
            elif any(name.lower().endswith(ext) for ext in WASTE_EXTENSIONS):
                waste_category = "temporal"
                waste_reason = "Archivo temporal o de sistema"
            elif name.startswith("Copy of ") or name.startswith("Copia de "):
                waste_category = "duplicado"
                waste_reason = "Copia manual de archivo"
            elif size_mb > LARGE_FILE_THRESHOLD_MB and mime_type not in ("application/vnd.google-apps.folder",):
                waste_category = "pesado"
                waste_reason = f"Archivo grande ({size_mb:.0f} MB)"
            elif modified and viewed:
                try:
                    mod_dt = datetime.fromisoformat(modified.replace("Z", "+00:00"))
                    view_dt = datetime.fromisoformat(viewed.replace("Z", "+00:00"))
                    if mod_dt < one_year_ago and view_dt < one_year_ago:
                        waste_category = "antiguo"
                        waste_reason = f"Sin acceso desde {view_dt.strftime('%b %Y')}"
                except Exception:
                    pass
            elif modified and not viewed:
                try:
                    mod_dt = datetime.fromisoformat(modified.replace("Z", "+00:00"))
                    if mod_dt < one_year_ago:
                        waste_category = "antiguo"
                        waste_reason = f"Sin modificar desde {mod_dt.strftime('%b %Y')}"
                except Exception:
                    pass

            is_waste = waste_category is not None
            if is_waste:
                total_waste_bytes += size_bytes

            results.append({
                "id": file_id,
                "name": name,
                "size_bytes": size_bytes,
                "size_mb": round(size_mb, 2),
                "mime_type": mime_type,
                "modified_time": modified,
                "viewed_time": viewed,
                "is_waste": is_waste,
                "waste_category": waste_category or "activo",
                "waste_reason": waste_reason,
            })

        # Sort: waste first, then by size descending
        results.sort(key=lambda x: (not x["is_waste"], -x["size_bytes"]))

        # CO₂ estimation: 0.5 kWh/GB/year * 0.475 kg CO₂/kWh
        total_waste_gb = total_waste_bytes / (1024 ** 3)
        co2_grams = total_waste_gb * 0.5 * 0.475 * 1000  # Convert to grams

        return {
            "total_files": len(files),
            "waste_files": sum(1 for r in results if r["is_waste"]),
            "total_size_gb": round(sum(int(f.get("size", 0)) for f in files) / (1024 ** 3), 3),
            "waste_size_gb": round(total_waste_gb, 3),
            "co2_grams_per_year": round(co2_grams, 2),
            "quota": quota,
            "files": results,
        }

    def delete_file(self, file_id: str) -> None:
        """Move a file to trash."""
        self._service.files().update(
            fileId=file_id, body={"trashed": True}
        ).execute()
        logger.info("Trashed file: %s", file_id)

    def delete_file_permanently(self, file_id: str) -> None:
        """Permanently delete a file."""
        self._service.files().delete(fileId=file_id).execute()
        logger.info("Permanently deleted file: %s", file_id)
