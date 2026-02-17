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
                if player.get('user_id') != user_id:
                    hand_size = len(player.get('hand', []))
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
            return {"success": True, "game_state": filtered_state}
        else:
            game_state = {
                'id': result['id'],
                'room_code': result['room_code'],
                'game_status': result['game_status'],
                'players': []
            }
            return {"success": True, "game_state": game_state}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get private game state: {str(e)}"
        )
    finally:
        db.return_connection(conn)

@app.get("/api/game/{identifier}/lobby")
async def get_lobby_state(identifier: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT g.id, g.room_code, g.game_name, g.game_status, g.max_players, 
                      g.created_at 
               FROM games g 
               WHERE g.id = %s OR g.room_code = %s""",
            (identifier, identifier.upper())
        )
        game = cursor.fetchone()
        if not game:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
        cursor.execute(
            """SELECT gp.id, gp.player_name, gp.position, gp.is_computer, 
                      gp.is_ready, gp.is_host, gp.joined_at, gp.user_id,
                      u.username
               FROM game_players gp
               LEFT JOIN users u ON gp.user_id = u.id
               WHERE gp.game_id = %s 
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
        db.return_connection(conn)

@app.post("/api/game/{identifier}/start")
async def start_game(identifier: str, user_id: str = Query(...)):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM games WHERE id = %s OR room_code = %s",
            (identifier, identifier.upper())
        )
        game = cursor.fetchone()
        if not game:
            db.return_connection(conn)
            raise HTTPException(status_code=404, detail="Game not found")
        
        cursor.execute(
            "SELECT state_json FROM game_states WHERE game_id = %s",
            (game['id'],)
        )
        state_row = cursor.fetchone()
        if state_row:
            game_state = json.loads(state_row['state_json'])
            deck = game_state.get('deck', [])
            players = game_state.get('players', [])
            for player in players:
                current_hand = player.get('hand', [])
                if len(current_hand) < 5 and deck:
                    cards_needed = 5 - len(current_hand)
                    for _ in range(cards_needed):
                        if deck:
                            current_hand.append(deck.pop())
                    player['hand'] = current_hand
            game_state['deck'] = deck
            game_state['deck_length'] = len(deck)
            game_state['game_status'] = 'playing'
            game_state['turn_phase'] = 'draw'
            game_state['current_player_index'] = 0
            for i, player in enumerate(game_state['players']):
                player['is_current_turn'] = (i == 0)
            cursor.execute(
                "UPDATE game_states SET state_json = %s WHERE game_id = %s",
                (json.dumps(game_state), game['id'])
            )
            cursor.execute(
                "UPDATE games SET game_status = 'playing', started_at = %s WHERE id = %s",
                (datetime.now().isoformat(), game['id'])
            )
            conn.commit()
        db.return_connection(conn)
        result = game_manager.start_game(
            game_id=game['id'],
            user_id=user_id
        )
        if result.get('game_state'):
            game_state = result['game_state']
            if 'deck' in game_state and 'deck_length' not in game_state:
                game_state['deck_length'] = len(game_state['deck'])
            result['game_state'] = game_state
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@app.post("/api/game/{game_id}/move")
async def make_move(game_id: str, move_request: MoveRequest):
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
    conn = get_db()
    cursor = conn.cursor()
    
    def check_for_tonk(hand):
        total = 0
        for card in hand:
            if card['rank'] in ['J', 'Q', 'K']:
                total += 10
            elif card['rank'] == 'A':
                total += 1
            else:
                try:
                    total += int(card['rank'])
                except ValueError:
                    total += 0
        return total <= 5
    
    def is_valid_spread(cards):
        if len(cards) < 3:
            return False
        ranks = [card['rank'] for card in cards]
        if len(set(ranks)) == 1:
            return True
        suits = [card['suit'] for card in cards]
        if len(set(suits)) > 1:
            return False
        rank_order = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        sorted_cards = sorted(cards, key=lambda x: rank_order.index(x['rank']))
        for i in range(1, len(sorted_cards)):
            current_idx = rank_order.index(sorted_cards[i]['rank'])
            prev_idx = rank_order.index(sorted_cards[i-1]['rank'])
            if current_idx != prev_idx + 1:
                return False
        return True
    
    def is_valid_hit(card, spread_cards):
        ranks = [c['rank'] for c in spread_cards]
        if len(set(ranks)) == 1:
            return card['rank'] == spread_cards[0]['rank']
        suits = [c['suit'] for c in spread_cards]
        if len(set(suits)) != 1:
            return False
        rank_order = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        sorted_cards = sorted(spread_cards, key=lambda x: rank_order.index(x['rank']))
        if card['suit'] != sorted_cards[0]['suit']:
            return False
        first_rank_idx = rank_order.index(sorted_cards[0]['rank'])
        last_rank_idx = rank_order.index(sorted_cards[-1]['rank'])
        card_rank_idx = rank_order.index(card['rank'])
        return card_rank_idx == first_rank_idx - 1 or card_rank_idx == last_rank_idx + 1
    
    try:
        if not verify_user_in_game(game_id, move_request.user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User not in this game"
            )
        if not verify_player_belongs_to_user(game_id, move_request.player_id, move_request.user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Player does not belong to user"
            )
        
        cursor.execute(
            "SELECT game_status FROM games WHERE id = %s",
            (game_id,)
        )
        game = cursor.fetchone()
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        if game['game_status'] != 'playing':
            raise HTTPException(status_code=400, detail="Game is not in progress")
        
        cursor.execute(
            "SELECT state_json FROM game_states WHERE game_id = %s",
            (game_id,)
        )
        state_record = cursor.fetchone()
        if not state_record:
            raise HTTPException(status_code=404, detail="Game state not found")
        
        game_state = json.loads(state_record['state_json'])
        current_player_idx = game_state.get('current_player_index', 0)
        current_player = game_state['players'][current_player_idx] if game_state['players'] else None
        if not current_player or current_player['id'] != move_request.player_id:
            raise HTTPException(status_code=400, detail="Not player's turn")
        
        move_result = {'success': False, 'message': '', 'game_state': game_state}
        player = next((p for p in game_state['players'] if p['id'] == move_request.player_id), None)
        if not player:
            raise HTTPException(status_code=400, detail="Player not found")
        
        turn_phase = game_state.get('turn_phase', 'waiting')
        move_type = move_request.moveType
        
        if move_type == 'draw_from_deck':
            if turn_phase != 'draw':
                raise HTTPException(status_code=400, detail="Not in draw phase")
            if not game_state['deck']:
                raise HTTPException(status_code=400, detail="Deck is empty")
            drawn_card = game_state['deck'].pop()
            player['hand'].append(drawn_card)
            game_state['turn_phase'] = 'play'
            move_result['success'] = True
            move_result['message'] = f"Drew {drawn_card['rank']} of {drawn_card['suit']}"
        
        elif move_type == 'draw_from_discard':
            if turn_phase != 'draw':
                raise HTTPException(status_code=400, detail="Not in draw phase")
            if not game_state['discard_pile']:
                raise HTTPException(status_code=400, detail="Discard pile is empty")
            drawn_card = game_state['discard_pile'].pop()
            player['hand'].append(drawn_card)
            game_state['turn_phase'] = 'play'
            move_result['success'] = True
            move_result['message'] = f"Drew {drawn_card['rank']} of {drawn_card['suit']} from discard"
        
        elif move_type == 'discard':
            if turn_phase != 'play':
                raise HTTPException(status_code=400, detail="Not in play phase")
            card_id = move_request.moveData.get('cardId')
            if not card_id:
                raise HTTPException(status_code=400, detail="No card specified")
            card_index = None
            for i, card in enumerate(player['hand']):
                if card.get('id') == card_id:
                    card_index = i
                    break
            if card_index is None:
                raise HTTPException(status_code=400, detail="Card not found in hand")
            discarded_card = player['hand'].pop(card_index)
            game_state['discard_pile'].append(discarded_card)
            if check_for_tonk(player['hand']):
                game_state['game_status'] = 'game_over'
                game_state['winner'] = player['name']
                game_state['win_reason'] = 'tonk'
                move_result['message'] = f"{player['name']} got TONK! Game over!"
            else:
                next_player_idx = (current_player_idx + 1) % len(game_state['players'])
                game_state['current_player_index'] = next_player_idx
                game_state['turn_phase'] = 'draw'
                game_state['turn_count'] = game_state.get('turn_count', 0) + 1
                for i, p in enumerate(game_state['players']):
                    p['is_current_turn'] = (i == next_player_idx)
                move_result['message'] = f"{player['name']} discarded {discarded_card['rank']} of {discarded_card['suit']}"
            move_result['success'] = True
        
        elif move_type == 'play_spread':
            if turn_phase != 'play':
                raise HTTPException(status_code=400, detail="Not in play phase")
            spread_cards = move_request.moveData.get('cards', [])
            if len(spread_cards) < 3:
                raise HTTPException(status_code=400, detail="Spread must have at least 3 cards")
            spread_cards_objects = []
            cards_to_remove = []
            for card_id in spread_cards:
                card_found = False
                for i, card in enumerate(player['hand']):
                    if card.get('id') == card_id:
                        spread_cards_objects.append(card)
                        cards_to_remove.append(i)
                        card_found = True
                        break
                if not card_found:
                    raise HTTPException(status_code=400, detail=f"Card {card_id} not found in hand")
            if not is_valid_spread(spread_cards_objects):
                raise HTTPException(status_code=400, detail="Invalid spread - must be a set (same rank) or run (consecutive ranks, same suit)")
            for index in sorted(cards_to_remove, reverse=True):
                player['hand'].pop(index)
            if 'table_spreads' not in game_state:
                game_state['table_spreads'] = []
            if len(set([c['rank'] for c in spread_cards_objects])) > 1:
                rank_order = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
                spread_cards_objects = sorted(spread_cards_objects, key=lambda x: rank_order.index(x['rank']))
            spread_id = f"spread_{len(game_state['table_spreads'])}"
            game_state['table_spreads'].append({
                'id': spread_id,
                'cards': spread_cards_objects,
                'player': player['name'],
                'player_id': player['id'],
                'created_at': datetime.utcnow().isoformat()
            })
            move_result['success'] = True
            move_result['message'] = f"{player['name']} played a spread with {len(spread_cards_objects)} cards"
        
        elif move_type == 'hit_spread':
            if turn_phase != 'play':
                raise HTTPException(status_code=400, detail="Not in play phase")
            card_id = move_request.moveData.get('cardId')
            spread_id = move_request.moveData.get('spreadId')
            if not card_id or not spread_id:
                raise HTTPException(status_code=400, detail="Missing cardId or spreadId")
            card_to_play = None
            card_index = None
            for i, card in enumerate(player['hand']):
                if card.get('id') == card_id:
                    card_to_play = card
                    card_index = i
                    break
            if not card_to_play:
                raise HTTPException(status_code=400, detail="Card not found in hand")
            spread_to_hit = None
            spread_index = None
            for i, spread in enumerate(game_state.get('table_spreads', [])):
                if spread.get('id') == spread_id:
                    spread_to_hit = spread
                    spread_index = i
                    break
            if not spread_to_hit:
                raise HTTPException(status_code=400, detail="Spread not found on table")
            if not is_valid_hit(card_to_play, spread_to_hit['cards']):
                raise HTTPException(status_code=400, detail="Invalid hit - card doesn't match spread")
            player['hand'].pop(card_index)
            spread_to_hit['cards'].append(card_to_play)
            if len(set([c['rank'] for c in spread_to_hit['cards']])) > 1:
                rank_order = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
                spread_to_hit['cards'] = sorted(spread_to_hit['cards'], key=lambda x: rank_order.index(x['rank']))
            game_state['table_spreads'][spread_index] = spread_to_hit
            move_result['success'] = True
            move_result['message'] = f"{player['name']} hit {spread_to_hit['player']}'s spread"
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown move type: {move_type}")
        
        game_state['last_move'] = {
            'player_id': move_request.player_id,
            'user_id': move_request.user_id,
            'player_name': player['name'],
            'move_type': move_type,
            'move_data': move_request.moveData,
            'timestamp': datetime.utcnow().isoformat()
        }
        if 'deck' in game_state:
            game_state['deck_length'] = len(game_state['deck'])
        
        cursor.execute(
            "UPDATE game_states SET state_json = %s, last_updated = CURRENT_TIMESTAMP WHERE game_id = %s",
            (json.dumps(game_state), game_id)
        )
        if game_state['game_status'] == 'game_over':
            cursor.execute(
                "UPDATE games SET game_status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = %s",
                (game_id,)
            )
        conn.commit()
        move_result['game_state'] = game_state
        if not move_result.get('success'):
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
        db.return_connection(conn)

@app.get("/api/game/room/{room_code}/id")
async def get_game_id(room_code: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id FROM games WHERE room_code = %s",
            (room_code.upper(),)
        )
        game = cursor.fetchone()
        if not game:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
        return {"success": True, "game_id": game['id']}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get game ID: {str(e)}"
        )
    finally:
        db.return_connection(conn)

@app.post("/api/game/{game_id}/ai-move")
async def trigger_ai_move(game_id: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT state_json FROM game_states WHERE game_id = %s",
            (game_id,)
        )
        state_record = cursor.fetchone()
        if not state_record:
            raise HTTPException(status_code=404, detail="Game state not found")
        game_state = json.loads(state_record['state_json'])
        current_player_idx = game_state.get('current_player_index', 0)
        current_player = game_state['players'][current_player_idx] if game_state['players'] else None
        if not current_player or not current_player.get('is_computer', False):
            return {"success": False, "message": "Current player is not a CPU", "game_state": game_state}
        
        def ai_make_move():
            turn_phase = game_state.get('turn_phase', 'draw')
            if turn_phase == 'draw':
                if game_state['deck']:
                    drawn_card = game_state['deck'].pop()
                    current_player['hand'].append(drawn_card)
                    game_state['turn_phase'] = 'play'
                    return f"CPU drew {drawn_card['rank']} of {drawn_card['suit']}"
                elif game_state['discard_pile']:
                    drawn_card = game_state['discard_pile'].pop()
                    current_player['hand'].append(drawn_card)
                    game_state['turn_phase'] = 'play'
                    return f"CPU drew from discard: {drawn_card['rank']} of {drawn_card['suit']}"
                else:
                    return "No cards to draw"
            elif turn_phase == 'play':
                if not current_player['hand']:
                    return "No cards to discard"
                card_to_discard = None
                highest_value = -1
                for card in current_player['hand']:
                    card_value = card.get('value', 0)
                    if card_value > highest_value:
                        highest_value = card_value
                        card_to_discard = card
                if card_to_discard:
                    current_player['hand'].remove(card_to_discard)
                    game_state['discard_pile'].append(card_to_discard)
                    def check_tonk(hand):
                        total = 0
                        for card in hand:
                            if card['rank'] in ['J', 'Q', 'K']:
                                total += 10
                            elif card['rank'] == 'A':
                                total += 1
                            else:
                                total += int(card['rank'])
                        return total <= 5
                    if check_tonk(current_player['hand']):
                        game_state['game_status'] = 'game_over'
                        game_state['winner'] = current_player['name']
                        game_state['win_reason'] = 'tonk'
                        message = f"{current_player['name']} got TONK! Game over!"
                    else:
                        game_state['current_player_index'] = (current_player_idx + 1) % len(game_state['players'])
                        game_state['turn_phase'] = 'draw'
                        game_state['turn_count'] = game_state.get('turn_count', 0) + 1
                        message = f"{current_player['name']} discarded {card_to_discard['rank']} of {card_to_discard['suit']}"
                    return message
        
        ai_message = ai_make_move()
        game_state['last_move'] = {
            'player_id': current_player['id'],
            'player_name': current_player['name'],
            'move_type': game_state['turn_phase'],
            'timestamp': datetime.utcnow().isoformat()
        }
        cursor.execute(
            "UPDATE game_states SET state_json = %s, last_updated = CURRENT_TIMESTAMP WHERE game_id = %s",
            (json.dumps(game_state), game_id)
        )
        if game_state['game_status'] == 'game_over':
            cursor.execute(
                "UPDATE games SET game_status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = %s",
                (game_id,)
            )
        conn.commit()
        return {"success": True, "message": f"AI move: {ai_message}", "game_state": game_state}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to make AI move: {str(e)}"
        )
    finally:
        db.return_connection(conn)

# ============ ADMIN ENDPOINTS ============
@app.get("/api/admin/export/json")
async def export_database_json(admin_token: str = Form(...)):
    if admin_token != "tonk_admin_123":
        raise HTTPException(status_code=403, detail="Invalid admin token")
    data = export_database()
    return JSONResponse(content=data)

@app.get("/api/admin/export/csv")
async def export_database_csv_endpoint(admin_token: str = Form(...)):
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
    if admin_token != "tonk_admin_123":
        raise HTTPException(status_code=403, detail="Invalid admin token")
    conn = get_db()
    cursor = conn.cursor()
    stats = {}
    try:
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
        return stats
    finally:
        db.return_connection(conn)

# Run the app
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Starting Tonk API server on port {port}")
    print(f"📁 Database: PostgreSQL")
    print('New update verified!')
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")