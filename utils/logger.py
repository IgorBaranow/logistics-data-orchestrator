import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_PATH = Path(__file__).resolve().parent.parent
SYS_LOG_DIR = BASE_PATH / "sys_logs"
SYS_LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_system_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_out = logging.StreamHandler(sys.stdout)
        console_out.setFormatter(formatter)
        logger.addHandler(console_out)

        fs_handler = RotatingFileHandler(
            filename=SYS_LOG_DIR / "integration_daemon.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fs_handler.setFormatter(formatter)
        logger.addHandler(fs_handler)

    return logger
