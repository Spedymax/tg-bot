import logging
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool
from config.settings import Settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        self.connection_pool = psycopg2.pool.SimpleConnectionPool(1, 20, **Settings.DB_CONFIG)

    def get_connection(self):
        return self.connection_pool.getconn()

    def release_connection(self, connection):
        self.connection_pool.putconn(connection)

    def close_all_connections(self):
        self.connection_pool.closeall()

    @contextmanager
    def get_connection_context(self):
        """Context manager for safe connection handling."""
        connection = self.get_connection()
        try:
            yield connection
        finally:
            self.release_connection(connection)

    def execute_query(self, query, params=None):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                result = cursor.fetchall()
            connection.commit()
            return result
        except (Exception, psycopg2.DatabaseError) as error:
            logger.error(f"Error executing query: {error}")
            connection.rollback()
            return None
        finally:
            self.release_connection(connection)
