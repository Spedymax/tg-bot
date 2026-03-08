import logging
import os
import time
from contextlib import asynccontextmanager

from psycopg_pool import AsyncConnectionPool
from config.settings import Settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        self._pool: AsyncConnectionPool | None = None
        self._connection_metrics = {
            'total_connections': 0,
            'active_connections': 0,
            'peak_connections': 0,
            'connection_errors': 0,
        }

    async def init_pool(self):
        """Initialize the async connection pool. Must be awaited before use."""
        WORKER_COUNT = int(os.getenv('GUNICORN_WORKERS', '4'))
        MAX_CONN_PER_WORKER = max(3, 20 // WORKER_COUNT)

        conninfo = (
            f"host={Settings.DB_CONFIG['host']} "
            f"dbname={Settings.DB_CONFIG['dbname']} "
            f"user={Settings.DB_CONFIG['user']} "
            f"password={Settings.DB_CONFIG['password']}"
        )

        self._pool = AsyncConnectionPool(
            conninfo=conninfo,
            min_size=1,
            max_size=MAX_CONN_PER_WORKER,
            open=False,
            kwargs={"autocommit": True},
        )
        await self._pool.open()
        logger.info(
            f"Async connection pool initialized with 1-{MAX_CONN_PER_WORKER} connections (worker-aware sizing)"
        )

    @asynccontextmanager
    async def connection(self):
        """Get a connection from the pool as an async context manager."""
        start_time = time.time()
        try:
            async with self._pool.connection() as conn:
                self._connection_metrics['total_connections'] += 1
                self._connection_metrics['active_connections'] += 1
                if self._connection_metrics['active_connections'] > self._connection_metrics['peak_connections']:
                    self._connection_metrics['peak_connections'] = self._connection_metrics['active_connections']

                get_time = time.time() - start_time
                if get_time > 1.0:
                    logger.warning(
                        f"Slow connection retrieval: {get_time:.2f}s, "
                        f"active: {self._connection_metrics['active_connections']}"
                    )

                try:
                    yield conn
                finally:
                    self._connection_metrics['active_connections'] = max(
                        0, self._connection_metrics['active_connections'] - 1
                    )
        except Exception:
            self._connection_metrics['connection_errors'] += 1
            raise

    async def execute_query(self, query, params=None):
        """Execute a query and return results for SELECT, or None for INSERT/UPDATE/DELETE."""
        try:
            async with self.connection() as conn:
                cursor = await conn.execute(query, params)
                if cursor.description:
                    return await cursor.fetchall()
                return None
        except Exception as error:
            logger.error(f"Error executing query: {error}")
            return None

    def get_pool_status(self):
        """Get current status of the connection pool."""
        return dict(self._connection_metrics)

    def log_pool_status(self):
        """Log current pool status for debugging."""
        status = self.get_pool_status()
        logger.info(f"Pool status: {status}")

        if status['active_connections'] > 15:
            logger.warning(
                f"High connection pool usage: {status['active_connections']}/20 connections active"
            )

        return status

    async def close_all_connections(self):
        """Close all connections in the pool."""
        logger.info("Closing all database connections")
        logger.info(f"Connection metrics: {self._connection_metrics}")
        if self._pool:
            await self._pool.close()
