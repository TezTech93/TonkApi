# database.py
import sqlite3
import threading
import time

class DatabaseManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_db()
        return cls._instance
    
    def _init_db(self):
        """Initialize database tables"""
        print("🔄 Initializing database...")
        conn = sqlite3.connect("tonk_game.db")
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            games_played INTEGER DEFAULT 0,
            games_won INTEGER DEFAULT 0,
            online BOOLEAN DEFAULT 0,
            last_seen TIMESTAMP
        )
        ''')
        
        # Games table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            room_code TEXT UNIQUE NOT NULL,
            game_name TEXT,
            deck TEXT,
            discard_pile TEXT,
            under_card TEXT,
            current_player_index INTEGER DEFAULT 0,
            turn_phase TEXT DEFAULT 'waiting',
            table_spreads TEXT,
            turn_count INTEGER DEFAULT 0,
            game_status TEXT DEFAULT 'lobby',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_move TEXT,
            settings TEXT DEFAULT '{"allow_under_card_any_turn": true}',
            winner TEXT,
            win_reason TEXT,
            creator_id TEXT,
            max_players INTEGER DEFAULT 4
        )
        ''')
        
        # Players table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_players (
            id TEXT PRIMARY KEY,
            game_id TEXT NOT NULL,
            user_id TEXT,
            name TEXT NOT NULL,
            is_computer BOOLEAN DEFAULT 0,
            hand TEXT DEFAULT '[]',
            spreads TEXT DEFAULT '[]',
            has_dropped BOOLEAN DEFAULT 0,
            score INTEGER DEFAULT 0,
            last_move TEXT,
            turns INTEGER DEFAULT 0,
            has_drawn_from_under BOOLEAN DEFAULT 0,
            is_online BOOLEAN DEFAULT 1,
            position INTEGER
        )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Database initialized")
    
    def get_connection(self):
        """Get a database connection with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect("tonk_game.db", check_same_thread=False)
                conn.row_factory = sqlite3.Row
                return conn
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise
    
    def ensure_tables_exist(self):
        """Ensure tables exist before operations"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Quick check if users table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if not cursor.fetchone():
                print("⚠️ Tables missing, re-initializing...")
                conn.close()
                self._init_db()
            else:
                conn.close()
                
        except Exception as e:
            print(f"⚠️ Error checking tables: {e}")
            self._init_db()

# Global instance
db = DatabaseManager()