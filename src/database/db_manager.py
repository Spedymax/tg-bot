import psycopg2
from psycopg2 import pool
from config.settings import Settings

class DatabaseManager:
    def __init__(self):
        self.connection_pool = psycopg2.pool.SimpleConnectionPool(1, 20, **Settings.DB_CONFIG)

    def get_connection(self):
        return self.connection_pool.getconn()

    def release_connection(self, connection):
        self.connection_pool.putconn(connection)

    def close_all_connections(self):
        self.connection_pool.closeall()

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
