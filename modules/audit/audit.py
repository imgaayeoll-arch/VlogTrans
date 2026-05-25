import logging
import os
import shutil

logger = logging.getLogger(__name__)


def cleanup_temporary_files(temp_paths):
    """Remove temporary files after processing."""
    for path in temp_paths:
        try:
            if os.path.isfile(path):
                os.remove(path)
                logger.info(f"Removed file: {path}")
            elif os.path.isdir(path):
                shutil.rmtree(path)
                logger.info(f"Removed directory: {path}")
            else:
                logger.debug(f"Skipping non-existent path: {path}")
        except OSError as e:
            logger.warning(f"Failed to clean up {path}: {e}")
