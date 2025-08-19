import psycopg2
from psycopg2 import pool
import logging
import time
from config.settings import Settings

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.connection_pool = psycopg2.pool.SimpleConnectionPool(1, 20, **Settings.DB_CONFIG)
        self._connection_metrics = {
            'total_connections': 0,
            'active_connections': 0,
            'peak_connections': 0,
            'connection_errors': 0
        }
        logger.info("Database connection pool initialized with 1-20 connections")

    def get_connection(self):
        """Get a connection from the pool with monitoring."""
        start_time = time.time()
        try:
            connection = self.connection_pool.getconn()
            if connection:
                self._connection_metrics['total_connections'] += 1
                self._connection_metrics['active_connections'] += 1
                if self._connection_metrics['active_connections'] > self._connection_metrics['peak_connections']:
                    self._connection_metrics['peak_connections'] = self._connection_metrics['active_connections']
                
                get_time = time.time() - start_time
                if get_time > 1.0:  # Log slow connection retrievals
                    logger.warning(f"Slow connection retrieval: {get_time:.2f}s, active: {self._connection_metrics['active_connections']}")
                
                return connection
            else:
                logger.error("Connection pool returned None - pool may be exhausted")
                self._connection_metrics['connection_errors'] += 1
                return None
        except Exception as e:
            logger.error(f"Error getting connection from pool: {e}")
            self._connection_metrics['connection_errors'] += 1
            raise

    def release_connection(self, connection):
        """Release a connection back to the pool with monitoring."""
        if connection:
            try:
                self.connection_pool.putconn(connection)
                self._connection_metrics['active_connections'] = max(0, self._connection_metrics['active_connections'] - 1)
            except Exception as e:
                logger.error(f"Error releasing connection to pool: {e}")
        else:
            logger.warning("Attempted to release None connection")

    def close_all_connections(self):
        """Close all connections in the pool."""
        logger.info("Closing all database connections")
        logger.info(f"Connection metrics: {self._connection_metrics}")
        self.connection_pool.closeall()
    
    def get_pool_status(self):
        """Get current status of the connection pool."""
        try:
            # Try to get basic pool info (this might not work with all psycopg2 versions)
            pool_info = {
                'active_connections': self._connection_metrics['active_connections'],
                'total_connections': self._connection_metrics['total_connections'], 
                'peak_connections': self._connection_metrics['peak_connections'],
                'connection_errors': self._connection_metrics['connection_errors']
            }
            return pool_info
        except Exception as e:
            logger.error(f"Error getting pool status: {e}")
            return self._connection_metrics
    
    def log_pool_status(self):
        """Log current pool status for debugging."""
        status = self.get_pool_status()
        logger.info(f"Pool status: {status}")
        
        # Log warning if pool usage is high
        if status['active_connections'] > 15:  # 75% of max (20)
            logger.warning(f"High connection pool usage: {status['active_connections']}/20 connections active")
        
        return status

    def execute_query(self, query, params=None):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                result = cursor.fetchall()
            connection.commit()
            return result
        except (Exception, psycopg2.DatabaseError) as error:
            print(f"Error executing query: {error}")
            return None
        finally:
            self.release_connection(connection)

    def update_player_data(self, player_id, data):
        # Example method to update player data
        query = "UPDATE players SET data = %s WHERE player_id = %s"
        params = (data, player_id)
        self.execute_query(query, params)
