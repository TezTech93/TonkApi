# auth_manager.py
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import HTTPException

# Security configuration
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthManager:
    def __init__(self, db_path: str = "tonk_game.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize users table only"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
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
        
        conn.commit()
        conn.close()
        print("✅ Auth database initialized")
    
    def get_db_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # Password helpers
    def hash_password(self, password: str) -> str:
        return pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)
    
    def create_token(self, username: str) -> str:
        """Create JWT token"""
        payload = {
            "sub": username,
            "exp": datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    
    def decode_token(self, token: str) -> Optional[Dict]:
        """Decode and validate JWT token"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None
    
    # User CRUD operations
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user by username"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user by ID"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def create_user(self, username: str, email: str, password: str) -> Dict:
        """Create a new user"""
        # Check if username exists
        if self.get_user_by_username(username):
            raise ValueError("Username already exists")
        
        # Check if email exists
        if self.get_user_by_email(email):
            raise ValueError("Email already exists")
        
        # Create user
        user_id = str(uuid.uuid4())
        hashed_password = self.hash_password(password)
        created_at = datetime.now().isoformat()
        
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO users 
            (id, username, email, hashed_password, created_at, games_played, games_won, online, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            username,
            email,
            hashed_password,
            created_at,
            0,  # games_played
            0,  # games_won
            1,  # online
            created_at  # last_seen
        ))
        
        conn.commit()
        conn.close()
        
        # Create token
        token = self.create_token(username)
        
        return {
            "id": user_id,
            "username": username,
            "email": email,
            "token": token
        }
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate user with username and password"""
        user = self.get_user_by_username(username)
        if not user:
            return None
        
        if not self.verify_password(password, user['hashed_password']):
            return None
        
        # Update last seen
        self.update_user_last_seen(user['id'])
        
        # Create token
        token = self.create_token(username)
        
        return {
            "id": user['id'],
            "username": user['username'],
            "email": user['email'],
            "token": token
        }
    
    def update_user_last_seen(self, user_id: str):
        """Update user's last seen timestamp"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET last_seen = ?, online = 1 WHERE id = ?",
            (datetime.now().isoformat(), user_id)
        )
        conn.commit()
        conn.close()
    
    def set_user_offline(self, user_id: str):
        """Set user offline"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET online = 0, last_seen = ? WHERE id = ?",
            (datetime.now().isoformat(), user_id)
        )
        conn.commit()
        conn.close()
    
    def get_online_users(self) -> list:
        """Get all online users"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, last_seen FROM users WHERE online = 1")
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return users
    
    def validate_token(self, token: str) -> Optional[Dict]:
        """Validate JWT token and return user"""
        payload = self.decode_token(token)
        if not payload:
            return None
        
        username = payload.get("sub")
        if not username:
            return None
        
        user = self.get_user_by_username(username)
        if not user:
            return None
        
        # Update last seen
        self.update_user_last_seen(user['id'])
        
        return {
            "id": user['id'],
            "username": user['username']
        }