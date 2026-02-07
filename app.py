from fastapi import FastAPI, HTTPException, status, Query,Request
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

# app.py - Add this RIGHT AFTER the CORS middleware setup
import time

def get_db():
    """Get database connection - USING SHARED DATABASE MANAGER"""
    from database import db
    return db.get_connection()

# Pydantic models for user management
class UserRegister(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    
    @validator('username')
    def validate_username(cls, v):
        """Username validation"""
        if len(v) < 3 or len(v) > 20:
            raise ValueError('Username must be 3-20 characters')
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('Username can only contain letters, numbers, and underscores')
        return v
    
    @validator('password')
    def validate_password(cls, v):
        """Password validation"""
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

# Helper functions
def verify_user_in_game(game_id: str, user_id: str) -> bool:
    """Verify if a user is in a game"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT COUNT(*) as count FROM game_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id)
        )
        result = cursor.fetchone()
        return result['count'] > 0
    finally:
        conn.close()

def verify_player_belongs_to_user(game_id: str, player_id: str, user_id: str) -> bool:
    """Verify if a player belongs to a specific user"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT user_id FROM game_players WHERE game_id = ? AND id = ?",
            (game_id, player_id)
        )
        result = cursor.fetchone()
        return result and result['user_id'] == user_id
    finally:
        conn.close()

# Database export/import functions
def export_database():
    """Export entire database as JSON"""
    conn = get_db()
    cursor = conn.cursor()
    
    data = {}
    
    # Export users - UPDATED COLUMN NAME
    cursor.execute("SELECT id, username, email, password_hash, created_at, last_login FROM users")
    users = [dict(row) for row in cursor.fetchall()]
    data['users'] = users
    
    # Export games
    cursor.execute("SELECT * FROM games")
    games = [dict(row) for row in cursor.fetchall()]
    data['games'] = games
    
    # Export game_players
    cursor.execute("SELECT * FROM game_players")
    game_players = [dict(row) for row in cursor.fetchall()]
    data['game_players'] = game_players
    
    # Export game_states
    cursor.execute("SELECT * FROM game_states")
    game_states = [dict(row) for row in cursor.fetchall()]
    data['game_states'] = game_states
    
    conn.close()
    
    return data

def export_database_csv():
    """Export entire database as CSV"""
    conn = get_db()
    cursor = conn.cursor()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Export users table
    writer.writerow(['=== USERS TABLE ==='])
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    if users:
        writer.writerow([col[0] for col in cursor.description])
        writer.writerows(users)
    writer.writerow([])
    
    # Export games table
    writer.writerow(['=== GAMES TABLE ==='])
    cursor.execute("SELECT * FROM games")
    games = cursor.fetchall()
    if games:
        writer.writerow([col[0] for col in cursor.description])
        writer.writerows(games)
    writer.writerow([])
    
    # Export game_players table
    writer.writerow(['=== GAME_PLAYERS TABLE ==='])
    cursor.execute("SELECT * FROM game_players")
    game_players = cursor.fetchall()
    if game_players:
        writer.writerow([col[0] for col in cursor.description])
        writer.writerows(game_players)
    writer.writerow([])
    
    # Export game_states table
    writer.writerow(['=== GAME_STATES TABLE ==='])
    cursor.execute("SELECT * FROM game_states")
    game_states = cursor.fetchall()
    if game_states:
        writer.writerow([col[0] for col in cursor.description])
        writer.writerows(game_states)
    
    conn.close()
    
    return output.getvalue()

def import_database(data):
    """Import database from JSON"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Clear existing data
        cursor.execute("DELETE FROM game_states")
        cursor.execute("DELETE FROM game_players")
        cursor.execute("DELETE FROM games")
        cursor.execute("DELETE FROM users")
        
        # Import users - UPDATED COLUMN NAME
        if 'users' in data:
            for user in data['users']:
                cursor.execute(
                    """INSERT INTO users 
                       (id, username, email, password_hash, created_at, last_login)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (user['id'], user['username'], user['email'], 
                     user['password_hash'], user['created_at'], user['last_login'])
                )
        
        # Import games
        if 'games' in data:
            for game in data['games']:
                cursor.execute(
                    """INSERT INTO games 
                       (id, room_code, game_name, game_status, 
                        max_players, created_at, started_at, completed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (game['id'], game['room_code'], game['game_name'], 
                     game['game_status'], game['max_players'],
                     game['created_at'], game['started_at'], game['completed_at'])
                )
        
        # Import game_players
        if 'game_players' in data:
            for player in data['game_players']:
                cursor.execute(
                    """INSERT INTO game_players 
                       (id, game_id, user_id, player_name, position, 
                        is_computer, is_ready, is_host, joined_at, left_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (player['id'], player['game_id'], player['user_id'],
                     player['player_name'], player['position'], player['is_computer'],
                     player['is_ready'], player['is_host'], player['joined_at'],
                     player['left_at'])
                )
        
        # Import game_states
        if 'game_states' in data:
            for state in data['game_states']:
                cursor.execute(
                    """INSERT INTO game_states 
                       (id, game_id, state_json, last_updated, 
                        turn_count, current_player_index, turn_phase)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
        conn.close()

# API Endpoints
@app.middleware("http")
async def log_all_requests(request: Request, call_next):
    """Log ALL incoming requests"""
    start_time = time.time()
    
    # Get request details
    method = request.method
    url = str(request.url)
    client = request.client.host if request.client else "unknown"
    
    print(f"🌐 [{datetime.utcnow()}] REQUEST START: {method} {url}")
    print(f"   Client: {client}")
    print(f"   Headers: {dict(request.headers)}")
    
    # Check body for non-GET requests
    if method in ["POST", "PUT", "PATCH"]:
        try:
            # Peek at the body without consuming it
            body_bytes = await request.body()
            if body_bytes:
                body_str = body_bytes.decode('utf-8')
                print(f"   Body preview (first 500 chars): {body_str[:500]}")
            else:
                print(f"   Body: (empty)")
            
            # Reset the body so it can be read again
            async def receive():
                return {"type": "http.request", "body": body_bytes}
            request._receive = receive
        except Exception as e:
            print(f"   Error reading body: {e}")
    
    # Process the request
    response = await call_next(request)
    
    # Log response
    duration = time.time() - start_time
    print(f"📤 [{datetime.utcnow()}] RESPONSE: {method} {url} -> {response.status_code} ({duration:.3f}s)")
    
    return response

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Tonk Game API",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }

@app.get("/ping")
async def ping():
    """Health check endpoint"""
    return {
        "status": "pong",
        "timestamp": datetime.utcnow().isoformat(),
        "server": "TonkAPI",
        "environment": "Render.com",
        "database": "SQLite"
    }

@app.get("/api/ping")
async def api_ping():
    """API health check"""
    return await ping()

# ============ USER ENDPOINTS ============

@app.post("/api/users/register")
async def register(user_data: UserRegister):
    print(f"🔍 DEBUG REGISTER ENDPOINT:")
    print(f"  Raw user_data: {user_data}")
    print(f"  username: {user_data.username}")
    print(f"  password: {user_data.password}")
    print(f"  email: {user_data.email}")
    print(f"  email type: {type(user_data.email)}")
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
    """Login user - USING AUTH MANAGER"""
    print(f"  username: {user_data.username}")
    print(f"  password: {user_data.password}")
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
    """Get specific user by ID - USING AUTH MANAGER"""
    user_info = auth_manager.get_user_by_id(user_id)
    
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {
        "success": True,
        "user": user_info
    }

@app.get("/api/users/username/{username}")
async def get_user_by_username_endpoint(username: str):
    """Get user by username - USING AUTH MANAGER"""
    user_info = auth_manager.get_user_by_username(username)
    
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {
        "success": True,
        "user": user_info
    }

@app.put("/api/users/{user_id}")
async def update_user(user_id: str, update_data: UserUpdate):
    """Update user's information"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Get current user from database
        cursor.execute(
            "SELECT email, password_hash FROM users WHERE id = ?",
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
        
        # Update email if provided
        if update_data.email is not None:
            # Validate email format
            email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
            if not re.match(email_regex, update_data.email):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid email address"
                )
            
            # Check if email already exists
            cursor.execute(
                "SELECT id FROM users WHERE email = ? AND id != ?",
                (update_data.email, user_id)
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already in use"
                )
            
            update_fields.append("email = ?")
            update_values.append(update_data.email)
        
        # Update password if provided
        if update_data.new_password is not None:
            if not update_data.current_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Current password is required to set new password"
                )
            
            # Verify current password
            if not auth_manager.verify_password(update_data.current_password, user['password_hash']):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Current password is incorrect"
                )
            
            # Validate new password
            if len(update_data.new_password) < 6:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="New password must be at least 6 characters"
                )
            
            # Hash new password
            new_password_hash = auth_manager.hash_password(update_data.new_password)
            update_fields.append("password_hash = ?")
            update_values.append(new_password_hash)
        
        # If no fields to update
        if not update_fields:
            return {
                "success": True,
                "message": "No changes to update"
            }
        
        # Build and execute update query
        update_values.append(user_id)
        update_query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = ?"
        
        cursor.execute(update_query, update_values)
        conn.commit()
        
        return {
            "success": True,
            "message": "User updated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user: {str(e)}"
        )
    finally:
        conn.close()

# ============ GAME ENDPOINTS ============

@app.post("/api/game/create")
async def create_game(game_data: GameCreate, user_id: str = Query(...)):
    """Create a new game - USING GAME MANAGER"""
    try:
        # Convert players to format expected by game manager
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
    """Join an existing game - USING GAME MANAGER"""
    try:
        # First get game ID from room code
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM games WHERE room_code = ?", (room_code.upper(),))
        game = cursor.fetchone()
        conn.close()
        
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
    """Get current game state (public) - USING GAME MANAGER"""
    try:
        # Check if identifier is a room code or game ID
        conn = get_db()
        cursor = conn.cursor()
        
        # Try to find game by ID or room code
        cursor.execute(
            """SELECT g.id 
               FROM games g 
               WHERE g.id = ? OR g.room_code = ?""",
            (identifier, identifier.upper())
        )
        result = cursor.fetchone()
        conn.close()
        
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
        
        return {
            "success": True,
            "game_state": game_state
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get game state: {str(e)}"
        )

@app.get("/api/game/{identifier}/state/private")
async def get_private_game_state(identifier: str, user_id: str = Query(...)):
    """Get game state with user-specific data (hides other players' cards) - FIXED"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Try to find game by ID or room code
        cursor.execute(
            """SELECT g.id, g.room_code, g.game_status, gs.state_json 
               FROM games g 
               LEFT JOIN game_states gs ON g.id = gs.game_id 
               WHERE g.id = ? OR g.room_code = ?""",
            (identifier, identifier.upper())
        )
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
        
        # Check if user is in the game
        cursor.execute(
            "SELECT id FROM game_players WHERE game_id = ? AND user_id = ?",
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
            
            # Filter sensitive information based on user
            filtered_state = game_state.copy()
            
            # Add deck_length if missing
            if 'deck' in filtered_state and 'deck_length' not in filtered_state:
                filtered_state['deck_length'] = len(filtered_state['deck'])
            
            # Only show current user's hand fully
            for player in filtered_state.get('players', []):
                if player.get('user_id') != user_id:
                    # FIX: Return array of hidden cards, one for each card in hand
                    hand_size = len(player.get('hand', []))
                    # Create an array of hidden card objects
                    hidden_cards = []
                    for i in range(hand_size):
                        hidden_cards.append({
                            'id': f'hidden_{player["id"]}_{i}',
                            'rank': '?',
                            'suit': 'hidden',
                            'value': 0,
                            'is_hidden': True
                        })
                    player['hand'] = hidden_cards
            
            print(f"🔍 DEBUG - Private state for {user_id}:")
            print(f"  - Deck length: {filtered_state.get('deck_length', 'N/A')}")
            print(f"  - Players hand sizes: {[(p['name'], len(p['hand'])) for p in filtered_state.get('players', [])]}")
            
            return {
                "success": True,
                "game_state": filtered_state
            }
        else:
            # Create basic state if none exists
            game_state = {
                'id': result['id'],
                'room_code': result['room_code'],
                'game_status': result['game_status'],
                'players': []
            }
            
            return {
                "success": True,
                "game_state": game_state
            }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in get_private_game_state: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get private game state: {str(e)}"
        )
    finally:
        conn.close()

@app.get("/api/game/{identifier}/lobby")
async def get_lobby_state(identifier: str):
    """Get lobby state (without cards) - public"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Try to find game by ID or room code
        cursor.execute(
            """SELECT g.id, g.room_code, g.game_name, g.game_status, g.max_players, 
                      g.created_at 
               FROM games g 
               WHERE g.id = ? OR g.room_code = ?""",
            (identifier, identifier.upper())
        )
        game = cursor.fetchone()
        
        if not game:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
        
        # Get players with their user info
        cursor.execute(
            """SELECT gp.id, gp.player_name, gp.position, gp.is_computer, 
                      gp.is_ready, gp.is_host, gp.joined_at, gp.user_id,
                      u.username
               FROM game_players gp
               LEFT JOIN users u ON gp.user_id = u.id
               WHERE gp.game_id = ? 
               ORDER BY gp.position""",
            (game['id'],)
        )
        players_data = cursor.fetchall()
        
        players = []
        for player in players_data:
            players.append({
                'id': player['id'],
                'name': player['player_name'],
                'position': player['position'],
                'is_computer': bool(player['is_computer']),
                'is_ready': bool(player['is_ready']),
                'is_host': bool(player['is_host']),
                'joined_at': player['joined_at'],
                'user_id': player['user_id'],
                'username': player['username']
            })
        
        return {
            "success": True,
            "game_state": {
                'id': game['id'],
                'room_code': game['room_code'],
                'game_name': game['game_name'],
                'game_status': game['game_status'],
                'max_players': game['max_players'],
                'created_at': game['created_at'],
                'players': players,
                'player_count': len(players),
                'can_start': len(players) >= 2
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get lobby state: {str(e)}"
        )
    finally:
        conn.close()

@app.post("/api/game/{identifier}/start")
async def start_game(identifier: str, user_id: str = Query(...)):
    """Start a game - FIXED: Ensure all players have 5 cards"""
    try:
        # Get game ID from identifier
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT id FROM games WHERE id = ? OR room_code = ?",
            (identifier, identifier.upper())
        )
        game = cursor.fetchone()
        
        if not game:
            conn.close()
            raise HTTPException(status_code=404, detail="Game not found")
        
        # First, get the current game state
        cursor.execute(
            "SELECT state_json FROM game_states WHERE game_id = ?",
            (game['id'],)
        )
        state_row = cursor.fetchone()
        
        if state_row:
            game_state = json.loads(state_row['state_json'])
            
            # Ensure all players have exactly 5 cards
            deck = game_state.get('deck', [])
            players = game_state.get('players', [])
            
            print(f"🎮 DEBUG - Starting game {identifier}")
            print(f"🎮 DEBUG - Current deck size: {len(deck)}")
            print(f"🎮 DEBUG - Player hand sizes before: {[(p['name'], len(p.get('hand', []))) for p in players]}")
            
            # If any player doesn't have 5 cards, fix it
            for player in players:
                current_hand = player.get('hand', [])
                if len(current_hand) < 5 and deck:
                    cards_needed = 5 - len(current_hand)
                    print(f"🎮 DEBUG - Player {player['name']} needs {cards_needed} more cards")
                    for _ in range(cards_needed):
                        if deck:
                            current_hand.append(deck.pop())
                    player['hand'] = current_hand
            
            # Update game state
            game_state['deck'] = deck
            game_state['deck_length'] = len(deck)
            game_state['game_status'] = 'playing'
            game_state['turn_phase'] = 'draw'
            game_state['current_player_index'] = 0
            
            # Update first player's turn
            for i, player in enumerate(game_state['players']):
                player['is_current_turn'] = (i == 0)
            
            print(f"🎮 DEBUG - Player hand sizes after: {[(p['name'], len(p.get('hand', []))) for p in players]}")
            
            # Save updated state
            cursor.execute(
                "UPDATE game_states SET state_json = ? WHERE game_id = ?",
                (json.dumps(game_state), game['id'])
            )
            
            # Update game status
            cursor.execute(
                "UPDATE games SET game_status = 'playing', started_at = ? WHERE id = ?",
                (datetime.now().isoformat(), game['id'])
            )
            
            conn.commit()
        
        conn.close()
        
        # Now call the game manager's start_game
        result = game_manager.start_game(
            game_id=game['id'],
            user_id=user_id
        )
        
        # Ensure the returned game state has deck_length
        if result.get('game_state'):
            game_state = result['game_state']
            if 'deck' in game_state and 'deck_length' not in game_state:
                game_state['deck_length'] = len(game_state['deck'])
            result['game_state'] = game_state
        
        return result
        
    except Exception as e:
        print(f"❌ Error starting game: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@app.post("/api/game/{game_id}/move")
async def make_move(game_id: str, move_request: MoveRequest):
    """Make a move in the game - USING GAME MANAGER"""
    try:
        result = game_manager.make_move(
            game_id=game_id,
            player_id=move_request.player_id,
            user_id=move_request.user_id,
            move_type=move_request.moveType,
            move_data=move_request.moveData
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@app.post("/api/game/{game_id}/move-enhanced")
async def make_enhanced_move(game_id: str, move_request: MoveRequest):
    """Make a move with enhanced game logic"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Verify user is in the game
        if not verify_user_in_game(game_id, move_request.user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User not in this game"
            )
        
        # Verify player belongs to user
        if not verify_player_belongs_to_user(game_id, move_request.player_id, move_request.user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Player does not belong to user"
            )
        
        # Get game and state
        cursor.execute(
            "SELECT game_status FROM games WHERE id = ?",
            (game_id,)
        )
        game = cursor.fetchone()
        
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        
        if game['game_status'] != 'playing':
            raise HTTPException(status_code=400, detail="Game is not in progress")
        
        cursor.execute(
            "SELECT state_json FROM game_states WHERE game_id = ?",
            (game_id,)
        )
        state_record = cursor.fetchone()
        
        if not state_record:
            raise HTTPException(status_code=404, detail="Game state not found")
        
        game_state = json.loads(state_record['state_json'])
        
        # Validate player turn
        current_player_idx = game_state.get('current_player_index', 0)
        current_player = game_state['players'][current_player_idx] if game_state['players'] else None
        
        if not current_player or current_player['id'] != move_request.player_id:
            raise HTTPException(status_code=400, detail="Not player's turn")
        
        # Process move based on type
        move_result = {
            'success': False,
            'message': '',
            'game_state': game_state
        }
        
        player = next((p for p in game_state['players'] if p['id'] == move_request.player_id), None)
        
        if move_request.moveType == 'draw_from_deck':
            if game_state['deck']:
                drawn_card = game_state['deck'].pop()
                player['hand'].append(drawn_card)
                game_state['turn_phase'] = 'play'
                move_result['success'] = True
                move_result['message'] = f"Drew {drawn_card['rank']} of {drawn_card['suit']}"
            else:
                raise HTTPException(status_code=400, detail="Deck is empty")
        
        elif move_request.moveType == 'draw_from_discard':
            if game_state['discard_pile']:
                drawn_card = game_state['discard_pile'].pop()
                player['hand'].append(drawn_card)
                game_state['turn_phase'] = 'play'
                move_result['success'] = True
                move_result['message'] = f"Drew {drawn_card['rank']} of {drawn_card['suit']} from discard"
            else:
                raise HTTPException(status_code=400, detail="Discard pile is empty")
        
        elif move_request.moveType == 'discard':
            card_id = move_request.moveData.get('cardId')
            if not card_id:
                raise HTTPException(status_code=400, detail="No card specified")
            
            # Find and remove card from hand
            card_index = None
            for i, card in enumerate(player['hand']):
                if card.get('id') == card_id:
                    card_index = i
                    break
            
            if card_index is None:
                raise HTTPException(status_code=400, detail="Card not found in hand")
            
            discarded_card = player['hand'].pop(card_index)
            game_state['discard_pile'].append(discarded_card)
            
            # Check for Tonk after discard
            def check_for_tonk(hand):
                """Check if player has Tonk (5 points or less)"""
                total = 0
                for card in hand:
                    if card['rank'] in ['J', 'Q', 'K']:
                        total += 10
                    elif card['rank'] == 'A':
                        total += 1
                    else:
                        total += int(card['rank'])
                return total <= 5
            
            if check_for_tonk(player['hand']):
                game_state['game_status'] = 'game_over'
                game_state['winner'] = player['name']
                game_state['win_reason'] = 'tonk'
                move_result['message'] = f"{player['name']} got TONK! Game over!"
            else:
                # Move to next player
                game_state['current_player_index'] = (current_player_idx + 1) % len(game_state['players'])
                game_state['turn_phase'] = 'draw'
                game_state['turn_count'] = game_state.get('turn_count', 0) + 1
                move_result['message'] = f"{player['name']} discarded {discarded_card['rank']} of {discarded_card['suit']}"
        
        elif move_request.moveType == 'play_spread':
            spread_cards = move_request.moveData.get('cards', [])
            if len(spread_cards) < 3:
                raise HTTPException(status_code=400, detail="Spread must have at least 3 cards")
            
            # Validate spread
            def is_valid_spread(cards):
                """Check if cards form a valid spread (run or set)"""
                if len(cards) < 3:
                    return False
                
                # Check for set (same rank)
                ranks = [card['rank'] for card in cards]
                if len(set(ranks)) == 1:
                    return True
                
                # Check for run (consecutive ranks, same suit)
                suits = [card['suit'] for card in cards]
                if len(set(suits)) > 1:
                    return False
                
                # Sort by rank value
                rank_order = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
                sorted_cards = sorted(cards, key=lambda x: rank_order.index(x['rank']))
                
                for i in range(1, len(sorted_cards)):
                    current_idx = rank_order.index(sorted_cards[i]['rank'])
                    prev_idx = rank_order.index(sorted_cards[i-1]['rank'])
                    if current_idx != prev_idx + 1:
                        return False
                
                return True
            
            spread_cards_objects = []
            for card_id in spread_cards:
                card_found = False
                for i, card in enumerate(player['hand']):
                    if card.get('id') == card_id:
                        spread_cards_objects.append(card)
                        player['hand'].pop(i)
                        card_found = True
                        break
                if not card_found:
                    raise HTTPException(status_code=400, detail=f"Card {card_id} not found in hand")
            
            if not is_valid_spread(spread_cards_objects):
                # Return cards to hand
                player['hand'].extend(spread_cards_objects)
                raise HTTPException(status_code=400, detail="Invalid spread")
            
            # Add spread to table
            if 'table_spreads' not in game_state:
                game_state['table_spreads'] = []
            
            game_state['table_spreads'].append({
                'id': f"spread_{len(game_state['table_spreads'])}",
                'cards': spread_cards_objects,
                'player': player['name'],
                'player_id': player['id']
            })
            
            move_result['success'] = True
            move_result['message'] = f"{player['name']} played a spread"
        
        # Update last move
        game_state['last_move'] = {
            'player_id': move_request.player_id,
            'user_id': move_request.user_id,
            'player_name': player['name'],
            'move_type': move_request.moveType,
            'move_data': move_request.moveData,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Save updated state
        cursor.execute(
            "UPDATE game_states SET state_json = ?, last_updated = CURRENT_TIMESTAMP WHERE game_id = ?",
            (json.dumps(game_state), game_id)
        )
        
        # Update game if over
        if game_state['game_status'] == 'game_over':
            cursor.execute(
                "UPDATE games SET game_status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (game_id,)
            )
        
        conn.commit()
        
        move_result['game_state'] = game_state
        move_result['success'] = True
        
        return move_result
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to make move: {str(e)}"
        )
    finally:
        conn.close()

@app.get("/api/game/room/{room_code}/id")
async def get_game_id(room_code: str):
    """Get game ID from room code"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT id FROM games WHERE room_code = ?",
            (room_code.upper(),)
        )
        game = cursor.fetchone()
        
        if not game:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
        
        return {
            "success": True,
            "game_id": game['id']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get game ID: {str(e)}"
        )
    finally:
        conn.close()

# ============ ADMIN ENDPOINTS ============

@app.get("/api/admin/export/json")
async def export_database_json(admin_token: str = Form(...)):
    """Export entire database as JSON (protected)"""
    if admin_token != "tonk_admin_123":
        raise HTTPException(status_code=403, detail="Invalid admin token")
    
    data = export_database()
    return JSONResponse(content=data)

@app.get("/api/admin/export/csv")
async def export_database_csv_endpoint(admin_token: str = Form(...)):
    """Export entire database as CSV (protected)"""
    if admin_token != "tonk_admin_123":
        raise HTTPException(status_code=403, detail="Invalid admin token")
    
    csv_data = export_database_csv()
    return StreamingResponse(
        io.StringIO(csv_data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tonk_database.csv"}
    )

@app.post("/api/admin/import")
async def import_database_endpoint(
    admin_token: str = Form(...),
    file: UploadFile = File(...)
):
    """Import database from JSON file"""
    if admin_token != "tonk_admin_123":
        raise HTTPException(status_code=403, detail="Invalid admin token")
    
    try:
        content = await file.read()
        data = json.loads(content.decode('utf-8'))
        
        result = import_database(data)
        
        if result['success']:
            return {"success": True, "message": result['message']}
        else:
            raise HTTPException(status_code=400, detail=result['error'])
            
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/stats")
async def get_database_stats(admin_token: str = Form(...)):
    """Get database statistics"""
    if admin_token != "tonk_admin_123":
        raise HTTPException(status_code=403, detail="Invalid admin token")
    
    conn = get_db()
    cursor = conn.cursor()
    
    stats = {}
    
    cursor.execute("SELECT COUNT(*) FROM users")
    stats['total_users'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM games")
    stats['total_games'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM game_players")
    stats['total_players'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM games WHERE game_status = 'playing'")
    stats['active_games'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM games WHERE game_status = 'lobby'")
    stats['lobby_games'] = cursor.fetchone()[0]
    
    conn.close()
    
    return stats

# Run the app
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Starting Tonk API server on port {port}")
    print(f"📁 Database file: {DATABASE_FILE}")
    print('New update verified!')
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    