# CRITICAL FIXES FOR APP.PY
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import json
import traceback
import uuid
import sqlite3
import random
import bcrypt
import jwt
import os

app = FastAPI(title="Tonk Game API - Fixed")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ CONFIGURATION ============
SECRET_KEY = os.environ.get("SECRET_KEY", "tonk-secure-key-12345-change-in-production")
ALGORITHM = "HS256"

# ============ MODELS ============
class UserRegister(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class CreateGameRequest(BaseModel):
    players: List[Dict]
    game_name: Optional[str] = None
    userId: Optional[str] = None

class JoinGameRequest(BaseModel):
    playerName: str
    userId: Optional[str] = None

class MoveRequest(BaseModel):
    playerId: str
    moveType: str
    moveData: Dict

class PlayerReadyRequest(BaseModel):
    is_ready: bool = True

# ============ DATABASE SETUP ============
def init_db():
    """Initialize database"""
    print("🔄 Initializing database...")
    
    try:
        conn = sqlite3.connect("tonk_game.db")
        cursor = conn.cursor()
        
        # Users table
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
        
        # Games table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            room_code TEXT UNIQUE NOT NULL,
            game_name TEXT,
            deck TEXT,
            discard_pile TEXT,
            under_card TEXT,
            current_player_index INTEGER DEFAULT 0,
            turn_phase TEXT DEFAULT 'waiting',
            table_spreads TEXT,
            turn_count INTEGER DEFAULT 0,
            game_status TEXT DEFAULT 'lobby',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_move TEXT,
            settings TEXT DEFAULT '{}',
            winner TEXT,
            win_reason TEXT,
            creator_id TEXT,
            max_players INTEGER DEFAULT 4,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Players table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_players (
            id TEXT PRIMARY KEY,
            game_id TEXT NOT NULL,
            user_id TEXT,
            name TEXT NOT NULL,
            is_computer BOOLEAN DEFAULT 0,
            hand TEXT DEFAULT '[]',
            spreads TEXT DEFAULT '[]',
            has_dropped BOOLEAN DEFAULT 0,
            score INTEGER DEFAULT 0,
            last_move TEXT,
            turns INTEGER DEFAULT 0,
            has_drawn_from_under BOOLEAN DEFAULT 0,
            is_online BOOLEAN DEFAULT 1,
            position INTEGER,
            is_ready BOOLEAN DEFAULT 1
        )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Database initialized successfully")
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        open("tonk_game.db", "a").close()
        print("📁 Created empty database file")

@app.on_event("startup")
def startup():
    print("🚀 Tonk API starting...")
    init_db()
    print("✅ Server ready")

def get_db():
    """Get database connection"""
    try:
        conn = sqlite3.connect("tonk_game.db")
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        init_db()
        conn = sqlite3.connect("tonk_game.db")
        conn.row_factory = sqlite3.Row
        return conn

# ============ AUTH UTILITIES ============
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_token(username: str, user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=24)
    payload = {
        "sub": username,
        "user_id": user_id,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# ============ CARD & GAME UTILITIES ============
def create_deck():
    """Create a standard 52-card deck"""
    suits = ["hearts", "diamonds", "clubs", "spades"]
    ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    deck = []
    
    for suit in suits:
        for rank in ranks:
            value = 10 if rank in ["J", "Q", "K"] else 1 if rank == "A" else int(rank)
            suit_symbol = {"hearts": "♥", "diamonds": "♦", "clubs": "♣", "spades": "♠"}.get(suit, "")
            
            deck.append({
                "id": str(uuid.uuid4()),
                "suit": suit,
                "rank": rank,
                "value": value,
                "isFaceUp": False,
                "suitSymbol": suit_symbol,
                "color": "red" if suit in ["hearts", "diamonds"] else "black"
            })
    
    random.shuffle(deck)
    return deck

def safe_json_parse(value, default):
    """Safely parse JSON with error handling"""
    if not value:
        return default
    try:
        return json.loads(value)
    except:
        return default

# ============ HEALTH ENDPOINTS ============
@app.get("/api/ping")
async def ping():
    return {
        "status": "pong",
        "timestamp": datetime.now().isoformat(),
        "server": "TonkAPI",
        "environment": "Render.com"
    }

@app.get("/api/warmup")
async def warmup():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        conn.close()
        return {
            "status": "ready",
            "database": "connected",
            "tables": [t[0] for t in tables],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "error",
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.get("/api/status")
async def status():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM games")
        game_count = cursor.fetchone()[0]
        conn.close()
        return {
            "online": True,
            "status": "running",
            "database": "connected",
            "users": user_count,
            "games": game_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "online": False,
            "status": "error",
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# ============ AUTH ENDPOINTS ============
@app.post("/api/auth/register")
async def register_user(user_data: UserRegister):
    try:
        if not user_data.username or not user_data.email or not user_data.password:
            raise HTTPException(400, "Username, email, and password are required")
        
        if len(user_data.password) < 3:
            raise HTTPException(400, "Password must be at least 3 characters")
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (user_data.username,))
        if cursor.fetchone():
            raise HTTPException(400, "Username already exists")
        
        cursor.execute("SELECT id FROM users WHERE email = ?", (user_data.email,))
        if cursor.fetchone():
            raise HTTPException(400, "Email already exists")
        
        user_id = str(uuid.uuid4())
        hashed_password = hash_password(user_data.password)
        created_at = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO users (id, username, email, hashed_password, created_at, online, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, user_data.username, user_data.email, hashed_password, created_at, 1, created_at))
        
        conn.commit()
        token = create_token(user_data.username, user_id)
        conn.close()
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user_id,
            "username": user_data.username,
            "message": "Registration successful"
        }
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(500, f"Registration failed: {str(e)}")

@app.post("/api/auth/login")
async def login_user(user_data: UserLogin):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (user_data.username,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            raise HTTPException(401, "Invalid username or password")
        
        if not verify_password(user_data.password, user['hashed_password']):
            conn.close()
            raise HTTPException(401, "Invalid username or password")
        
        cursor.execute(
            "UPDATE users SET last_seen = ?, online = 1 WHERE id = ?",
            (datetime.now().isoformat(), user['id'])
        )
        conn.commit()
        token = create_token(user_data.username, user['id'])
        conn.close()
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user['id'],
            "username": user['username'],
            "message": "Login successful"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Login failed: {str(e)}")

@app.get("/api/auth/validate-token")
async def validate_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "No token provided")
    
    token = authorization.split(" ")[1]
    payload = decode_token(token)
    
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    
    return {
        "valid": True,
        "username": payload.get("sub"),
        "user_id": payload.get("user_id")
    }

# ============ GAME ENDPOINTS ============
@app.post("/api/game/create")
async def create_game(request: CreateGameRequest):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        game_id = str(uuid.uuid4())
        room_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        deck = create_deck()
        
        cursor.execute('''
            INSERT INTO games (id, room_code, game_name, deck, creator_id, created_at, last_updated, settings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            game_id, room_code, request.game_name or "Tonk Game", 
            json.dumps(deck), request.userId, 
            datetime.now().isoformat(), datetime.now().isoformat(),
            '{"allow_under_card_any_turn": true}'
        ))
        
        first_player_id = None
        for i, player_data in enumerate(request.players):
            player_id = str(uuid.uuid4())
            player_user_id = request.userId if i == 0 else None
            is_computer = player_data.get("isComputer", False) or player_data.get("is_computer", False)
            
            cursor.execute('''
                INSERT INTO game_players (id, game_id, user_id, name, is_computer, position)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (player_id, game_id, player_user_id, player_data["name"], 1 if is_computer else 0, i))
            
            if i == 0:
                first_player_id = player_id
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "gameId": game_id,
            "roomCode": room_code,
            "playerId": first_player_id,
            "gameName": request.game_name or "Tonk Game",
            "message": "Game created successfully"
        }
        
    except Exception as e:
        print(f"Create game error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to create game: {str(e)}")

@app.post("/api/game/{room_code}/join")
async def join_game(room_code: str, request: JoinGameRequest):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, game_status, max_players FROM games WHERE room_code = ?", (room_code.upper(),))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, f"Game not found with code: {room_code}")
        
        game_id = game_row['id']
        if game_row['game_status'] != 'lobby':
            conn.close()
            raise HTTPException(400, "Game has already started")
        
        cursor.execute("SELECT COUNT(*) FROM game_players WHERE game_id = ?", (game_id,))
        player_count = cursor.fetchone()[0]
        
        if player_count >= game_row['max_players']:
            conn.close()
            raise HTTPException(400, "Game is full (max 4 players)")
        
        cursor.execute("SELECT id FROM game_players WHERE game_id = ? AND name = ?", (game_id, request.playerName))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(400, f"Player name '{request.playerName}' is already taken")
        
        player_id = str(uuid.uuid4())
        position = player_count
        
        cursor.execute('''
            INSERT INTO game_players (id, game_id, user_id, name, is_computer, position, is_online)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (player_id, game_id, request.userId, request.playerName, 0, position, 1))
        
        cursor.execute("UPDATE games SET last_updated = ? WHERE id = ?", (datetime.now().isoformat(), game_id))
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "gameId": game_id,
            "playerId": player_id,
            "message": f"Joined game as {request.playerName}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Join game error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to join game: {str(e)}")

@app.post("/api/game/{game_id}/start")
async def start_game(game_id: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        if game_row['game_status'] != 'lobby':
            conn.close()
            raise HTTPException(400, f"Game is already {game_row['game_status']}")
        
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        if len(players) < 2:
            conn.close()
            raise HTTPException(400, "Need at least 2 players to start")
        
        deck = create_deck()
        player_hands = {}
        for player in players:
            hand = []
            for _ in range(5):
                if deck:
                    card = deck.pop()
                    card["isFaceUp"] = True
                    hand.append(card)
            
            cursor.execute(
                "UPDATE game_players SET hand = ? WHERE id = ?",
                (json.dumps(hand), player['id'])
            )
            player_hands[player['id']] = hand
        
        discard_pile = []
        if deck:
            first_card = deck.pop()
            first_card["isFaceUp"] = True
            discard_pile.append(first_card)
        
        under_card = deck.pop() if deck else None
        if under_card:
            under_card["isFaceUp"] = True
        
        last_move = {
            "playerId": players[0]['id'] if players else None,
            "playerName": players[0]['name'] if players else "System",
            "moveType": "start_game",
            "timestamp": datetime.now().isoformat()
        }
        
        cursor.execute('''
            UPDATE games SET
                deck = ?, discard_pile = ?, under_card = ?,
                game_status = 'playing', turn_phase = 'draw',
                turn_count = 1, current_player_index = 0,
                last_move = ?, last_updated = ?
            WHERE id = ?
        ''', (
            json.dumps(deck),
            json.dumps(discard_pile),
            json.dumps(under_card) if under_card else None,
            json.dumps(last_move),
            datetime.now().isoformat(),
            game_id
        ))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "gameId": game_id,
            "roomCode": game_row['room_code'],
            "status": "playing",
            "message": "Game started successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Start game error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to start game: {str(e)}")

# ============ FIXED GAME STATE ENDPOINTS ============
@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str):
    """Get game state - FIXED VERSION"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        game = dict(game_row)
        
        # Parse JSON fields with safe defaults
        game["deck"] = safe_json_parse(game.get("deck"), [])
        game["discard_pile"] = safe_json_parse(game.get("discard_pile"), [])
        game["under_card"] = safe_json_parse(game.get("under_card"), None)
        game["table_spreads"] = safe_json_parse(game.get("table_spreads"), [])
        game["last_move"] = safe_json_parse(game.get("last_move"), {})
        game["settings"] = safe_json_parse(game.get("settings"), {"allow_under_card_any_turn": True})
        
        # Always ensure deck is a list
        if not isinstance(game["deck"], list):
            game["deck"] = []
        
        # Build players list
        game_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["is_computer"] = bool(player_dict.get("is_computer", 0))
            player_dict["hand"] = safe_json_parse(player_dict.get("hand"), [])
            player_dict["spreads"] = safe_json_parse(player_dict.get("spreads"), [])
            player_dict["is_online"] = bool(player_dict.get("is_online", 1))
            player_dict["is_ready"] = bool(player_dict.get("is_ready", 1))
            player_dict["has_dropped"] = bool(player_dict.get("has_dropped", 0))
            
            # Calculate hand total
            hand_total = sum(card.get("value", 0) for card in player_dict["hand"])
            player_dict["hand_total"] = hand_total
            
            game_players.append(player_dict)
        
        game["players"] = game_players
        
        # Add current player name
        if game.get("current_player_index") is not None and game["players"]:
            idx = game["current_player_index"] % len(game["players"])
            if idx < len(game["players"]):
                game["current_player_name"] = game["players"][idx].get("name", "Unknown")
            else:
                game["current_player_name"] = "Unknown"
        else:
            game["current_player_name"] = "Unknown"
        
        conn.close()
        
        return {
            "success": True,
            "gameState": game,
            "lastMove": game.get("last_move", {}),
            "message": "Game state retrieved successfully"
        }
        
    except Exception as e:
        print(f"Get game state error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to get game state: {str(e)}")

@app.get("/api/game/{game_id}/lobby")
async def get_lobby_state(game_id: str):
    """Get lobby state - SIMPLIFIED"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, room_code, game_name, game_status, max_players FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        cursor.execute("SELECT id, name, is_computer, position FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        game_dict = dict(game_row)
        
        lobby_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["is_computer"] = bool(player_dict.get("is_computer", 0))
            player_dict["hand"] = []
            player_dict["spreads"] = []
            lobby_players.append(player_dict)
        
        conn.close()
        
        return {
            "success": True,
            "gameState": {
                "id": game_dict["id"],
                "room_code": game_dict["room_code"],
                "game_name": game_dict["game_name"],
                "game_status": game_dict["game_status"],
                "players": lobby_players
            },
            "players": lobby_players,
            "canStart": len(lobby_players) >= 2,
            "playerCount": len(lobby_players),
            "roomCode": game_dict["room_code"]
        }
        
    except Exception as e:
        print(f"Get lobby state error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to get lobby state: {str(e)}")

# ============ FIXED MOVE PROCESSING ============
@app.post("/api/game/{game_id}/move")
async def make_move(game_id: str, request: MoveRequest):
    """Process a game move - FIXED VERSION"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get game
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        if game_row['game_status'] != 'playing':
            conn.close()
            raise HTTPException(400, "Game is not in progress")
        
        # Get player
        cursor.execute("SELECT * FROM game_players WHERE id = ?", (request.playerId,))
        player_row = cursor.fetchone()
        
        if not player_row:
            conn.close()
            raise HTTPException(404, "Player not found in this game")
        
        game = dict(game_row)
        player = dict(player_row)
        
        # Parse game state
        game["deck"] = safe_json_parse(game.get("deck"), [])
        game["discard_pile"] = safe_json_parse(game.get("discard_pile"), [])
        game["under_card"] = safe_json_parse(game.get("under_card"), None)
        
        # Parse player state
        player["hand"] = safe_json_parse(player.get("hand"), [])
        player["spreads"] = safe_json_parse(player.get("spreads"), [])
        
        # Get all players for turn order
        cursor.execute("SELECT COUNT(*) FROM game_players WHERE game_id = ?", (game_id,))
        player_count = cursor.fetchone()[0]
        
        # Process the move
        move_result = {}
        last_move_data = {}
        
        if request.moveType == "draw_from_deck":
            if not game["deck"]:
                conn.close()
                raise HTTPException(400, "No cards left in deck")
            
            card = game["deck"].pop()
            card["isFaceUp"] = True
            player["hand"].append(card)
            
            move_result = {
                "next_phase": "discard",
                "next_player_index": game.get("current_player_index", 0)
            }
            
            last_move_data = {
                "playerId": player["id"],
                "playerName": player.get("name", "Unknown"),
                "moveType": "draw_from_deck",
                "timestamp": datetime.now().isoformat()
            }
            
        elif request.moveType == "draw_from_discard":
            if not game["discard_pile"]:
                conn.close()
                raise HTTPException(400, "Discard pile is empty")
            
            card = game["discard_pile"].pop()
            card["isFaceUp"] = True
            player["hand"].append(card)
            
            move_result = {
                "next_phase": "discard",
                "next_player_index": game.get("current_player_index", 0)
            }
            
            last_move_data = {
                "playerId": player["id"],
                "playerName": player.get("name", "Unknown"),
                "moveType": "draw_from_discard",
                "timestamp": datetime.now().isoformat()
            }
            
        elif request.moveType == "discard":
            card_id = request.moveData.get("cardId")
            if not card_id:
                conn.close()
                raise HTTPException(400, "No card specified to discard")
            
            # Find and remove card from hand
            card_to_discard = None
            for i, card in enumerate(player["hand"]):
                if card.get("id") == card_id:
                    card_to_discard = player["hand"].pop(i)
                    break
            
            if not card_to_discard:
                conn.close()
                raise HTTPException(400, "Card not found in hand")
            
            card_to_discard["isFaceUp"] = True
            game["discard_pile"].append(card_to_discard)
            
            # Move to next player
            next_player_index = (game.get("current_player_index", 0) + 1) % max(player_count, 1)
            
            move_result = {
                "next_player_index": next_player_index,
                "next_phase": "draw"
            }
            
            last_move_data = {
                "playerId": player["id"],
                "playerName": player.get("name", "Unknown"),
                "moveType": "discard",
                "card": card_to_discard,
                "timestamp": datetime.now().isoformat()
            }
        
        else:
            conn.close()
            raise HTTPException(400, f"Unknown move type: {request.moveType}")
        
        # Update game in database
        cursor.execute('''
            UPDATE games SET
                deck = ?, discard_pile = ?, under_card = ?,
                current_player_index = ?, turn_phase = ?,
                turn_count = turn_count + 1, last_move = ?,
                last_updated = ?
            WHERE id = ?
        ''', (
            json.dumps(game["deck"]),
            json.dumps(game["discard_pile"]),
            json.dumps(game["under_card"]),
            move_result.get("next_player_index", game.get("current_player_index", 0)),
            move_result.get("next_phase", game.get("turn_phase", "draw")),
            json.dumps(last_move_data),
            datetime.now().isoformat(),
            game_id
        ))
        
        # Update player in database
        cursor.execute('''
            UPDATE game_players SET
                hand = ?, last_move = ?, turns = turns + 1
            WHERE id = ?
        ''', (
            json.dumps(player["hand"]),
            json.dumps(request.moveData),
            request.playerId
        ))
        
        conn.commit()
        conn.close()
        
        # Return success response
        return {
            "success": True,
            "message": f"Move '{request.moveType}' processed successfully",
            "nextPlayerIndex": move_result.get("next_player_index"),
            "nextPhase": move_result.get("next_phase"),
            "lastMove": last_move_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Make move error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to process move: {str(e)}")

# ============ FIXED AI MOVE ENDPOINT ============
@app.post("/api/game/{game_id}/ai-move")
async def ai_move(game_id: str):
    """Process an AI player move - FIXED VERSION"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get game state
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            return {
                "success": False,
                "message": "Game not found",
                "error": "Game not found"
            }
        
        game = dict(game_row)
        
        # Check game status
        if game.get('game_status') != 'playing':
            conn.close()
            return {
                "success": False,
                "message": "Game is not in progress",
                "error": f"Game status: {game.get('game_status')}"
            }
        
        # Parse game state
        game["deck"] = safe_json_parse(game.get("deck"), [])
        game["discard_pile"] = safe_json_parse(game.get("discard_pile"), [])
        
        # Get current player
        current_player_index = game.get("current_player_index", 0)
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        if current_player_index >= len(players):
            conn.close()
            return {
                "success": False,
                "message": "Invalid player index",
                "error": f"Player index {current_player_index} out of range"
            }
        
        current_player = dict(players[current_player_index])
        
        # Check if current player is AI
        if not current_player.get("is_computer"):
            conn.close()
            return {
                "success": False,
                "message": "Current player is not an AI",
                "error": "Player is human"
            }
        
        # Parse player hand
        current_player["hand"] = safe_json_parse(current_player.get("hand"), [])
        
        # Simple AI logic
        ai_move_type = None
        ai_move_data = {}
        turn_phase = game.get("turn_phase", "draw")
        
        if turn_phase == "draw":
            # AI decides to draw from deck or discard
            if game["discard_pile"] and random.random() > 0.4:  # 40% chance to draw from discard
                ai_move_type = "draw_from_discard"
            else:
                ai_move_type = "draw_from_deck"
        
        elif turn_phase == "discard":
            # AI chooses a card to discard
            if current_player["hand"]:
                # Simple strategy: discard highest value card
                highest_card = None
                highest_value = -1
                
                for card in current_player["hand"]:
                    card_value = card.get("value", 0)
                    if card_value > highest_value:
                        highest_value = card_value
                        highest_card = card
                
                if highest_card:
                    ai_move_type = "discard"
                    ai_move_data = {"cardId": highest_card.get("id")}
        
        # If no move was determined
        if not ai_move_type:
            conn.close()
            return {
                "success": False,
                "message": "AI couldn't decide on a move",
                "error": "No move type determined"
            }
        
        # Prepare move request
        move_request = MoveRequest(
            playerId=current_player["id"],
            moveType=ai_move_type,
            moveData=ai_move_data
        )
        
        conn.close()
        
        # Process the move
        try:
            move_result = await make_move(game_id, move_request)
            return move_result
        except Exception as move_error:
            print(f"AI move processing error: {move_error}")
            return {
                "success": False,
                "message": "AI move failed",
                "error": str(move_error)
            }
        
    except Exception as e:
        print(f"AI move error: {traceback.format_exc()}")
        return {
            "success": False,
            "message": "Failed to process AI move",
            "error": str(e)
        }

# ============ SIMPLE ENDPOINTS ============
@app.get("/api/game/available")
async def get_available_games():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT g.id, g.room_code, g.game_name, COUNT(p.id) as player_count
            FROM games g
            LEFT JOIN game_players p ON g.id = p.game_id
            WHERE g.game_status = 'lobby'
            GROUP BY g.id
            HAVING player_count < 4
        ''')
        
        games = []
        for row in cursor.fetchall():
            games.append({
                "gameId": row['id'],
                "roomCode": row['room_code'],
                "gameName": row['game_name'],
                "currentPlayers": row['player_count'],
                "maxPlayers": 4
            })
        
        conn.close()
        return {"available_games": games}
        
    except Exception as e:
        print(f"Get available games error: {traceback.format_exc()}")
        return {"available_games": []}

@app.get("/api/game/user/{user_id}/active")
async def get_user_active_game(user_id: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT g.id, g.room_code, g.game_status 
            FROM games g
            JOIN game_players p ON g.id = p.game_id
            WHERE p.user_id = ? AND g.game_status IN ('lobby', 'playing')
            ORDER BY g.created_at DESC
            LIMIT 1
        ''', (user_id,))
        
        game_row = cursor.fetchone()
        conn.close()
        
        if game_row:
            return {
                "hasActiveGame": True,
                "gameId": game_row["id"],
                "roomCode": game_row["room_code"],
                "gameStatus": game_row["game_status"]
            }
        
        return {"hasActiveGame": False}
        
    except Exception as e:
        print(f"Get active game error: {traceback.format_exc()}")
        return {"hasActiveGame": False}

@app.get("/api/game/room/{room_code}/id")
async def get_game_id_by_room_code(room_code: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, game_status FROM games WHERE room_code = ?", (room_code.upper(),))
        game_row = cursor.fetchone()
        conn.close()
        
        if game_row:
            return {
                "success": True,
                "gameId": game_row["id"],
                "gameStatus": game_row["game_status"]
            }
        else:
            raise HTTPException(404, f"Game not found with room code: {room_code}")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Get game ID error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to get game ID: {str(e)}")

@app.get("/api/game/room/{room_code}/state")
async def get_game_state_by_room_code(room_code: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM games WHERE room_code = ?", (room_code.upper(),))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, f"Game not found with room code: {room_code}")
        
        game_id = game_row["id"]
        conn.close()
        
        return await get_game_state(game_id)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Get game state by room code error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to get game state: {str(e)}")

# ============ DEBUG ENDPOINT ============
@app.get("/api/debug/db")
async def debug_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        counts = {}
        for table in tables:
            table_name = table[0]
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                counts[table_name] = count
            except:
                counts[table_name] = "error"
        
        conn.close()
        return {
            "tables": [t[0] for t in tables],
            "counts": counts,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}

# ============ ROOT ENDPOINT ============
@app.get("/")
async def root():
    return {
        "message": "Tonk Game API - Fixed Version",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "health": {
                "ping": "GET /api/ping",
                "status": "GET /api/status",
                "warmup": "GET /api/warmup"
            },
            "game": {
                "create": "POST /api/game/create",
                "join": "POST /api/game/{code}/join",
                "start": "POST /api/game/{id}/start",
                "state": "GET /api/game/{id}/state",
                "lobby": "GET /api/game/{id}/lobby",
                "move": "POST /api/game/{id}/move",
                "ai_move": "POST /api/game/{id}/ai-move",
                "available": "GET /api/game/available",
                "user_active": "GET /api/game/user/{id}/active",
                "room_id": "GET /api/game/room/{code}/id",
                "room_state": "GET /api/game/room/{code}/state"
            }
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)