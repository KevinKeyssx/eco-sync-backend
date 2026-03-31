"""
Audit Logger — Módulo dedicado exclusivamente a registrar acciones destructivas.

Escribe en 'deletions.log' cada vez que un repositorio es eliminado,
con formato estricto: [TIMESTAMP] USER: <user> ACTION: DELETE REPO: <repo> STATUS: <status>
"""

import logging
import time

# Ruta del archivo de log de auditoría
LOG_FILE = "deletions.log"

# Logger dedicado (separado del root logger de FastAPI)
audit_logger = logging.getLogger("audit_logger")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False  # No mezclar con los logs de consola

# Handler que escribe en el archivo
_file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")

# Formato con timestamp UTC
_formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")
_formatter.converter = time.gmtime  # Forzar UTC
_file_handler.setFormatter(_formatter)

audit_logger.addHandler(_file_handler)


def log_deletion(username: str, repo_name: str, status: str = "SUCCESS") -> None:
    """
    Registra en deletions.log la eliminación de un repositorio.

    Formato:
        [2026-03-29T23:15:00Z] USER: octocat ACTION: DELETE REPO: old-project STATUS: SUCCESS
    """
    audit_logger.info(
        "USER: %s ACTION: DELETE REPO: %s STATUS: %s",
        username,
        repo_name,
        status,
    )
