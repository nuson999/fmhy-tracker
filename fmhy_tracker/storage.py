"""Shared helpers for durable local files."""

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def atomic_write_text(destination: Path, content: str) -> None:
    """Write text beside its destination and replace it only when complete."""
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temporary_path = Path(temp_file.name)
            temp_file.write(content)
        os.replace(temporary_path, destination)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                logger.warning("Error removing temporary file: %s", cleanup_error)
        raise
