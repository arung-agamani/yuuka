"""
Configuration module for Yuuka bot.

Contains constants, settings, and configuration values used throughout the application.
"""

import os
from pathlib import Path

# Version
VERSION = "0.1.0"

# Application paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"

# Database configuration
DEFAULT_DB_PATH = DATA_DIR / "yuuka.db"
DB_TIMEOUT = 10.0  # seconds

# NLP configuration
DEFAULT_SPACY_MODEL = "en_core_web_sm"
MAX_TRANSACTION_TEXT_LENGTH = 500

# Transaction parsing
LOW_CONFIDENCE_THRESHOLD = 0.7
MIN_AMOUNT = 0.01
MAX_AMOUNT = 999_999_999_999.99  # ~1 trillion

# Budget defaults
DEFAULT_DAILY_LIMIT = 50000.0
DEFAULT_PAYDAY = 25
DEFAULT_WARNING_THRESHOLD = 0.2

# Discord configuration
DISCORD_MESSAGE_MAX_LENGTH = 2000
CONFIRMATION_TIMEOUT = 60.0  # seconds

# Export configuration
MAX_EXPORT_ENTRIES = 10000
EXPORT_FORMATS = ["xlsx", "csv"]

# Chart generation
CHART_DPI = 150
CHART_FORMAT = "png"
CHART_WIDTH = 12
CHART_HEIGHT = 8

# Logging configuration
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_FILE = "yuuka_bot.log"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Rate limiting (future enhancement)
MAX_COMMANDS_PER_MINUTE = 30
MAX_TRANSACTIONS_PER_DAY = 1000

# Validation constraints
MIN_PAYDAY = 1
MAX_PAYDAY = 31
MIN_WARNING_THRESHOLD = 0.0
MAX_WARNING_THRESHOLD = 1.0

# User input limits
MAX_ACCOUNT_NAME_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 200

# Database query limits
DEFAULT_HISTORY_LIMIT = 10
MAX_HISTORY_LIMIT = 25
DEFAULT_OFFSET = 0

# Error messages
ERROR_MESSAGES = {
    "invalid_token": "Invalid Discord bot token format",
    "spacy_not_found": "spaCy model not found. Please install it with: python -m spacy download {model}",
    "database_error": "Database error occurred. Please try again later.",
    "validation_error": "Invalid input. Please check your values and try again.",
    "permission_denied": "You don't have permission to perform this action.",
    "not_found": "The requested resource was not found.",
    "rate_limited": "Too many requests. Please slow down.",
    "internal_error": "An internal error occurred. Please try again.",
}

# Feature flags
ENABLE_RATE_LIMITING = False  # Not yet implemented
ENABLE_SCHEDULED_RECAPS = False  # Not yet implemented
ENABLE_BACKUP = False  # Not yet implemented


def ensure_directories():
    """Ensure required directories exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_log_level():
    """Get the configured log level."""
    import logging

    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(LOG_LEVEL.upper(), logging.INFO)
