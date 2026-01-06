# auth_manager.py - USE BCRYPT DIRECTLY
import uuid
import bcrypt  # ADD THIS IMPORT
from datetime import datetime, timedelta
from typing import Optional, Dict
from jose import JWTError, jwt
from database import db

SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# REMOVE: pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthManager:
    def __init__(self):
        pass
    
    def _ensure_db(self):
        db.ensure_tables_exist()
    
    def hash_password(self, password: str) -> str:
        """Hash a password for storing - USING DIRECT BCRYPT"""
        # Bcrypt can handle any length password - it hashes internally
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    def verify_password(self, password: str, hashed_password: str) -> bool:
        """Verify a stored password - USING DIRECT BCRYPT"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception:
            return False
    
    def create_token(self, username: str) -> str:
        """Create JWT token"""
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {"sub": username, "exp": expire}
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    
    def decode_token(self, token: str) -> Optional[Dict]:
        """Decode and validate JWT token"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None
    
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
            hashed_password = self.hash_password(password)
            created_at = datetime.now().isoformat()
            
            cursor.execute('''
                INSERT INTO users 
                (id, username, email, hashed_password, created_at, online, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, username, email, hashed_password, 
                created_at, 1, created_at
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
            
            if not self.verify_password(password, user['hashed_password']):
                conn.close()
                return None
            
            # Update last seen
            cursor.execute(
                "UPDATE users SET last_seen = ?, online = 1 WHERE id = ?",
                (datetime.now().isoformat(), user['id'])
            )
            conn.commit()
            conn.close()
            
            # Create token
            token = self.create_token(username)
            
            return {
                "id": user['id'],
                "username": user['username'],
                "email": user['email'],
                "token": token
            }
            
        except Exception as e:
            conn.close()
            raise e
    
    def validate_token(self, token: str) -> Optional[Dict]:
        """Validate token and return user"""
        payload = self.decode_token(token)
        if not payload:
            return None
        
        username = payload.get("sub")
        if not username:
            return None
        
        self._ensure_db()
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            conn.close()
            
            if not user:
                return None
            
            return {
                "id": user['id'],
                "username": user['username']
            }
            
        except Exception:
            conn.close()
            return None