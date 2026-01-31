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

- Python 3.10 or higher
- Poetry (Python package manager)
- Discord Bot Token ([Get one here](https://discord.com/developers/applications))

## Installation

### 1. Install Poetry

#### macOS / Linux

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

#### Windows (PowerShell)

```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```

After installation, add Poetry to your PATH if it's not automatically added.

### 2. Clone or Download the Project

```bash
cd yuuka
```

### 3. Install Dependencies

```bash
poetry install
```

This will create a virtual environment and install all required packages including:
- discord.py
- spaCy
- matplotlib/seaborn
- openpyxl
- and more...

### 4. Download spaCy Language Model

```bash
poetry run python -m spacy download en_core_web_sm
```

### 5. Configure Your Bot Token

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
