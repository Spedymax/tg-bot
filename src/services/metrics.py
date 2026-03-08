import time
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class BotMetrics:
    """Lightweight in-process metrics collector. No external dependencies."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.start_time = time.time()
        self.command_counts = defaultdict(int)        # command -> count
        self.command_errors = defaultdict(int)         # command -> error count
        self.command_latency_sum = defaultdict(float)  # command -> total ms
        self.command_latency_count = defaultdict(int)  # command -> count for avg
        self.active_users = set()                      # unique user IDs seen
        self.circuit_breaker_trips = defaultdict(int)  # service -> trip count
        self._db_query_count = 0
        self._db_error_count = 0

    def record_command(self, command: str, user_id: int, latency_ms: float, error: bool = False):
        """Record a command execution."""
        self.command_counts[command] += 1
        self.command_latency_sum[command] += latency_ms
        self.command_latency_count[command] += 1
        self.active_users.add(user_id)
        if error:
            self.command_errors[command] += 1

    def record_db_query(self, error: bool = False):
        """Record a database query."""
        self._db_query_count += 1
        if error:
            self._db_error_count += 1

    def record_circuit_trip(self, service: str):
        """Record a circuit breaker trip."""
        self.circuit_breaker_trips[service] += 1

    def get_summary(self) -> dict:
        """Get a summary of all metrics."""
        uptime = time.time() - self.start_time
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)

        # Top 10 commands by count
        top_commands = sorted(self.command_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        # Commands with errors
        error_commands = {cmd: cnt for cmd, cnt in self.command_errors.items() if cnt > 0}

        # Average latencies
        avg_latencies = {}
        for cmd in self.command_latency_count:
            if self.command_latency_count[cmd] > 0:
                avg_latencies[cmd] = self.command_latency_sum[cmd] / self.command_latency_count[cmd]

        return {
            'uptime': f"{hours}h {minutes}m",
            'uptime_seconds': int(uptime),
            'unique_users': len(self.active_users),
            'total_commands': sum(self.command_counts.values()),
            'total_errors': sum(self.command_errors.values()),
            'top_commands': top_commands,
            'error_commands': error_commands,
            'avg_latency_ms': avg_latencies,
            'db_queries': self._db_query_count,
            'db_errors': self._db_error_count,
            'circuit_trips': dict(self.circuit_breaker_trips),
        }

    def format_report(self) -> str:
        """Format metrics as a human-readable Telegram message."""
        s = self.get_summary()
        lines = [
            f"<b>Bot Metrics</b>",
            f"",
            f"Uptime: {s['uptime']}",
            f"Unique users: {s['unique_users']}",
            f"Total commands: {s['total_commands']}",
            f"Total errors: {s['total_errors']}",
            f"DB queries: {s['db_queries']} (errors: {s['db_errors']})",
        ]

        if s['circuit_trips']:
            lines.append(f"Circuit trips: {s['circuit_trips']}")

        if s['top_commands']:
            lines.append(f"\n<b>Top Commands:</b>")
            for cmd, cnt in s['top_commands'][:5]:
                avg = s['avg_latency_ms'].get(cmd, 0)
                errs = s['error_commands'].get(cmd, 0)
                err_str = f" err:{errs}" if errs else ""
                lines.append(f"  {cmd}: {cnt}x ({avg:.0f}ms avg){err_str}")

        return "\n".join(lines)


# Singleton instance
metrics = BotMetrics()
