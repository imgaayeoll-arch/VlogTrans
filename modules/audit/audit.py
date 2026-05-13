import logging

logger = logging.getLogger(__name__)


def cleanup_temporary_files(temp_paths):
    """Remove temporary files after processing."""
    for path in temp_paths:
        logger.info(f"Cleaning up {path}")
