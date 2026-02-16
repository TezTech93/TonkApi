# auth_manager.py - PostgreSQL compatible
import uuid
import bcrypt
import re
from datetime import datetime
from typing import Optional, Dict
from database import db

class AuthManager:
    def __init__(self):
        self.min_password_length = 6
        self.work_factor = 12

    def _ensure_db(self):
        db.ensure_tables_exist()

    def _validate_password_strength(self, password: str) -> (bool, str):
        if len(password) < self.min_password_length:
            return False, f"Password must be at least {self.min_password_length} characters"
        return True, "Password is acceptable"

    def _validate_email_format(self, email: str) -> (bool, str):
        if not email or not isinstance(email, str):
            return False, "Email is required"
        if '@' not in email or '.' not in email:
            return False, "Invalid email format"
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            return False, "Invalid email address format"
        return True, "Email format is valid"

    def hash_password(self, password: str) -> str:
        salt = bcrypt.gensalt(rounds=self.work_factor)
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    def verify_password(self, password: str, hashed_password: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception:
            return False

    def create_user(self, username: str, email: str, password: str) -> Dict:
        self._ensure_db()

        # validation (unchanged) ...

        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                # Check if username exists
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    raise ValueError("Username already exists")

                if email:
                    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                    if cursor.fetchone():
                        raise ValueError("Email already exists")

                user_id = str(uuid.uuid4())
                password_hash = self.hash_password(password)
                created_at = datetime.now().isoformat()

                cursor.execute("""
                    INSERT INTO users 
                    (id, username, email, password_hash, created_at, last_login)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (user_id, username, email, password_hash, created_at, created_at))

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
            db.return_connection(conn)

    def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        self._ensure_db()
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                if not user:
                    return None

                if not self.verify_password(password, user['password_hash']):
                    return None

                cursor.execute(
                    "UPDATE users SET last_login = %s WHERE id = %s",
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
            db.return_connection(conn)

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        self._ensure_db()
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, username, email, created_at, last_login FROM users WHERE id = %s",
                    (user_id,)
                )
                user = cursor.fetchone()
                return dict(user) if user else None
        finally:
            db.return_connection(conn)

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        self._ensure_db()
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, username, email, created_at, last_login FROM users WHERE username = %s",
                    (username,)
                )
                user = cursor.fetchone()
                return dict(user) if user else None
        finally:
            db.return_connection(conn)

    def change_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        self._ensure_db()
        # validation (unchanged) ...
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
                user = cursor.fetchone()
                if not user:
                    raise ValueError("User not found")
                if not self.verify_password(current_password, user['password_hash']):
                    raise ValueError("Current password is incorrect")

                new_password_hash = self.hash_password(new_password)
                cursor.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (new_password_hash, user_id)
                )
                conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            db.return_connection(conn)