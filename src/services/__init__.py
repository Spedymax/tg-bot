# Import services with graceful handling of missing dependencies

__all__ = []

# Core services (should always be available)
try:
    from .game_service import GameService
    __all__.append('GameService')
except Exception:
    pass

# Services with external dependencies
try:
    from .spotify_service import SpotifyService
    __all__.append('SpotifyService')
except Exception:
    pass

try:
    from .tournament_service import TournamentService
    __all__.append('TournamentService')
except Exception:
    pass

try:
    from .stock_service import StockService
    __all__.append('StockService')
except Exception:
    pass

try:
    from .crypto_service import CryptoService
    __all__.append('CryptoService')
except Exception:
    pass

try:
    from .messaging_service import MessagingService
    __all__.append('MessagingService')
except Exception:
    pass

try:
    from .trivia_service import TriviaService
    __all__.append('TriviaService')
except Exception:
    pass

try:
    from .bot_response_service import BotResponseService
    __all__.append('BotResponseService')
except Exception:
    pass

try:
    from .database_service import DatabaseService
    __all__.append('DatabaseService')
except Exception:
    pass

# Services package
