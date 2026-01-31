"""
Bot runner script for Yuuka Discord Bot.

This module handles configuration loading and bot startup.
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from yuuka.config import (
    LOG_FILE,
    LOG_FORMAT,
    ensure_directories,
    get_log_level,
)

from .client import create_bot

# Ensure required directories exist
ensure_directories()

# Configure logging
logging.basicConfig(
    level=get_log_level(),
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def get_token() -> str:
    """
    Get the Discord bot token from environment variables.

    Returns:
        The bot token string.

    Raises:
        SystemExit: If the token is not found.
    """
    token = os.environ.get("DISCORD_BOT_TOKEN")

    if not token:
        logger.error("DISCORD_BOT_TOKEN environment variable is not set")
        print("Error: DISCORD_BOT_TOKEN environment variable is not set.")
        print("")
        print("Please set the token using one of these methods:")
        print("  1. Export it: export DISCORD_BOT_TOKEN='your-token-here'")
        print("  2. Create a .env file with: DISCORD_BOT_TOKEN=your-token-here")
        print("")
        print(
            "You can get a bot token from: https://discord.com/developers/applications"
        )
        sys.exit(1)

    # Validate token format (basic check)
    if not isinstance(token, str) or len(token) < 50:
        logger.error("Invalid Discord bot token format")
        print("Error: Discord bot token appears to be invalid.")
        print("Please check that you've copied the complete token.")
        sys.exit(1)

    logger.info("Bot token loaded successfully")
    return token


def run():
    """Run the Discord bot with comprehensive error handling."""
    try:
        # Load .env file if it exists
        env_path = Path(__file__).parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.info(f"Loaded environment from {env_path}")
            print(f"Loaded environment from {env_path}")
        else:
            logger.warning(f".env file not found at {env_path}")

        token = get_token()

        logger.info("Starting Yuuka Discord Bot...")
        print("Starting Yuuka Discord Bot...")

        try:
            bot = create_bot()
        except RuntimeError as e:
            logger.error(f"Failed to create bot: {e}", exc_info=True)
            print(f"\nError: {e}")
            print("\nPlease ensure all dependencies are installed correctly.")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Unexpected error creating bot: {e}", exc_info=True)
            print(f"\nUnexpected error: {e}")
            sys.exit(1)

        try:
            bot.run(token)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down...")
            print("\nShutting down...")
        except Exception as e:
            logger.error(f"Error running bot: {e}", exc_info=True)
            print(f"\nError running bot: {e}")
            print("Check yuuka_bot.log for more details.")
            sys.exit(1)
    except Exception as e:
        logger.critical(f"Critical error in run(): {e}", exc_info=True)
        print(f"\nCritical error: {e}")
        print("Check yuuka_bot.log for more details.")
        sys.exit(1)


if __name__ == "__main__":
    run()
