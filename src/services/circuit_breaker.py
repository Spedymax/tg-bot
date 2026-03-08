import time
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Simple circuit breaker for external service calls."""

    def __init__(self, name: str, failure_threshold: int = 5,
                 recovery_timeout: int = 60, half_open_max: int = 1):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout  # seconds before trying again
        self.half_open_max = half_open_max

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if self._last_failure_time and (time.time() - self._last_failure_time) >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(f"CircuitBreaker [{self.name}]: OPEN → HALF_OPEN (recovery timeout elapsed)")
        return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        current = self.state
        if current == CircuitState.CLOSED:
            return True
        if current == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.half_open_max:
                self._half_open_calls += 1
                return True
            return False
        return False  # OPEN

    def record_success(self):
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info(f"CircuitBreaker [{self.name}]: HALF_OPEN → CLOSED (success)")
        self._state = CircuitState.CLOSED
        self._failure_count = 0

    def record_failure(self):
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            if self._state != CircuitState.OPEN:
                logger.warning(f"CircuitBreaker [{self.name}]: → OPEN (failures={self._failure_count})")
                from services.metrics import metrics
                metrics.record_circuit_trip(self.name)
            self._state = CircuitState.OPEN
        elif self._state == CircuitState.HALF_OPEN:
            logger.warning(f"CircuitBreaker [{self.name}]: HALF_OPEN → OPEN (failed during recovery)")
            self._state = CircuitState.OPEN


# Shared instances for external services
ollama_breaker = CircuitBreaker("ollama", failure_threshold=3, recovery_timeout=120)
gemini_breaker = CircuitBreaker("gemini", failure_threshold=5, recovery_timeout=60)
openclaw_breaker = CircuitBreaker("openclaw", failure_threshold=3, recovery_timeout=120)
