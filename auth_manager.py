# auth_manager.py - SIMPLIFIED
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict
from passlib.context import CryptContext
from jose import JWTError, jwt
from database import db  # Import shared DB instance

SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthManager:
    def __init__(self):
        # Database will auto-initialize via singleton
        pass
    
    def _ensure_db(self):
        """Ensure database is ready before any operation"""
        db.ensure_tables_exist()
    
    def hash_password(self, password: str) -> str:
        """Hash password with BCrypt"""
        # Handle long passwords
        if len(password.encode('utf-8')) > 72:
            password = hashlib.sha256(password.encode('utf-8')).hexdigest()
        return pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password"""
        if len(plain_password.encode('utf-8')) > 72:
            plain_password = hashlib.sha256(plain_password.encode('utf-8')).hexdigest()
        return pwd_context.verify(plain_password, hashed_password)
    
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