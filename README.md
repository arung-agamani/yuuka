# Yuuka - Transaction Ledger Discord Bot

Yuuka is an intelligent Discord bot that helps you manage your personal finances through natural language transaction processing. It uses NLP to parse transaction messages and maintains a ledger with SQLite, providing insights, forecasts, and visualizations.

Also it weights 100kg.

## Features

- 📝 **Natural Language Processing** - Parse transactions from casual messages
- 💾 **SQLite Database** - Persistent ledger storage
- 📊 **Financial Forecasting** - Budget tracking and warnings before you go red
- 📈 **Burndown Charts** - Visual financial health tracking
- 📁 **Data Export** - Export to XLSX or CSV
- 🤖 **Discord Integration** - Slash commands and direct messaging

## Supported Transaction Formats

```
16k from gopay for commuting
52.500 from main pocket for lunch
transfer 1mil from account1 to account3
incoming salary 21m to main pocket
```

## Prerequisites

- Python 3.12 (recommended - Python 3.14 is not yet fully supported by all dependencies)
- Poetry (Python package manager)
- Discord Bot Token ([Get one here](https://discord.com/developers/applications))

> **Note:** Python 3.14 may cause issues with packages like `spacy`, `thinc`, and `blis` as prebuilt wheels are not yet available. Stick with Python 3.12 for the best experience.

## Installation

### 1. Install Python 3.12

Choose your preferred Python version manager:

<details>
<summary><b>Option A: Using uv (Recommended)</b></summary>

Modern, fast Python version manager written in Rust.

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Python 3.12
uv python install 3.12

# Verify installation
uv python list
```

When configuring Poetry later, use:
```bash
poetry env use ~/.local/share/uv/python/cpython-3.12.*/bin/python3
```

</details>

<details>
<summary><b>Option B: Using pyenv</b></summary>

Popular Python version manager for Unix-like systems.

**Installation:**

```bash
# macOS (using Homebrew)
brew install pyenv

# Linux (using pyenv-installer)
curl https://pyenv.run | bash
```

After installation, add to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
```

**Install Python 3.12:**

```bash
# Install Python 3.12
pyenv install 3.12

# Set as global default (optional)
pyenv global 3.12

# Or set for this project only
cd yuuka
pyenv local 3.12
```

When configuring Poetry later, use:
```bash
poetry env use $(pyenv which python3.12)
```

</details>

<details>
<summary><b>Option C: Using asdf</b></summary>

Universal version manager that handles multiple languages.

**Installation:**

```bash
# Install asdf
git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.14.0

# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
. "$HOME/.asdf/asdf.sh"
```

**Install Python plugin and Python 3.12:**

```bash
# Install Python plugin
asdf plugin add python

# Install Python 3.12
asdf install python 3.12.7

# Set globally (optional)
asdf global python 3.12.7

# Or set for this project only
cd yuuka
asdf local python 3.12.7
```

When configuring Poetry later, use:
```bash
poetry env use python3.12
```

</details>

<details>
<summary><b>Option D: System Package Manager</b></summary>

Use your operating system's package manager.

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev
```

**Fedora:**
```bash
sudo dnf install python3.12 python3.12-devel
```

**macOS (using Homebrew):**
```bash
brew install python@3.12
```

**Windows:**
1. Download from [python.org](https://www.python.org/downloads/)
2. Run the installer
3. **Important:** Check "Add Python to PATH" during installation

When configuring Poetry later, use:
```bash
poetry env use python3.12
```

</details>

### 2. Install Poetry

Choose the method that matches your Python installation:

<details>
<summary><b>Using uv</b></summary>

If you installed Python with uv:

```bash
uv tool install poetry
```

</details>

<details>
<summary><b>Using pipx (Recommended for pyenv/asdf/system Python)</b></summary>

```bash
# Install pipx first
python3.12 -m pip install --user pipx
python3.12 -m pipx ensurepath

# Install Poetry
pipx install poetry
```

</details>

<details>
<summary><b>Official installer</b></summary>

**macOS / Linux:**

```bash
curl -sSL https://install.python-poetry.org | python3.12 -
```

**Windows (PowerShell):**

```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -3.12 -
```

</details>

After installation, add Poetry to your PATH if it's not automatically added.
- **Linux/macOS:** `~/.local/bin`
- **Windows:** `%APPDATA%\Python\Scripts`

### 3. Clone or Download the Project

```bash
cd yuuka
```

### 4. Configure Poetry to Use Python 3.12

```bash
# Configure Poetry to use the Python 3.12 you installed
# (use the appropriate command from your installation method above)

# For uv:
poetry env use ~/.local/share/uv/python/cpython-3.12.*/bin/python3

# For pyenv:
poetry env use $(pyenv which python3.12)

# For asdf or system Python:
poetry env use python3.12

# Verify the Python version
poetry env info

# Configure Poetry to prefer binary packages (recommended - faster installation)
poetry config installer.prefer-binary true
```

### 5. Install Dependencies

```bash
poetry install
```

This will create a virtual environment and install all required packages including:
- discord.py
- spaCy
- matplotlib/seaborn
- openpyxl
- and more...

### 6. Download spaCy Language Model

```bash
poetry run python -m spacy download en_core_web_sm
```

### 7. Configure Your Bot Token

Copy the example environment file:

```bash
cp env.example .env
```

Edit `.env` and add your Discord bot token:

```env
DISCORD_BOT_TOKEN=your-bot-token-here
```

**To get a Discord bot token:**
1. Go to https://discord.com/developers/applications
2. Click "New Application"
3. Go to the "Bot" tab
4. Click "Add Bot"
5. Under "Token", click "Copy"
6. Enable "Message Content Intent" under "Privileged Gateway Intents"

## Running the Bot

### macOS / Linux

```bash
poetry run python -m yuuka.bot.runner
```

Or activate the virtual environment first:

```bash
poetry shell
python -m yuuka.bot.runner
```

### Windows

```powershell
poetry run python -m yuuka.bot.runner
```

Or activate the virtual environment first:

```powershell
poetry shell
python -m yuuka.bot.runner
```

## Usage

### Recording Transactions

**Via Slash Command:**
```
/parse 16k from gopay for commuting
```

**Via Direct Message:**
Just send the transaction message directly to the bot:
```
50k from wallet for lunch
```

**Via Mention in Server:**
```
@Yuuka 100k from bank for groceries
```

### Viewing Your Ledger

```
/history          - View recent transactions
/summary          - See income/expense totals
/balance          - View balances by account
```

### Budget & Forecasting

```
/budget daily_limit:50000 payday:25
/forecast         - Check if you'll make it to payday
/recap            - Get daily recap with burndown chart
```

### Data Management

```
/delete 123       - Delete transaction by ID
/export           - Export ledger to XLSX or CSV
```

### Help

```
/help             - Show all available commands
```

## Project Structure

```
yuuka/
├── yuuka/
│   ├── bot/
│   │   ├── cogs/          # Command handlers (modular)
│   │   ├── client.py      # Bot main class
│   │   └── runner.py      # Entry point
│   ├── db/
│   │   ├── models.py      # Database models
│   │   ├── repository.py  # Ledger operations
│   │   └── budget.py      # Budget configuration
│   ├── models/
│   │   └── transaction.py # Transaction data models
│   └── services/
│       ├── nlp_service.py # NLP parsing
│       ├── recap/         # Daily recap & charts
│       └── export.py      # Data export
├── data/                  # SQLite database (auto-created)
├── pyproject.toml         # Project dependencies
└── .env                   # Configuration (create from env.example)
```

## Database Location

The SQLite database is automatically created at:
```
yuuka/data/yuuka.db
```

## Troubleshooting

### "DISCORD_BOT_TOKEN environment variable is not set"
- Make sure you created a `.env` file from `env.example`
- Ensure your bot token is correctly pasted without quotes

### "Module not found" errors
- Run `poetry install` to ensure all dependencies are installed
- Make sure you're running commands with `poetry run` or inside `poetry shell`

### spaCy model not found
- Run `poetry run python -m spacy download en_core_web_sm`

### Packages building from source / taking too long to install
- Ensure you're using Python 3.12, not 3.14
- Configure Poetry to prefer binary packages: `poetry config installer.prefer-binary true`
- Recreate the environment: `poetry env remove --all` then `poetry install`

### Bot doesn't respond to messages
- Ensure "Message Content Intent" is enabled in Discord Developer Portal
- Make sure the bot has permission to read messages in the channel

### Permission errors on macOS/Linux
- You may need to make the runner executable: `chmod +x yuuka/bot/runner.py`

## Development

### Running Tests
```bash
poetry run pytest
```

### Code Formatting
```bash
poetry run ruff check .
```

### Testing NLP Parsing
```bash
poetry run python yuuka/main.py
```

## Contributing

This is a personal project, but suggestions and improvements are welcome!

## License

MIT License - see LICENSE file for details

## Support

For issues or questions, please create an issue in the repository.

---

**Note:** This bot stores data locally in SQLite. Make sure to backup your `data/yuuka.db` file regularly if you want to preserve your transaction history.
