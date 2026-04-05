import asyncio
import logging
import time

from config.settings import Settings

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Periodic self-health check that alerts admin on issues."""

    def __init__(self, bot, db_manager, player_service):
        self.bot = bot
        self.db = db_manager
        self.player_service = player_service
        self._task = None
        self._last_alert_time = 0
        self._alert_cooldown = 300  # 5 min between alerts

    def start(self):
        """Start the health monitoring loop."""
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Health monitor started (interval: 5 min)")

    async def _monitor_loop(self):
        """Run health checks every 5 minutes."""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                await self._check_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}")

    async def _check_health(self):
        """Run all health checks."""
        issues = []

        # Check database connectivity
        try:
            async with self.db.connection() as conn:
                cursor = await conn.execute("SELECT 1")
                await cursor.fetchone()
        except Exception as e:
            issues.append(f"Database: {e}")

        # Check Redis connectivity
        try:
            if self.player_service._redis:
                await self.player_service._redis.ping()
        except Exception as e:
            issues.append(f"Redis: {e}")

        # Check circuit breakers
        from services.circuit_breaker import ollama_breaker, gemini_breaker, together_breaker
        for name, breaker in [("Ollama", ollama_breaker), ("Gemini", gemini_breaker), ("Together", together_breaker)]:
            if breaker.state.value == "open":
                issues.append(f"{name} circuit breaker OPEN")

        # Check DB pool
        pool_status = self.db.get_pool_status()
        if pool_status.get('connection_errors', 0) > 10:
            issues.append(f"High DB connection errors: {pool_status['connection_errors']}")

        # Alert if issues found
        if issues and (time.time() - self._last_alert_time > self._alert_cooldown):
            self._last_alert_time = time.time()
            alert_text = "<b>Health Check Alert</b>\n\n" + "\n".join(issues)
            try:
                await self.bot.send_message(Settings.ADMIN_IDS[0], alert_text)
                logger.warning(f"Health alert sent: {issues}")
            except Exception as e:
                logger.error(f"Failed to send health alert: {e}")
