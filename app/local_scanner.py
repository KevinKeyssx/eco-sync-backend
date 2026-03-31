"""
Local Storage Scanner — Analyzes the user's hard drive for waste files and supports dual deletion (permanent/trash).
"""

from __future__ import annotations

import logging
import os
import stat
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None

logger = logging.getLogger(__name__)

# Extensions considered waste by default
WASTE_EXTENSIONS = {
    '.tmp', '.temp', '.bak', '.old', '.log', '.cache',
    '.DS_Store', '.thumbs.db', '.~tmp'
}

# Heavy installer extensions
INSTALLER_EXTENSIONS = {'.msi', '.exe', '.dmg', '.iso', '.pkg', '.rpm', '.deb'}

LARGE_FILE_THRESHOLD_MB = 100
OLD_FILE_DAYS = 365


def get_default_directories() -> dict[str, str]:
    """Return standard directories to scan."""
    home = Path.home()
    return {
        "Descargas": str(home / "Downloads"),
        "Documentos": str(home / "Documents"),
        "Escritorio": str(home / "Desktop"),
        "Temporales (Sistema)": os.environ.get('TEMP', '/tmp'),
    }


def get_directory_sizes() -> list[dict[str, Any]]:
    """Quick pre-scan to calculate the size of default directories."""
    directories = get_default_directories()
    results = []

    for name, path_str in directories.items():
        path = Path(path_str)
        if not path.exists() or not path.is_dir():
            continue

        total_size = 0
        file_count = 0
        
        # Fast walk to just sum sizes
        try:
            for root, _, files in os.walk(path):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        total_size += os.path.getsize(file_path)
                        file_count += 1
                    except (OSError, PermissionError):
                        pass
        except PermissionError:
            pass

        size_mb = total_size / (1024 * 1024)
        results.append({
            "name": name,
            "path": path_str,
            "size_bytes": total_size,
            "size_str": f"{size_mb / 1024:.2f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB",
            "files_count": file_count
        })

    return results


def scan_local_paths(paths: list[str], config=None) -> dict[str, Any]:
    """Deep scan selected paths for waste files."""
    results: list[dict[str, Any]] = []
    total_waste_bytes = 0
    total_files_scanned = 0
    total_size_bytes = 0

    now = datetime.now(timezone.utc)
    
    # Defaults in case run locally without config
    min_size_mb = config.min_size_mb if config else LARGE_FILE_THRESHOLD_MB
    min_months_old = config.min_months_old if config else (OLD_FILE_DAYS // 30)
    opts = {
        'installers': config.include_installers if config else True,
        'temps': config.include_temps if config else True,
        'cache': config.include_cache if config else True
    }

    one_year_ago = now - timedelta(days=min_months_old * 30)

    for base_path_str in paths:
        base_path = Path(base_path_str)
        if not base_path.exists() or not base_path.is_dir():
            continue

        for root, dirs, files in os.walk(base_path):
            # Skip hidden/system directories completely to speed up
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('AppData', 'Windows', 'Program Files', 'Program Files (x86)', 'node_modules')]
            
            for file in files:
                total_files_scanned += 1
                file_path = os.path.join(root, file)
                
                try:
                    stat_info = os.stat(file_path)
                    size_bytes = stat_info.st_size
                    total_size_bytes += size_bytes
                    
                    # Only calculate waste for reasonably sized or relevant files
                    ext = Path(file).suffix.lower()
                    size_mb = size_bytes / (1024 * 1024)
                    
                    # File modification time
                    try:
                        mod_time = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc)
                    except:
                        mod_time = now

                    waste_category = None
                    waste_reason = ""

                    if opts['temps'] and (ext in WASTE_EXTENSIONS or file.startswith("~$")):
                        waste_category = "temporal"
                        waste_reason = "Archivo residual del sistema"
                    elif opts['installers'] and ext in INSTALLER_EXTENSIONS and size_mb >= min_size_mb and mod_time < one_year_ago:
                        waste_category = "pesado"
                        waste_reason = f"Instalador obsoleto ({size_mb:.0f} MB)"
                    elif size_mb >= min_size_mb and mod_time < one_year_ago:
                        waste_category = "antiguo"
                        waste_reason = f"Archivo pesado sin modificar desde {mod_time.strftime('%b %Y')}"
                    elif opts['cache'] and "cache" in root.lower() and mod_time < one_year_ago:
                        waste_category = "cache"
                        waste_reason = "Caché de aplicación antigua"
                    
                    is_waste = waste_category is not None

                    if is_waste:
                        total_waste_bytes += size_bytes
                        results.append({
                            "id": file_path, # Use full path as ID
                            "name": file,
                            "path": file_path,
                            "size_bytes": size_bytes,
                            "size_mb": round(size_mb, 2),
                            "modified_time": mod_time.isoformat(),
                            "is_waste": True,
                            "waste_category": waste_category,
                            "waste_reason": waste_reason,
                        })

                except (OSError, PermissionError):
                    # Cannot access file, skip
                    pass

    # Sort waste by size descending
    results.sort(key=lambda x: -x["size_bytes"])

    # CO₂ estimation: 0.5 kWh/GB/year * 0.475 kg CO₂/kWh
    total_waste_gb = total_waste_bytes / (1024 ** 3)
    co2_grams = total_waste_gb * 0.5 * 0.475 * 1000

    return {
        "total_files": total_files_scanned,
        "waste_files": len(results),
        "total_size_gb": round(total_size_bytes / (1024 ** 3), 3),
        "waste_size_gb": round(total_waste_gb, 3),
        "co2_grams_per_year": round(co2_grams, 2),
        "files": results,
    }


def delete_local_files(file_paths: list[str], permanent: bool = False) -> dict[str, int]:
    """Delete files permanently or send them to the recycle bin."""
    deleted = 0
    failed = 0

    for path_str in file_paths:
        path = Path(path_str)
        if not path.exists() or not path.is_file():
            failed += 1
            continue
            
        try:
            # First ensure the file is not read-only
            os.chmod(path, stat.S_IWRITE)
            
            if permanent:
                os.remove(path)
                logger.info("Permanently deleted local file: %s", path_str)
                deleted += 1
            else:
                if send2trash:
                    send2trash(path_str)
                    logger.info("Sent local file to trash: %s", path_str)
                    deleted += 1
                else:
                    logger.warning("send2trash not installed, falling back to permanent deletion")
                    os.remove(path)
                    deleted += 1
                    
        except Exception as exc:
            logger.error("Failed to delete local file %s: %s", path_str, exc)
            failed += 1

    return {"deleted": deleted, "failed": failed, "total": len(file_paths)}
