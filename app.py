# COMPLETE FIXED VERSION FOR RENDER.COM
from fastapi import FastAPI, HTTPException, Header
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

# ============ DATABASE SETUP ============
def init_db():
    """Initialize database - DO NOT DROP TABLES on every startup"""
    print("🔄 Initializing database for Render.com...")
    
    try:
        conn = sqlite3.connect("tonk_game.db")
        cursor = conn.cursor()
        
        # Users table - CREATE IF NOT EXISTS
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
        
        # Games table - CREATE IF NOT EXISTS
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
            settings TEXT DEFAULT '{"allow_under_card_any_turn": true}',
            winner TEXT,
            win_reason TEXT,
            creator_id TEXT,
            max_players INTEGER DEFAULT 4
        )
        ''')
        
        # Players table - CREATE IF NOT EXISTS
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
            position INTEGER
        )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Database initialized successfully on Render.com")
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        # Try to create just the file
        open("tonk_game.db", "a").close()
        print("📁 Created empty database file")

# Initialize on startup
@app.on_event("startup")
def startup():
    print("🚀 Tonk API starting on Render.com...")
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
        # Try to reinitialize
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
            suit_symbol = {"hearts": "H", "diamonds": "D", "clubs": "C", "spades": "S"}.get(suit, "")
            
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

def get_current_player_id(game):
    """Get the ID of the current player"""
    players = json.loads(game["players"]) if isinstance(game["players"], str) else game["players"]
    if players and game["current_player_index"] < len(players):
        return players[game["current_player_index"]]["id"]
    return None

def get_player_by_id(game, player_id):
    """Get player by ID"""
    players = json.loads(game["players"]) if isinstance(game["players"], str) else game["players"]
    for player in players:
        if player["id"] == player_id:
            return player
    return None

# ============ HEALTH ENDPOINTS ============
@app.get("/api/ping")
async def ping():
    """Simple health check"""
    return {
        "status": "pong",
        "timestamp": datetime.now().isoformat(),
        "server": "TonkAPI",
        "environment": "Render.com"
    }

@app.get("/api/warmup")
async def warmup():
    """Warm up server and check database"""
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
    """Server status"""
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
    """Register a new user"""
    print(f"📝 Register user attempt: {user_data.username}")
    
    conn = None
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
        
        response_data = {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user_id,
            "username": user_data.username,
            "message": "Registration successful"
        }
        
        print(f"✅ User registered: {user_data.username}")
        return response_data
        
    except HTTPException as he:
        print(f"❌ HTTP Exception in register: {he.detail}")
        raise he
    except Exception as e:
        print(f"❌ Unexpected error in register: {str(e)}")
        raise HTTPException(500, f"Registration failed: {str(e)}")
    finally:
        if conn:
            conn.close()

@app.post("/api/auth/login")
async def login_user(user_data: UserLogin):
    """Login user"""
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
        print(f"Login error: {traceback.format_exc()}")
        raise HTTPException(500, f"Login failed: {str(e)}")

@app.get("/api/auth/validate-token")
async def validate_token(authorization: str = Header(None)):
    """Validate JWT token"""
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
    """Create a new game"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        game_id = str(uuid.uuid4())
        room_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        
        deck = create_deck()
        
        cursor.execute('''
            INSERT INTO games (id, room_code, game_name, deck, creator_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (game_id, room_code, request.game_name, json.dumps(deck), request.userId, datetime.now().isoformat()))
        
        first_player_id = None
        for i, player_data in enumerate(request.players):
            player_id = str(uuid.uuid4())
            player_user_id = request.userId if i == 0 else None
            
            is_computer = player_data.get("isComputer", False) or player_data.get("is_computer", False)
            
            cursor.execute('''
                INSERT INTO game_players (id, game_id, user_id, name, is_computer, position)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                player_id, game_id, player_user_id, 
                player_data["name"], 
                1 if is_computer else 0,
                i
            ))
            
            if i == 0:
                first_player_id = player_id
        
        conn.commit()
        
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game = dict(cursor.fetchone())
        
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        game_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["is_computer"] = bool(player_dict["is_computer"])
            player_dict["hand"] = []
            player_dict["spreads"] = []
            game_players.append(player_dict)
        
        conn.close()
        
        return {
            "success": True,
            "gameId": game_id,
            "roomCode": room_code,
            "playerId": first_player_id,
            "players": game_players,
            "gameName": request.game_name or "Tonk Game",
            "message": "Game created successfully"
        }
        
    except Exception as e:
        print(f"Create game error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to create game: {str(e)}")

@app.post("/api/game/{room_code}/join")
async def join_game(room_code: str, request: JoinGameRequest):
    """Join an existing game"""
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
            INSERT INTO game_players (id, game_id, user_id, name, is_computer, position)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (player_id, game_id, request.userId, request.playerName, 0, position))
        
        conn.commit()
        
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game = dict(cursor.fetchone())
        
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        if game["deck"]:
            game["deck"] = json.loads(game["deck"])
        else:
            game["deck"] = []
            
        if game["discard_pile"]:
            game["discard_pile"] = json.loads(game["discard_pile"])
        else:
            game["discard_pile"] = []
            
        if game["under_card"]:
            game["under_card"] = json.loads(game["under_card"])
        else:
            game["under_card"] = None
        
        game_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["hand"] = json.loads(player_dict["hand"]) if player_dict["hand"] else []
            player_dict["spreads"] = json.loads(player_dict["spreads"]) if player_dict["spreads"] else []
            player_dict["is_computer"] = bool(player_dict["is_computer"])
            game_players.append(player_dict)
        
        game["players"] = game_players
        
        conn.close()
        
        return {
            "success": True,
            "gameId": game_id,
            "playerId": player_id,
            "gameState": game,
            "message": f"Joined game as {request.playerName}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Join game error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to join game: {str(e)}")

@app.post("/api/game/{game_id}/start")
async def start_game(game_id: str):
    """Start a game with AI support"""
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
                last_move = ?
            WHERE id = ?
        ''', (
            json.dumps(deck),
            json.dumps(discard_pile),
            json.dumps(under_card),
            json.dumps(last_move),
            game_id
        ))
        
        conn.commit()
        
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        updated_game = dict(cursor.fetchone())
        
        updated_game["deck"] = deck
        updated_game["discard_pile"] = discard_pile
        updated_game["under_card"] = under_card
        updated_game["last_move"] = last_move
        
        updated_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["hand"] = player_hands.get(player['id'], [])
            player_dict["spreads"] = json.loads(player_dict["spreads"]) if player_dict["spreads"] else []
            player_dict["is_computer"] = bool(player_dict["is_computer"])
            updated_players.append(player_dict)
        
        updated_game["players"] = updated_players
        
        conn.close()
        
        # Check if first player is AI and trigger AI move if needed
        first_player = updated_players[0] if updated_players else None
        if first_player and first_player.get("is_computer"):
            print(f"🤖 First player is AI ({first_player['name']}), should trigger AI move")
            # Note: Frontend should handle this via polling
        
        return {
            "success": True,
            "gameId": game_id,
            "roomCode": game_row['room_code'],
            "status": "playing",
            "gameState": updated_game,
            "message": "Game started successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Start game error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to start game: {str(e)}")

# ============ COMPLETE MOVE PROCESSING ============
@app.post("/api/game/{game_id}/move")
async def make_move(game_id: str, request: MoveRequest):
    """Process a game move with full game logic"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        if game_row['game_status'] != 'playing':
            conn.close()
            raise HTTPException(400, "Game is not in progress")
        
        cursor.execute("SELECT * FROM game_players WHERE id = ?", (request.playerId,))
        player_row = cursor.fetchone()
        
        if not player_row:
            conn.close()
            raise HTTPException(404, "Player not found in this game")
        
        game = dict(game_row)
        player = dict(player_row)
        
        # Parse JSON fields
        game["deck"] = json.loads(game["deck"]) if game["deck"] else []
        game["discard_pile"] = json.loads(game["discard_pile"]) if game["discard_pile"] else []
        game["under_card"] = json.loads(game["under_card"]) if game["under_card"] else None
        game["table_spreads"] = json.loads(game["table_spreads"]) if game["table_spreads"] else []
        
        player["hand"] = json.loads(player["hand"]) if player["hand"] else []
        player["spreads"] = json.loads(player["spreads"]) if player["spreads"] else []
        
        # Get players to check turn order
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        all_players = cursor.fetchall()
        players_list = []
        for p in all_players:
            p_dict = dict(p)
            p_dict["hand"] = json.loads(p_dict["hand"]) if p_dict["hand"] else []
            p_dict["spreads"] = json.loads(p_dict["spreads"]) if p_dict["spreads"] else []
            p_dict["is_computer"] = bool(p_dict["is_computer"])
            players_list.append(p_dict)
        
        current_player_index = game["current_player_index"]
        
        # Verify it's the player's turn
        if current_player_index >= len(players_list) or players_list[current_player_index]["id"] != request.playerId:
            conn.close()
            raise HTTPException(400, "Not your turn")
        
        # Process move based on type
        move_result = process_game_move(game, player, request.moveType, request.moveData)
        
        # Update game state
        cursor.execute('''
            UPDATE games SET
                deck = ?, discard_pile = ?, under_card = ?,
                current_player_index = ?, turn_phase = ?,
                turn_count = ?, last_move = ?, table_spreads = ?,
                game_status = ?
            WHERE id = ?
        ''', (
            json.dumps(game["deck"]),
            json.dumps(game["discard_pile"]),
            json.dumps(game["under_card"]),
            move_result.get("next_player_index", current_player_index),
            move_result.get("next_phase", game["turn_phase"]),
            game["turn_count"] + 1,
            json.dumps(move_result.get("last_move", {})),
            json.dumps(game["table_spreads"]),
            move_result.get("game_status", game["game_status"]),
            game_id
        ))
        
        # Update player
        cursor.execute('''
            UPDATE game_players SET
                hand = ?, spreads = ?, has_dropped = ?,
                score = ?, last_move = ?, turns = ?,
                has_drawn_from_under = ?
            WHERE id = ?
        ''', (
            json.dumps(player["hand"]),
            json.dumps(player["spreads"]),
            player.get("has_dropped", 0),
            player.get("score", 0),
            json.dumps(request.moveData),
            player.get("turns", 0) + 1,
            player.get("has_drawn_from_under", 0),
            request.playerId
        ))
        
        conn.commit()
        
        # Get updated game state
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        updated_game = dict(cursor.fetchone())
        
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        updated_players = cursor.fetchall()
        
        # Parse for response
        updated_game["deck"] = json.loads(updated_game["deck"]) if updated_game["deck"] else []
        updated_game["discard_pile"] = json.loads(updated_game["discard_pile"]) if updated_game["discard_pile"] else []
        updated_game["under_card"] = json.loads(updated_game["under_card"]) if updated_game["under_card"] else None
        updated_game["table_spreads"] = json.loads(updated_game["table_spreads"]) if updated_game["table_spreads"] else []
        updated_game["last_move"] = json.loads(updated_game["last_move"]) if updated_game["last_move"] else None
        
        game_players_response = []
        for p in updated_players:
            p_dict = dict(p)
            p_dict["hand"] = json.loads(p_dict["hand"]) if p_dict["hand"] else []
            p_dict["spreads"] = json.loads(p_dict["spreads"]) if p_dict["spreads"] else []
            p_dict["is_computer"] = bool(p_dict["is_computer"])
            game_players_response.append(p_dict)
        
        updated_game["players"] = game_players_response
        
        conn.close()
        
        return {
            "success": True,
            "gameState": updated_game,
            "lastMove": updated_game.get("last_move"),
            "message": f"Move '{request.moveType}' processed successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Make move error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to process move: {str(e)}")

def process_game_move(game, player, move_type, move_data):
    """Process game move logic"""
    
    if move_type == "draw_from_deck":
        if not game["deck"]:
            raise HTTPException(400, "No cards left in deck")
        
        card = game["deck"].pop()
        card["isFaceUp"] = True
        player["hand"].append(card)
        
        return {
            "next_phase": "discard",
            "last_move": {
                "playerId": player["id"],
                "playerName": player["name"],
                "moveType": "draw_from_deck",
                "card": card,
                "timestamp": datetime.now().isoformat()
            }
        }
    
    elif move_type == "draw_from_discard":
        if not game["discard_pile"]:
            raise HTTPException(400, "Discard pile is empty")
        
        card = game["discard_pile"].pop()
        card["isFaceUp"] = True
        player["hand"].append(card)
        
        return {
            "next_phase": "discard",
            "last_move": {
                "playerId": player["id"],
                "playerName": player["name"],
                "moveType": "draw_from_discard",
                "card": card,
                "timestamp": datetime.now().isoformat()
            }
        }
    
    elif move_type == "discard":
        card_id = move_data.get("cardId")
        if not card_id:
            raise HTTPException(400, "No card specified to discard")
        
        # Find and remove card from hand
        card_to_discard = None
        for i, card in enumerate(player["hand"]):
            if card["id"] == card_id:
                card_to_discard = player["hand"].pop(i)
                break
        
        if not card_to_discard:
            raise HTTPException(400, "Card not found in hand")
        
        card_to_discard["isFaceUp"] = True
        game["discard_pile"].append(card_to_discard)
        
        # Move to next player
        cursor = get_db().cursor()
        cursor.execute("SELECT COUNT(*) FROM game_players WHERE game_id = ?", (game["id"],))
        player_count = cursor.fetchone()[0]
        
        next_player_index = (game["current_player_index"] + 1) % player_count
        
        return {
            "next_player_index": next_player_index,
            "next_phase": "draw",
            "last_move": {
                "playerId": player["id"],
                "playerName": player["name"],
                "moveType": "discard",
                "card": card_to_discard,
                "timestamp": datetime.now().isoformat()
            }
        }
    
    elif move_type == "create_spread":
        # Simplified spread creation
        card_ids = move_data.get("cardIds", [])
        spread_type = move_data.get("type", "set")
        
        if len(card_ids) < 3:
            raise HTTPException(400, "Need at least 3 cards for a spread")
        
        spread_cards = []
        for card_id in card_ids:
            for i, card in enumerate(player["hand"]):
                if card["id"] == card_id:
                    spread_cards.append(player["hand"].pop(i))
                    break
        
        if len(spread_cards) != len(card_ids):
            raise HTTPException(400, "Some cards not found in hand")
        
        spread = {
            "id": str(uuid.uuid4()),
            "playerId": player["id"],
            "playerName": player["name"],
            "type": spread_type,
            "cards": spread_cards,
            "createdAt": datetime.now().isoformat()
        }
        
        if "spreads" not in player:
            player["spreads"] = []
        player["spreads"].append(spread)
        
        if not game["table_spreads"]:
            game["table_spreads"] = []
        game["table_spreads"].append(spread)
        
        return {
            "last_move": {
                "playerId": player["id"],
                "playerName": player["name"],
                "moveType": "create_spread",
                "spread": spread,
                "timestamp": datetime.now().isoformat()
            }
        }
    
    else:
        raise HTTPException(400, f"Unknown move type: {move_type}")

# ============ AI MOVE ENDPOINT (CRITICAL MISSING ENDPOINT) ============
@app.post("/api/game/{game_id}/ai-move")
async def ai_move(game_id: str):
    """Process an AI player move"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        if game_row['game_status'] != 'playing':
            conn.close()
            raise HTTPException(400, "Game is not in progress")
        
        game = dict(game_row)
        game["deck"] = json.loads(game["deck"]) if game["deck"] else []
        game["discard_pile"] = json.loads(game["discard_pile"]) if game["discard_pile"] else []
        game["under_card"] = json.loads(game["under_card"]) if game["under_card"] else None
        
        current_player_index = game["current_player_index"]
        
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        if current_player_index >= len(players):
            conn.close()
            raise HTTPException(400, "Invalid player index")
        
        current_player = dict(players[current_player_index])
        
        if not current_player["is_computer"]:
            conn.close()
            raise HTTPException(400, "Current player is not an AI")
        
        current_player["hand"] = json.loads(current_player["hand"]) if current_player["hand"] else []
        current_player["spreads"] = json.loads(current_player["spreads"]) if current_player["spreads"] else []
        
        # Simple AI logic
        ai_move_type = None
        ai_move_data = {}
        
        if game["turn_phase"] == "draw":
            # AI decides to draw from deck or discard
            if game["discard_pile"] and random.random() > 0.5:
                ai_move_type = "draw_from_discard"
            else:
                ai_move_type = "draw_from_deck"
        elif game["turn_phase"] == "discard":
            # AI chooses a card to discard
            if current_player["hand"]:
                # Discard highest value card
                highest_card = max(current_player["hand"], key=lambda x: x["value"])
                ai_move_type = "discard"
                ai_move_data = {"cardId": highest_card["id"]}
        
        if not ai_move_type:
            conn.close()
            return {"success": False, "message": "AI couldn't decide on a move"}
        
        # Process the AI move
        move_request = MoveRequest(
            playerId=current_player["id"],
            moveType=ai_move_type,
            moveData=ai_move_data
        )
        
        conn.close()
        
        # Use the regular move endpoint to process the move
        return await make_move(game_id, move_request)
        
    except Exception as e:
        print(f"AI move error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to process AI move: {str(e)}")

# ============ GAME STATE ENDPOINTS ============
@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str):
    """Get game state"""
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
        game["deck"] = json.loads(game["deck"]) if game["deck"] else []
        game["discard_pile"] = json.loads(game["discard_pile"]) if game["discard_pile"] else []
        game["under_card"] = json.loads(game["under_card"]) if game["under_card"] else None
        game["table_spreads"] = json.loads(game["table_spreads"]) if game["table_spreads"] else []
        game["last_move"] = json.loads(game["last_move"]) if game["last_move"] else None
        game["settings"] = json.loads(game["settings"]) if game["settings"] else {"allow_under_card_any_turn": True}
        
        game_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["is_computer"] = bool(player_dict["is_computer"])
            player_dict["hand"] = json.loads(player_dict["hand"]) if player_dict["hand"] else []
            player_dict["spreads"] = json.loads(player_dict["spreads"]) if player_dict["spreads"] else []
            game_players.append(player_dict)
        
        game["players"] = game_players
        
        conn.close()
        
        return {
            "success": True,
            "gameState": game,
            "lastMove": game.get("last_move")
        }
        
    except Exception as e:
        print(f"Get game state error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to get game state: {str(e)}")

@app.get("/api/game/{game_id}/lobby")
async def get_lobby_state(game_id: str):
    """Get lobby state (players without cards)"""
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
        
        lobby_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["hand"] = []
            player_dict["spreads"] = []
            player_dict["is_computer"] = bool(player_dict["is_computer"])
            lobby_players.append(player_dict)
        
        conn.close()
        
        return {
            "success": True,
            "players": lobby_players,
            "status": game_row['game_status'],
            "roomCode": game_row['room_code'],
            "gameName": game_row['game_name'],
            "maxPlayers": game_row['max_players'],
            "canStart": len(players) >= 2,
            "playerCount": len(players)
        }
        
    except Exception as e:
        print(f"Get lobby state error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to get lobby state: {str(e)}")

@app.get("/api/game/available")
async def get_available_games():
    """Get available games"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT g.id, g.room_code, g.game_name, g.creator_id, g.created_at,
                   COUNT(p.id) as player_count, g.max_players
            FROM games g
            LEFT JOIN game_players p ON g.id = p.game_id
            WHERE g.game_status = 'lobby'
            GROUP BY g.id
            HAVING player_count < g.max_players
        ''')
        
        games = []
        for row in cursor.fetchall():
            games.append({
                "gameId": row['id'],
                "roomCode": row['room_code'],
                "gameName": row['game_name'],
                "currentPlayers": row['player_count'],
                "maxPlayers": row['max_players'],
                "creator": row['creator_id'],
                "createdAt": row['created_at']
            })
        
        conn.close()
        return {"available_games": games}
        
    except Exception as e:
        print(f"Get available games error: {traceback.format_exc()}")
        return {"available_games": []}

@app.get("/api/game/user/{user_id}/active")
async def get_user_active_game(user_id: str):
    """Get user's active game"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT g.id, g.room_code, g.game_status 
            FROM games g
            JOIN game_players p ON g.id = p.game_id
            WHERE p.user_id = ? AND g.game_status IN ('lobby', 'playing')
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

# ============ NEW ENDPOINTS NEEDED BY FRONTEND ============
@app.get("/api/game/room/{room_code}/id")
async def get_game_id_by_room_code(room_code: str):
    """Get game ID from room code"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM games WHERE room_code = ?", (room_code.upper(),))
        game_row = cursor.fetchone()
        
        conn.close()
        
        if game_row:
            return {
                "success": True,
                "gameId": game_row["id"]
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
    """Get game state by room code"""
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

# ============ DEBUG ENDPOINTS ============
@app.get("/api/debug/db")
async def debug_db():
    """Debug database state"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        counts = {}
        for table in tables:
            table_name = table[0]
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            counts[table_name] = count
        
        conn.close()
        
        return {
            "tables": [t[0] for t in tables],
            "counts": counts,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}

# ============ ROOT ENDPOINT ============
@app.get("/")
async def root():
    return {
        "message": "Tonk Game API - Fixed Version with AI Support",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "auth": {
                "register": "POST /api/auth/register",
                "login": "POST /api/auth/login",
                "validate_token": "GET /api/auth/validate-token"
            },
            "game": {
                "create": "POST /api/game/create",
                "join": "POST /api/game/{code}/join",
                "start": "POST /api/game/{id}/start",
                "state": "GET /api/game/{id}/state",
                "lobby": "GET /api/game/{id}/lobby",
                "available": "GET /api/game/available",
                "user_active": "GET /api/game/user/{id}/active",
                "room_id": "GET /api/game/room/{code}/id",
                "room_state": "GET /api/game/room/{code}/state",
                "move": "POST /api/game/{id}/move",
                "ai_move": "POST /api/game/{id}/ai-move"  # NEW
            },
            "system": {
                "ping": "GET /api/ping",
                "warmup": "GET /api/warmup",
                "status": "GET /api/status",
                "debug": "GET /api/debug/db"
            }
        },
        "notes": [
            "AI players can now make moves via /api/game/{id}/ai-move",
            "Database tables are preserved on restart",
            "Full move processing implemented"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)