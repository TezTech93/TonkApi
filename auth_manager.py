import uuid
import bcrypt
from datetime import datetime
from typing import Optional, Dict
from database import db

class AuthManager:
    def __init__(self):
        pass
    
    def _ensure_db(self):
        db.ensure_tables_exist()
    
    def hash_password(self, password: str) -> str:
        """Hash a password for storing - USING DIRECT BCRYPT"""
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    def verify_password(self, password: str, hashed_password: str) -> bool:
        """Verify a stored password - USING DIRECT BCRYPT"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception:
            return False
    
    def create_user(self, username: str, email: str, password: str) -> Dict:
        """Create a new user"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if username exists
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                conn.close()
                raise ValueError("Username already exists")
            
            # Check if email exists
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cursor.fetchone():
                conn.close()
                raise ValueError("Email already exists")
            
            # Create user
            user_id = str(uuid.uuid4())
            password_hash = self.hash_password(password)
            created_at = datetime.now().isoformat()
            
            cursor.execute('''
                INSERT INTO users 
                (id, username, email, password_hash, created_at, last_login)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                user_id, username, email, password_hash, 
                created_at, created_at
            ))
            
            conn.commit()
            conn.close()
            
            return {
                "success": True,
                "user_id": user_id,
                "username": username,
                "email": email,
                "message": "User created successfully"
            }
            
        except Exception as e:
            conn.close()
            raise e
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate user"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            
            if not user:
                conn.close()
                return None
            
            if not self.verify_password(password, user['password_hash']):
                conn.close()
                return None
            
            # Update last login
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user['id'])
            )
            conn.commit()
            conn.close()
            
            return {
                "success": True,
                "user_id": user['id'],
                "username": user['username'],
                "email": user['email'],
                "message": "Login successful"
            }
            
        except Exception as e:
            conn.close()
            raise e
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user by ID"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT id, username, email, created_at, last_login FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            conn.close()
            
            if not user:
                return None
            
            return dict(user)
            
        except Exception:
            conn.close()
            return None
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user by username"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT id, username, email, created_at, last_login FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            conn.close()
            
            if not user:
                return None
            
            return dict(user)
            
        except Exception:
            conn.close()
            return None