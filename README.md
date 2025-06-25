# Telegram Bot Collection

A collection of Telegram bots with gaming features, memory diary functionality, and various utilities.

## 🚨 Security Notice

**IMPORTANT**: This repository has been updated to use environment variables for sensitive data. 

### Before Running:
1. Create a `.env` file based on `.env.example`
2. Fill in your actual credentials (tokens, passwords, etc.)
3. Never commit real credentials to version control

## Features

### Main Bot (`main.py`)
- 🎮 Mini games with BTC currency system
- 📊 User stats and leaderboards  
- 🎯 Trivia questions with scoring
- 🛒 Virtual shop with items and upgrades
- 📈 Stock trading simulation
- 🏆 Achievement system
- 🎲 Dice rolling with effects
- 🔧 Admin panel for user management

### Memory Bot (`memories.py`)
- 📝 Personal diary for weekly thoughts
- 🔐 Password-protected entries
- 📅 Scheduled reminders
- 📊 Memory statistics
- 🗂️ Organized memory browsing

## Installation

### 1. Clone and Setup
```bash
git clone <repository-url>
cd tg-bot
pip install -r requirements.txt
```

### 2. Environment Configuration
```bash
# Copy the environment template
cp .env.example .env

# Edit .env with your actual credentials
# DO NOT use the example values in production!
```

### 3. Required Environment Variables

#### Bot Tokens
- `TELEGRAM_BOT_TOKEN` - Main bot token from @BotFather
- `MEMORY_BOT_TOKEN` - Memory bot token from @BotFather

#### Database Configuration
- `DB_HOST` - Database host (default: localhost)
- `DB_NAME` - Database name (default: server-tg-pisunchik)
- `DB_USER` - Database username (default: postgres)
- `DB_PASSWORD` - Database password (REQUIRED)

#### External APIs (Optional)
- `SPOTIFY_CLIENT_ID` - Spotify API client ID
- `SPOTIFY_CLIENT_SECRET` - Spotify API client secret
- `OPENAI_API_KEY` - OpenAI API key for AI features

### 4. Database Setup

Ensure PostgreSQL is installed and running:
```bash
# Create database
psql -U postgres -c "CREATE DATABASE \"server-tg-pisunchik\";"

# The bots will create necessary tables automatically
```

### 5. Run the Bots

```bash
# Main bot
python main.py

# Memory bot (in separate terminal)
python memories.py
```

## Security Best Practices

### ✅ Do:
- Use environment variables for all sensitive data
- Regularly rotate bot tokens and API keys
- Keep your `.env` file private and secure
- Use different credentials for development/production
- Implement proper access controls for admin features

### ❌ Don't:
- Commit credentials to version control
- Share bot tokens publicly
- Use production credentials in development
- Hardcode sensitive data in source code

## Project Structure

```
tg-bot/
├── main.py              # Main gaming bot
├── memories.py          # Memory diary bot
├── BotFunctions/        # Modular bot functions
│   ├── trivia.py       # Quiz functionality
│   ├── stocks.py       # Stock trading
│   ├── main_functions.py
│   └── ...
├── data/               # JSON data files
├── requirements.txt    # Python dependencies
├── .env.example       # Environment template
├── .gitignore         # Git ignore rules
└── README.md          # This file
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Ensure no credentials are committed
4. Test with your own bot tokens
5. Submit a pull request

## License

This project is for educational purposes. Please respect API terms of service.

---

**⚠️ Remember: Keep your credentials secure and never share them publicly!**
