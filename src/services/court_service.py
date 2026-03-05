import json
import logging

logger = logging.getLogger(__name__)


class CourtService:
    def __init__(self, db):
        self.db = db

    # ── DB-хелперы ─────────────────────────────────────────────────────────

    def create_game(self, chat_id: int, defendant: str, crime: str) -> int:
        """Создать строку игры в БД, вернуть её id."""
        rows = self.db.execute_query(
            "INSERT INTO court_games (chat_id, defendant, crime) VALUES (%s, %s, %s) RETURNING id",
            (chat_id, defendant, crime),
        )
        return rows[0][0] if rows else None

    def get_active_game(self, chat_id: int) -> dict | None:
        """Вернуть активную игру для чата или None."""
        rows = self.db.execute_query(
            "SELECT id, chat_id, defendant, crime, prosecutor_id, lawyer_id, witness_id, "
            "prosecutor_cards, lawyer_cards, witness_cards, played_cards, current_round, "
            "prosecutor_cards_left, lawyer_cards_left, witness_cards_left, status "
            "FROM court_games WHERE chat_id = %s AND status NOT IN ('finished', 'aborted') "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0], "chat_id": r[1], "defendant": r[2], "crime": r[3],
            "prosecutor_id": r[4], "lawyer_id": r[5], "witness_id": r[6],
            "prosecutor_cards": r[7] or [], "lawyer_cards": r[8] or [],
            "witness_cards": r[9] or [], "played_cards": r[10] or [],
            "current_round": r[11], "prosecutor_cards_left": r[12],
            "lawyer_cards_left": r[13], "witness_cards_left": r[14],
            "status": r[15],
        }

    def assign_role(self, game_id: int, role: str, user_id: int):
        """Установить prosecutor_id / lawyer_id / witness_id."""
        queries = {
            "prosecutor": "UPDATE court_games SET prosecutor_id = %s WHERE id = %s",
            "lawyer": "UPDATE court_games SET lawyer_id = %s WHERE id = %s",
            "witness": "UPDATE court_games SET witness_id = %s WHERE id = %s",
        }
        self.db.execute_query(queries[role], (user_id, game_id))

    def set_status(self, game_id: int, status: str):
        self.db.execute_query("UPDATE court_games SET status = %s WHERE id = %s", (status, game_id))

    def save_cards(self, game_id: int, prosecutor_cards: list, lawyer_cards: list, witness_cards: list):
        self.db.execute_query(
            "UPDATE court_games SET prosecutor_cards=%s, lawyer_cards=%s, witness_cards=%s WHERE id=%s",
            (json.dumps(prosecutor_cards), json.dumps(lawyer_cards), json.dumps(witness_cards), game_id),
        )

    def record_played_card(self, game_id: int, role: str, card: str, round_num: int):
        """Добавить сыгранную карту в массив и уменьшить счётчик оставшихся."""
        game = self.get_active_game_by_id(game_id)
        if not game:
            logger.warning(f"Game {game_id} not found in record_played_card")
            return
        played = game.get("played_cards", [])
        if not isinstance(played, list):
            played = []
        played.append({"round": round_num, "role": role, "card": card})
        col_left = {"prosecutor": "prosecutor_cards_left", "lawyer": "lawyer_cards_left", "witness": "witness_cards_left"}[role]
        self.db.execute_query(
            f"UPDATE court_games SET played_cards=%s, {col_left}={col_left}-1 WHERE id=%s",
            (json.dumps(played), game_id),
        )

    def get_active_game_by_id(self, game_id: int) -> dict | None:
        rows = self.db.execute_query(
            "SELECT id, chat_id, defendant, crime, prosecutor_id, lawyer_id, witness_id, "
            "prosecutor_cards, lawyer_cards, witness_cards, played_cards, current_round, "
            "prosecutor_cards_left, lawyer_cards_left, witness_cards_left, status "
            "FROM court_games WHERE id = %s", (game_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0], "chat_id": r[1], "defendant": r[2], "crime": r[3],
            "prosecutor_id": r[4], "lawyer_id": r[5], "witness_id": r[6],
            "prosecutor_cards": r[7] or [], "lawyer_cards": r[8] or [],
            "witness_cards": r[9] or [], "played_cards": r[10] or [],
            "current_round": r[11], "prosecutor_cards_left": r[12],
            "lawyer_cards_left": r[13], "witness_cards_left": r[14],
            "status": r[15],
        }

    def advance_round(self, game_id: int, new_round: int):
        self.db.execute_query("UPDATE court_games SET current_round=%s WHERE id=%s", (new_round, game_id))

    def save_verdict(self, game_id: int, verdict: str):
        self.db.execute_query(
            "UPDATE court_games SET verdict=%s, status='finished' WHERE id=%s", (verdict, game_id)
        )

    def log_message(self, game_id: int, role: str, content: str, round_number: int = None):
        self.db.execute_query(
            "INSERT INTO court_messages (game_id, role, content, round_number) VALUES (%s, %s, %s, %s)",
            (game_id, role, content, round_number),
        )

    def get_session_messages(self, game_id: int) -> list[dict]:
        rows = self.db.execute_query(
            "SELECT role, content, round_number FROM court_messages WHERE game_id=%s ORDER BY created_at",
            (game_id,),
        )
        return [{"role": r[0], "content": r[1], "round": r[2]} for r in (rows or [])]
