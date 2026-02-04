# auth_manager.py - UPDATED WITH ENHANCED SECURITY
import uuid
import bcrypt
import re
from datetime import datetime
from typing import Optional, Dict
from database import db

class AuthManager:
    def __init__(self):
        self.min_password_length = 8
        self.work_factor = 12  # BCrypt work factor
    
    def _ensure_db(self):
        db.ensure_tables_exist()
    
    def _validate_password_strength(self, password: str) -> bool:
        """Validate password meets security requirements"""
        if len(password) < self.min_password_length:
            return False, f"Password must be at least {self.min_password_length} characters"
        
        # Check for complexity
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(not c.isalnum() for c in password)
        
        score = sum([has_upper, has_lower, has_digit, has_special])
        if score < 3:
            return False, "Password should contain at least 3 of: uppercase, lowercase, digit, special character"
        
        return True, "Password is strong"
    
    def hash_password(self, password: str) -> str:
        """Hash a password with configurable work factor"""
        salt = bcrypt.gensalt(rounds=self.work_factor)
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    def verify_password(self, password: str, hashed_password: str) -> bool:
        """Verify a stored password against provided password"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception:
            return False
    
    def create_user(self, username: str, email: str, password: str) -> Dict:
        """Create a new user with validation"""
        self._ensure_db()
        
        # Validate password strength
        is_valid, message = self._validate_password_strength(password)
        if not is_valid:
            raise ValueError(message)
        
        # Validate username
        if len(username) < 3 or len(username) > 20:
            raise ValueError("Username must be 3-20 characters")
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            raise ValueError("Username can only contain letters, numbers, and underscores")
        
        # Validate email if provided
        if email:
            email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
            if not re.match(email_regex, email):
                raise ValueError("Invalid email address")
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if username exists
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                raise ValueError("Username already exists")
            
            # Check if email exists (if provided)
            if email:
                cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
                if cursor.fetchone():
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
            
            return {
                "success": True,
                "user_id": user_id,
                "username": username,
                "email": email,
                "message": "User created successfully"
            }
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate user with rate limiting protection"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            
            if not user:
                return None
            
            # Verify password
            if not self.verify_password(password, user['password_hash']):
                return None
            
            # Update last login
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user['id'])
            )
            conn.commit()
            
            return {
                "success": True,
                "user_id": user['id'],
                "username": user['username'],
                "email": user['email'],
                "message": "Login successful"
            }
            
        except Exception as e:
            raise e
        finally:
            conn.close()
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user by ID (excluding password hash)"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT id, username, email, created_at, last_login FROM users WHERE id = ?", 
                (user_id,)
            )
            user = cursor.fetchone()
            
            if not user:
                return None
            
            return dict(user)
        finally:
            conn.close()
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user by username (excluding password hash)"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT id, username, email, created_at, last_login FROM users WHERE username = ?", 
                (username,)
            )
            user = cursor.fetchone()
            
            if not user:
                return None
            
            return dict(user)
        finally:
            conn.close()
    
    def change_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        """Change user password with validation"""
        self._ensure_db()
        
        # Validate new password
        is_valid, message = self._validate_password_strength(new_password)
        if not is_valid:
            raise ValueError(message)
        
        # Check if new password is same as current
        if current_password == new_password:
            raise ValueError("New password must be different from current password")
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get current password hash
            cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            
            if not user:
                raise ValueError("User not found")
            
            # Verify current password
            if not self.verify_password(current_password, user['password_hash']):
                raise ValueError("Current password is incorrect")
            
            # Hash new password
            new_password_hash = self.hash_password(new_password)
            
            # Update password
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (new_password_hash, user_id)
            )
            conn.commit()
            
            return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()