from fastapi import FastAPI, HTTPException, status, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from datetime import datetime
from typing import List, Optional, Dict, Any
import uuid
import json
import random
import sqlite3
import os
import csv
import io
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi import UploadFile, File, Form
import re

# Import managers
from auth_manager import AuthManager
from game_manager import GameManager

# Initialize FastAPI
app = FastAPI(title="Tonk API", description="API for Tonk Card Game")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize managers
auth_manager = AuthManager()
game_manager = GameManager()

# Database setup
DATABASE_FILE = "tonk_game.db"

import time
from database import db  # import the shared database manager

def get_db():
    """Get database connection - USING SHARED DATABASE MANAGER"""
    return db.get_connection()

# Pydantic models for user management
class UserRegister(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    
    @validator('username')
    def validate_username(cls, v):
        if len(v) < 3 or len(v) > 20:
            raise ValueError('Username must be 3-20 characters')
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('Username can only contain letters, numbers, and underscores')
        return v
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v

class UserLogin(BaseModel):
    username: str
    password: str

class UserUpdate(BaseModel):
    email: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None

# Pydantic models for game management
class PlayerCreate(BaseModel):
    name: str
    is_computer: bool = False
    user_id: Optional[str] = None
    position: Optional[int] = None

class GameCreate(BaseModel):
    players: List[PlayerCreate]
    game_name: Optional[str] = None

class GameJoin(BaseModel):
    playerName: str
    user_id: str

class MoveRequest(BaseModel):
    player_id: str
    user_id: str
    moveType: str
    moveData: Dict[str, Any] = {}

# Helper functions (now use db.return_connection)
def verify_user_in_game(game_id: str, user_id: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) as count FROM game_players WHERE game_id = %s AND user_id = %s",
            (game_id, user_id)
        )
        result = cursor.fetchone()
        return result['count'] > 0
    finally:
        db.return_connection(conn)

def verify_player_belongs_to_user(game_id: str, player_id: str, user_id: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT user_id FROM game_players WHERE game_id = %s AND id = %s",
            (game_id, player_id)
        )
        result = cursor.fetchone()
        return result and result['user_id'] == user_id
    finally:
        db.return_connection(conn)

# Database export/import functions (updated to use db.return_connection)
def export_database():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, username, email, password_hash, created_at, last_login FROM users")
        users = [dict(row) for row in cursor.fetchall()]
        data = {'users': users}
        
        cursor.execute("SELECT * FROM games")
        games = [dict(row) for row in cursor.fetchall()]
        data['games'] = games
        
        cursor.execute("SELECT * FROM game_players")
        game_players = [dict(row) for row in cursor.fetchall()]
        data['game_players'] = game_players
        
        cursor.execute("SELECT * FROM game_states")
        game_states = [dict(row) for row in cursor.fetchall()]
        data['game_states'] = game_states
        
        return data
    finally:
        db.return_connection(conn)

def export_database_csv():
    conn = get_db()
    cursor = conn.cursor()
    output = io.StringIO()
    writer = csv.writer(output)
    try:
        writer.writerow(['=== USERS TABLE ==='])
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()
        if users:
            writer.writerow([col[0] for col in cursor.description])
            writer.writerows(users)
        writer.writerow([])
        
        writer.writerow(['=== GAMES TABLE ==='])
        cursor.execute("SELECT * FROM games")
        games = cursor.fetchall()
        if games:
            writer.writerow([col[0] for col in cursor.description])
            writer.writerows(games)
        writer.writerow([])
        
        writer.writerow(['=== GAME_PLAYERS TABLE ==='])
        cursor.execute("SELECT * FROM game_players")
        game_players = cursor.fetchall()
        if game_players:
            writer.writerow([col[0] for col in cursor.description])
            writer.writerows(game_players)
        writer.writerow([])
        
        writer.writerow(['=== GAME_STATES TABLE ==='])
        cursor.execute("SELECT * FROM game_states")
        game_states = cursor.fetchall()
        if game_states:
            writer.writerow([col[0] for col in cursor.description])
            writer.writerows(game_states)
        
        return output.getvalue()
    finally:
        db.return_connection(conn)

def import_database(data):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM game_states")
        cursor.execute("DELETE FROM game_players")
        cursor.execute("DELETE FROM games")
        cursor.execute("DELETE FROM users")
        
        if 'users' in data:
            for user in data['users']:
                cursor.execute(
                    """INSERT INTO users 
                       (id, username, email, password_hash, created_at, last_login)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (user['id'], user['username'], user['email'], 
                     user['password_hash'], user['created_at'], user['last_login'])
                )
        
        if 'games' in data:
            for game in data['games']:
                cursor.execute(
                    """INSERT INTO games 
                       (id, room_code, game_name, game_status, 
                        max_players, created_at, started_at, completed_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (game['id'], game['room_code'], game['game_name'], 
                     game['game_status'], game['max_players'],
                     game['created_at'], game['started_at'], game['completed_at'])
                )
        
        if 'game_players' in data:
            for player in data['game_players']:
                cursor.execute(
                    """INSERT INTO game_players 
                       (id, game_id, user_id, player_name, position, 
                        is_computer, is_ready, is_host, joined_at, left_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (player['id'], player['game_id'], player['user_id'],
                     player['player_name'], player['position'], 
                     bool(player['is_computer']),
                     bool(player['is_ready']),
                     bool(player['is_host']),
                     player['joined_at'],
                     player['left_at'])
                )
        
        if 'game_states' in data:
            for state in data['game_states']:
                cursor.execute(
                    """INSERT INTO game_states 
                       (id, game_id, state_json, last_updated, 
                        turn_count, current_player_index, turn_phase)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (state['id'], state['game_id'], state['state_json'],
                     state['last_updated'], state['turn_count'],
                     state['current_player_index'], state['turn_phase'])
                )
        
        conn.commit()
        return {"success": True, "message": f"Imported {len(data.get('users', []))} users, {len(data.get('games', []))} games"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.return_connection(conn)

# API Endpoints
@app.middleware("http")
async def log_all_requests(request: Request, call_next):
    start_time = time.time()
    method = request.method
    url = str(request.url)
    client = request.client.host if request.client else "unknown"
    
    print(f"🌐 [{datetime.utcnow()}] REQUEST START: {method} {url}")
    print(f"   Client: {client}")
    print(f"   Headers: {dict(request.headers)}")
    
    if method in ["POST", "PUT", "PATCH"]:
        try:
            body_bytes = await request.body()
            if body_bytes:
                body_str = body_bytes.decode('utf-8')
                print(f"   Body preview (first 500 chars): {body_str[:500]}")
            else:
                print(f"   Body: (empty)")
            async def receive():
                return {"type": "http.request", "body": body_bytes}
            request._receive = receive
        except Exception as e:
            print(f"   Error reading body: {e}")
    
    response = await call_next(request)
    duration = time.time() - start_time
    print(f"📤 [{datetime.utcnow()}] RESPONSE: {method} {url} -> {response.status_code} ({duration:.3f}s)")
    return response

@app.get("/")
async def root():
    return {
        "message": "Tonk Game API",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }

@app.get("/ping")
async def ping():
    return {
        "status": "pong",
        "timestamp": datetime.utcnow().isoformat(),
        "server": "TonkAPI",
        "environment": "Render.com",
        "database": "PostgreSQL"
    }

@app.get("/api/ping")
async def api_ping():
    return await ping()

# ============ PUBLIC TEST ENDPOINTS ============
@app.get("/api/test/users")
async def test_get_users():
    """Public test endpoint to view users (limited info) for verifying persistence"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, username, email, created_at FROM users LIMIT 10")
        users = [dict(row) for row in cursor.fetchall()]
        return {"success": True, "users": users}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.return_connection(conn)

@app.get("/api/test/games")
async def test_get_games():
    """Public test endpoint to view games (limited info)"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, room_code, game_name, game_status, created_at FROM games LIMIT 10")
        games = [dict(row) for row in cursor.fetchall()]
        return {"success": True, "games": games}
    finally:
        db.return_connection(conn)

# ============ USER ENDPOINTS ============
@app.post("/api/users/register")
async def register(user_data: UserRegister):
    try:
        result = auth_manager.create_user(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@app.post("/api/users/login")
async def login(user_data: UserLogin):
    try:
        result = auth_manager.authenticate_user(
            username=user_data.username,
            password=user_data.password
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@app.get("/api/users/{user_id}")
async def get_user_by_id_endpoint(user_id: str):
    user_info = auth_manager.get_user_by_id(user_id)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return {"success": True, "user": user_info}

@app.get("/api/users/username/{username}")
async def get_user_by_username_endpoint(username: str):
    user_info = auth_manager.get_user_by_username(username)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return {"success": True, "user": user_info}

@app.put("/api/users/{user_id}")
async def update_user(user_id: str, update_data: UserUpdate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT email, password_hash FROM users WHERE id = %s",
            (user_id,)
        )
        user = cursor.fetchone()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        update_fields = []
        update_values = []
        
        if update_data.email is not None:
            email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
            if not re.match(email_regex, update_data.email):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid email address"
                )
            cursor.execute(
                "SELECT id FROM users WHERE email = %s AND id != %s",
                (update_data.email, user_id)
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already in use"
                )
            update_fields.append("email = %s")
            update_values.append(update_data.email)
        
        if update_data.new_password is not None:
            if not update_data.current_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Current password is required to set new password"
                )
            if not auth_manager.verify_password(update_data.current_password, user['password_hash']):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Current password is incorrect"
                )
            if len(update_data.new_password) < 6:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="New password must be at least 6 characters"
                )
            new_password_hash = auth_manager.hash_password(update_data.new_password)
            update_fields.append("password_hash = %s")
            update_values.append(new_password_hash)
        
        if not update_fields:
            return {"success": True, "message": "No changes to update"}
        
        update_values.append(user_id)
        update_query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = %s"
        cursor.execute(update_query, update_values)
        conn.commit()
        return {"success": True, "message": "User updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user: {str(e)}"
        )
    finally:
        db.return_connection(conn)

# ============ GAME ENDPOINTS ============
@app.post("/api/game/create")
async def create_game(game_data: GameCreate, user_id: str = Query(...)):
    try:
        players = []
        for player in game_data.players:
            players.append({
                "name": player.name,
                "is_computer": player.is_computer,
                "user_id": player.user_id
            })
        result = game_manager.create_game(
            players=players,
            game_name=game_data.game_name,
            creator_id=user_id
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@app.post("/api/game/{room_code}/join")
async def join_game(room_code: str, join_data: GameJoin):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM games WHERE room_code = %s", (room_code.upper(),))
        game = cursor.fetchone()
        db.return_connection(conn)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        result = game_manager.join_game(
            game_id=game['id'],
            user_id=join_data.user_id,
            player_name=join_data.playerName
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@app.get("/api/game/{identifier}/state")
async def get_game_state(identifier: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT g.id 
               FROM games g 
               WHERE g.id = %s OR g.room_code = %s""",
            (identifier, identifier.upper())
        )
        result = cursor.fetchone()
        db.return_connection(conn)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
        game_state = game_manager.get_game(result['id'])
        if not game_state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game state not found"
            )
        return {"success": True, "game_state": game_state}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get game state: {str(e)}"
        )

@app.get("/api/game/{identifier}/state/private")
async def get_private_game_state(identifier: str, user_id: str = Query(...)):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT g.id, g.room_code, g.game_status, gs.state_json 
               FROM games g 
               LEFT JOIN game_states gs ON g.id = gs.game_id 
               WHERE g.id = %s OR g.room_code = %s""",
            (identifier, identifier.upper())
        )
        result = cursor.fetchone()
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
        cursor.execute(
            "SELECT id FROM game_players WHERE game_id = %s AND user_id = %s",
            (result['id'], user_id)
        )
        player_in_game = cursor.fetchone()
        if not player_in_game:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User not in this game"
            )
        if result['state_json']:
            game_state = json.loads(result['state_json'])
            filtered_state = game_state.copy()
            if 'deck' in filtered_state and 'deck_length' not in filtered_state:
                filtered_state['deck_length'] = len(filtered_state['deck'])
            for player in filtered_state.get('players', []):
                if player.get('user_id') 