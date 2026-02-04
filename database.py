# database.py - UPDATED FOR COMPATIBILITY
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
        """Initialize database tables - COMPATIBLE WITH APP.PY"""
        print("🔄 Initializing database...")
        conn = sqlite3.connect("tonk_game.db", check_same_thread=False)
        cursor = conn.cursor()
        
        # Users table - MATCHES APP.PY
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
        ''')
        
        # Games table - MATCHES APP.PY
        cursor.execute('''
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
        ''')
        
        # Game players table - MATCHES APP.PY
        cursor.execute('''
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
        ''')
        
        # Game states table - MATCHES APP.PY
        cursor.execute('''
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
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Database initialized with compatible schema")
    
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
                # Check if we need to migrate from old schema
                cursor.execute("PRAGMA table_info(users)")
                columns = [col[1] for col in cursor.fetchall()]
                
                if 'hashed_password' in columns and 'password_hash' not in columns:
                    print("🔄 Migrating from old schema...")
                    conn.close()
                    self._migrate_old_schema()
                else:
                    conn.close()
                    
        except Exception as e:
            print(f"⚠️ Error checking tables: {e}")
            self._init_db()
    
    def _migrate_old_schema(self):
        """Migrate from old schema to new one"""
        conn = sqlite3.connect("tonk_game.db", check_same_thread=False)
        cursor = conn.cursor()
        
        try:
            # Backup old tables
            cursor.execute("ALTER TABLE users RENAME TO users_old")
            cursor.execute("ALTER TABLE games RENAME TO games_old")
            cursor.execute("ALTER TABLE game_players RENAME TO game_players_old")
            
            # Create new tables
            self._init_db()
            
            # Migrate users data
            cursor.execute('''
                INSERT INTO users (id, username, email, password_hash, created_at, last_login)
                SELECT id, username, email, hashed_password, created_at, last_seen
                FROM users_old
            ''')
            
            # Migrate games data (basic fields)
            cursor.execute('''
                INSERT INTO games (id, room_code, game_name, game_status, created_at)
                SELECT id, room_code, game_name, game_status, created_at
                FROM games_old
            ''')
            
            # Drop old tables
            cursor.execute("DROP TABLE users_old")
            cursor.execute("DROP TABLE games_old")
            cursor.execute("DROP TABLE game_players_old")
            
            conn.commit()
            print("✅ Database migrated successfully")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            conn.rollback()
            # Restore old tables if migration fails
            try:
                cursor.execute("ALTER TABLE users_old RENAME TO users")
                cursor.execute("ALTER TABLE games_old RENAME TO games")
                cursor.execute("ALTER TABLE game_players_old RENAME TO game_players")
            except:
                pass
            raise
        finally:
            conn.close()

# Global instance
db = DatabaseManager()