# database.py - PostgreSQL version with connection pool
import os
import threading
import time
import psycopg2
from psycopg2 import pool, sql, extras
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

class DatabaseManager:
    _instance = None
    _lock = threading.Lock()
    _connection_pool = None

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_pool()
        return cls._instance

    def _init_pool(self):
        """Initialize PostgreSQL connection pool using DATABASE_URL."""
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            # Fallback for local development – adjust as needed
            database_url = "postgresql://postgres:password@localhost:5432/tonk_db"
            print("⚠️  DATABASE_URL not set, using local fallback.")

        # Render provides a DATABASE_URL that may start with postgres://
        # psycopg2 needs postgresql://, so we replace if necessary
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        try:
            # Create a simple connection pool with min 1, max 10 connections
            self._connection_pool = psycopg2.pool.SimpleConnectionPool(
                1, 10, dsn=database_url
            )
            print("✅ PostgreSQL connection pool created.")
        except Exception as e:
            print(f"❌ Failed to create connection pool: {e}")
            raise

    def get_connection(self):
        """Get a connection from the pool with retry logic."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = self._connection_pool.getconn()
                # Set row factory to return dict-like rows
                conn.cursor_factory = extras.RealDictCursor
                return conn
            except psycopg2.OperationalError as e:
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise
            except Exception as e:
                raise

    def return_connection(self, conn):
        """Return a connection to the pool."""
        if conn:
            self._connection_pool.putconn(conn)

    def close_all_connections(self):
        """Close all connections in the pool (called on shutdown)."""
        if self._connection_pool:
            self._connection_pool.closeall()

    def ensure_tables_exist(self):
        """Create tables if they don't exist."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                # Users table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        email TEXT UNIQUE,
                        password_hash TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_login TIMESTAMP
                    )
                """)

                # Games table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS games (
                        id TEXT PRIMARY KEY,
                        room_code TEXT UNIQUE NOT NULL,
                        game_name TEXT,
                        game_status TEXT DEFAULT 'lobby',
                        max_players INTEGER DEFAULT 4,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                """)

                # Game players table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS game_players (
                        id TEXT PRIMARY KEY,
                        game_id TEXT NOT NULL,
                        user_id TEXT,
                        player_name TEXT NOT NULL,
                        position INTEGER,
                        is_computer BOOLEAN DEFAULT FALSE,
                        is_ready BOOLEAN DEFAULT FALSE,
                        is_host BOOLEAN DEFAULT FALSE,
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        left_at TIMESTAMP,
                        FOREIGN KEY (game_id) REFERENCES games (id),
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                """)

                # Game states table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS game_states (
                        id TEXT PRIMARY KEY,
                        game_id TEXT UNIQUE NOT NULL,
                        state_json TEXT NOT NULL,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        turn_count INTEGER DEFAULT 0,
                        current_player_index INTEGER DEFAULT 0,
                        turn_phase TEXT DEFAULT 'waiting',
                        FOREIGN KEY (game_id) REFERENCES games (id)
                    )
                """)

                conn.commit()
                print("✅ Tables verified/created.")
        except Exception as e:
            conn.rollback()
            print(f"❌ Error creating tables: {e}")
            raise
        finally:
            self.return_connection(conn)

# Global instance
db = DatabaseManager()