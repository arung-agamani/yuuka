"""
Bot runner script for Yuuka Discord Bot.

This module handles configuration loading and bot startup.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .client import create_bot


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

    return token


def run():
    """Run the Discord bot."""
    # Load .env file if it exists
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment from {env_path}")

    token = get_token()

    print("Starting Yuuka Discord Bot...")
    bot = create_bot()

    try:
        bot.run(token)
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error running bot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run()
