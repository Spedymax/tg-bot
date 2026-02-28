"""Tournament manager wrapper for backwards compatibility"""
from src.services.tournament_service import TournamentService

# Alias for backwards compatibility
TournamentManager = TournamentService
