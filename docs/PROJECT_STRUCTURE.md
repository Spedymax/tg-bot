# Project Structure Documentation

This document describes the new, refactored structure of the Telegram Bot Collection project.

## 🎯 Overview

The project has been completely refactored from a monolithic structure to a modular, maintainable architecture following Python best practices.

## 📁 Directory Structure

```
tg-bot/
├── src/                          # Main source code
│   ├── config/                   # Configuration files
│   │   ├── settings.py          # Environment settings
│   │   └── game_config.py       # Game configuration constants
│   ├── database/                 # Database management
│   │   ├── manager.py           # Database connection pooling
│   │   └── __init__.py          # Database package init
│   ├── handlers/                 # Command handlers
│   │   ├── game_handlers.py     # Game commands (pisunchik, casino, roll)
│   │   ├── admin_handlers.py    # Admin panel functionality
│   │   ├── shop_handlers.py     # Shop and inventory management
│   │   └── __init__.py          # Handlers package init
│   ├── models/                  # Data models
│   │   ├── player.py            # Player data model
│   │   └── __init__.py          # Models package init
│   ├── services/                # Business logic services
│   │   ├── player_service.py    # Player management with caching
│   │   ├── game_service.py      # Game logic implementation
│   │   └── __init__.py          # Services package init
│   ├── legacy/                  # Legacy BotFunctions (being refactored)
│   │   ├── BotFunctions/        # Original modular functions
│   │   │   ├── BotAnswer.py
│   │   │   ├── Rofl.py
│   │   │   ├── main_functions.py
│   │   │   ├── trivia.py
│   │   │   ├── helpers.py
│   │   │   └── stocks.py
│   │   ├── main_old.py          # Original monolithic main.py
│   │   └── __init__.py          # Legacy package init
│   ├── main.py                  # New modular bot entry point
│   └── __init__.py              # Source package init
├── assets/                      # Static assets
│   ├── data/                    # JSON data files
│   │   ├── char.json           # Character data
│   │   ├── plot.json           # Story/plot data
│   │   ├── shop.json           # Shop items
│   │   └── statuetki.json      # Statuetki data
│   ├── images/                  # Image assets
│   │   ├── statuetki/          # Statuetki images
│   │   ├── backgrounds/        # Background images
│   │   └── cats/               # Cat images
│   └── audio/                   # Audio files
│       └── pirat-songs/        # Pirate songs
├── scripts/                     # Utility scripts
│   ├── memories.py             # Memory diary bot
│   ├── btc.py                  # Bitcoin-related scripts
│   ├── love.py                 # Love bot script
│   └── commit.py               # Git automation
├── backups/                     # Database backups
│   ├── backup_*.json           # JSON backups
│   └── latest.dump             # Database dumps
├── docs/                        # Documentation
│   ├── PROJECT_STRUCTURE.md    # This file
│   ├── API.md                  # API documentation (future)
│   └── SETUP.md                # Setup instructions (future)
├── tests/                       # Test files
│   ├── unit/                   # Unit tests
│   ├── integration/            # Integration tests
│   └── conftest.py             # Pytest configuration
├── run.py                       # Main entry point
├── .env                         # Environment variables (not in git)
├── .env.example                 # Environment template
├── requirements.txt             # Python dependencies
├── README.md                    # Project documentation
├── .gitignore                   # Git ignore rules
└── Procfile                     # Deployment configuration
```

## 🏗️ Architecture Overview

### 1. **Separation of Concerns**
- **Handlers**: Manage Telegram bot commands and callbacks
- **Services**: Contain business logic and game mechanics
- **Models**: Define data structures with validation
- **Database**: Handle data persistence and queries
- **Config**: Manage configuration and constants

### 2. **Handler Organization**
- **GameHandlers**: Core game commands (pisunchik, casino, roll, theft)
- **AdminHandlers**: Administrative functions and panels
- **ShopHandlers**: Shop, inventory, and item management

### 3. **Database Architecture**
- **Connection Pooling**: Efficient database connections
- **Player Service**: Abstracted player data operations
- **Caching**: In-memory player data caching

### 4. **Configuration Management**
- **Environment Variables**: Secure credential storage
- **Game Constants**: Centralized game balance settings
- **Type Safety**: Type hints throughout the codebase

## 🔧 Key Improvements

### Before Refactoring:
- ❌ 2,651 lines in single main.py
- ❌ Global variables and shared state
- ❌ No type safety
- ❌ Hardcoded values
- ❌ Mixed concerns
- ❌ No error handling
- ❌ No logging

### After Refactoring:
- ✅ Modular structure (~1,700 lines across multiple files)
- ✅ Clean separation of concerns
- ✅ Type-safe data models
- ✅ Configuration management
- ✅ Database connection pooling
- ✅ Comprehensive error handling
- ✅ Proper logging
- ✅ Testable architecture

## 🚀 Running the Bot

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials (include OPENAI_API_KEY for AI features)
   ```

3. **Run the bot:**
   ```bash
   cd src
   python main.py
   ```

## 📝 Development Guidelines

1. **Adding New Commands:**
   - Add handler to appropriate handler class
   - Implement business logic in service layer
   - Update configuration if needed

2. **Database Changes:**
   - Update Player model if schema changes
   - Modify PlayerService for new operations
   - Use proper type hints

3. **Configuration:**
   - Add constants to GameConfig
   - Use Settings for environment variables
   - Never hardcode values

4. **Testing:**
   - Add tests to tests/ directory
   - Mock external dependencies
   - Test business logic separately

## 🔄 Migration Notes

The old main.py has been moved to `src/legacy/main_old.py` for reference. The legacy BotFunctions are in `src/legacy/` and should be gradually refactored to follow the new architecture.

## 📋 TODO

- [ ] Refactor remaining legacy modules
- [ ] Add comprehensive test suite
- [ ] Implement proper logging rotation
- [ ] Add database migrations
- [ ] Create API documentation
- [ ] Add performance monitoring
