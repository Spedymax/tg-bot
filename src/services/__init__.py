# Import services with graceful handling of missing dependencies

__all__ = []

# Core services (should always be available)
try:
    from .game_service import GameService
    __all__.append('GameService')
except ImportError:
    pass

# Services with external dependencies
try:
    from .spotify_service import SpotifyService
    __all__.append('SpotifyService')
except ImportError:
    pass

try:
    from .tournament_service import TournamentService
    __all__.append('TournamentService')
except ImportError:
    pass

try:
    from .stock_service import StockService
    __all__.append('StockService')
except ImportError:
    pass

try:
    from .crypto_service import CryptoService
    __all__.append('CryptoService')
except ImportError:
    pass

try:
    from .messaging_service import MessagingService
    __all__.append('MessagingService')
except ImportError:
    pass

try:
    from .trivia_service import TriviaService
    __all__.append('TriviaService')
except ImportError:
    pass

try:
    from .bot_response_service import BotResponseService
    __all__.append('BotResponseService')
except ImportError:
    pass

try:
    from .database_service import DatabaseService
    __all__.append('DatabaseService')
except ImportError:
    pass

# Services package
