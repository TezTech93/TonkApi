# auth_manager.py - CORRECTED VERSION
import uuid
import bcrypt
import re
from datetime import datetime
from typing import Optional, Dict
from database import db

class AuthManager:
    def __init__(self):
        self.min_password_length = 6  # Reduced from 8 to match frontend
        self.work_factor = 12  # BCrypt work factor
    
    def _ensure_db(self):
        db.ensure_tables_exist()
    
    def _validate_password_strength(self, password: str) -> (bool, str):
        """Validate password - SIMPLIFIED FOR EXPO APP"""
        # Check minimum length
        if len(password) < self.min_password_length:
            return False, f"Password must be at least {self.min_password_length} characters"
        
        # SIMPLE VALIDATION: Just check it's not empty and meets length
        # Remove complexity requirements for now - you can add them back later
        return True, "Password is acceptable"
    
    def _validate_email_format(self, email: str) -> (bool, str):
        """Validate email format - SIMPLIFIED"""
        if not email or not isinstance(email, str):
            return False, "Email is required"
        
        # Check for basic email format (simplified)
        if '@' not in email or '.' not in email:
            return False, "Invalid email format"
        
        # More permissive regex for testing
        # Allows: user@example.com, user.name@domain.co.uk, user+tag@domain.com
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            return False, "Invalid email address format"
        
        return True, "Email format is valid"
    
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
        
        # DEBUG: Log what we're receiving
        print(f"🔍 CREATE_USER RECEIVED:")
        print(f"  Username: '{username}'")
        print(f"  Email: '{email}'")
        print(f"  Password: '{password[:2]}...' (length: {len(password)})")
        
        # Validate username
        if not username or len(username) < 3 or len(username) > 20:
            raise ValueError("Username must be 3-20 characters")
        
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            raise ValueError("Username can only contain letters, numbers, and underscores")
        
        # Validate email (can be null/empty for guest users)
        if email and email.strip():
            is_valid, email_msg = self._validate_email_format(email)
            if not is_valid:
                print(f"❌ Email validation failed: {email_msg}")
                raise ValueError(email_msg)
            email = email.strip()  # Clean up whitespace
        else:
            email = None  # Allow null email
        
        # Validate password
        is_valid, password_msg = self._validate_password_strength(password)
        if not is_valid:
            print(f"❌ Password validation failed: {password_msg}")
            raise ValueError(password_msg)
        
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
            
            print(f"✅ Creating user with:")
            print(f"  ID: {user_id}")
            print(f"  Username: {username}")
            print(f"  Email: {email or 'None'}")
            
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
            print(f"❌ Database error in create_user: {e}")
            raise e
        finally:
            conn.close()
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate user"""
        self._ensure_db()
        
        print(f"🔍 AUTHENTICATE_USER RECEIVED:")
        print(f"  Username: '{username}'")
        print(f"  Password: '{password[:2]}...' (length: {len(password)})")
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            
            if not user:
                print(f"❌ User not found: {username}")
                return None
            
            print(f"✅ User found: {user['username']}")
            
            # Verify password
            if not self.verify_password(password, user['password_hash']):
                print(f"❌ Password verification failed for user: {username}")
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
            print(f"❌ Authentication error: {e}")
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