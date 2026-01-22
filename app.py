# ADD at the top:
import os
import traceback
from datetime import datetime, timedelta
import uuid
import sqlite3
import random
import bcrypt
import jwt
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import json

app = FastAPI(title="Tonk Game API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use environment variable for secret key
SECRET_KEY = os.environ.get("SECRET_KEY", "tonk-game-secure-key-12345")
ALGORITHM = "HS256"
API_VERSION = "2.0-fixed"

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
    """Initialize database - handles ephemeral storage on Render.com"""
    print("🔄 Initializing database...")
    
    conn = sqlite3.connect("tonk_game.db")
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # Drop tables if they exist (for clean restart)
    cursor.execute("DROP TABLE IF EXISTS game_players")
    cursor.execute("DROP TABLE IF EXISTS games")
    cursor.execute("DROP TABLE IF EXISTS users")
    
    # Users table
    cursor.execute('''
    CREATE TABLE users (
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
    CREATE TABLE games (
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
    
    # Players table
    cursor.execute('''
    CREATE TABLE game_players (
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
        FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
    )
    ''')
    
    # Create indexes
    cursor.execute("CREATE INDEX idx_games_room_code ON games(room_code)")
    cursor.execute("CREATE INDEX idx_games_status ON games(game_status)")
    cursor.execute("CREATE INDEX idx_game_players_game_id ON game_players(game_id)")
    cursor.execute("CREATE INDEX idx_game_players_user_id ON game_players(user_id)")
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully")
    print(f"📊 Tables created: users, games, game_players")

# Initialize on startup
@app.on_event("startup")
def startup():
    print(f"🚀 Tonk Game API v{API_VERSION} starting up...")
    init_db()
    print("✅ Server ready")

def get_db():
    """Get database connection with proper error handling"""
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

# ============ AUTH ENDPOINTS ============
@app.post("/api/auth/register")
async def register_user(user_data: UserRegister):
    """Register a new user"""
    print(f"📝 Register user: {user_data.username}")
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Check username
        cursor.execute("SELECT id FROM users WHERE username = ?", (user_data.username,))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(400, "Username already exists")
        
        # Check email
        cursor.execute("SELECT id FROM users WHERE email = ?", (user_data.email,))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(400, "Email already exists")
        
        # Create user
        user_id = str(uuid.uuid4())
        hashed_password = hash_password(user_data.password)
        created_at = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO users (id, username, email, hashed_password, created_at, online, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, user_data.username, user_data.email, hashed_password, created_at, 1, created_at))
        
        conn.commit()
        
        # Create token
        token = create_token(user_data.username, user_id)
        
        conn.close()
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user_id,
            "username": user_data.username,
            "message": "Registration successful"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Registration error: {traceback.format_exc()}")
        raise HTTPException(500, f"Registration failed: {str(e)}")

@app.post("/api/auth/login")
async def login_user(user_data: UserLogin):
    """Login user"""
    print(f"🔑 Login attempt: {user_data.username}")
    
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
        
        # Update last seen
        cursor.execute(
            "UPDATE users SET last_seen = ?, online = 1 WHERE id = ?",
            (datetime.now().isoformat(), user['id'])
        )
        conn.commit()
        
        # Create token
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
        print(f"❌ Login error: {traceback.format_exc()}")
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

# ============ HEALTH ENDPOINTS ============
@app.get("/api/ping")
async def ping():
    return {
        "status": "pong", 
        "timestamp": datetime.now().isoformat(),
        "version": API_VERSION,
        "database": "sqlite"
    }

@app.get("/api/warmup")
async def warmup():
    """Warm up server and check database"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Check all tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        table_names = [t['name'] for t in tables]
        
        conn.close()
        
        return {
            "status": "ready",
            "database": "connected",
            "tables": table_names,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "error",
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# ============ GAME ENDPOINTS ============
@app.post("/api/game/create")
async def create_game(request: CreateGameRequest):
    """Create a new game"""
    print(f"🎮 Create game: {request.game_name}")
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Generate game ID and room code
        game_id = str(uuid.uuid4())
        room_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        
        # Check for duplicate room code (unlikely but possible)
        cursor.execute("SELECT id FROM games WHERE room_code = ?", (room_code,))
        if cursor.fetchone():
            # Regenerate if duplicate
            room_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        
        # Create deck
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
        
        # Save game to database
        cursor.execute('''
            INSERT INTO games (id, room_code, game_name, deck, creator_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (game_id, room_code, request.game_name, json.dumps(deck), request.userId, datetime.now().isoformat()))
        
        # Save players
        first_player_id = None
        for i, player_data in enumerate(request.players):
            player_id = str(uuid.uuid4())
            player_user_id = request.userId if i == 0 else None
            
            # Ensure is_computer is properly stored as 0/1
            is_computer = 1 if player_data.get("isComputer", False) or player_data.get("is_computer", False) else 0
            
            cursor.execute('''
                INSERT INTO game_players (id, game_id, user_id, name, is_computer, position)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                player_id, game_id, player_user_id, 
                player_data["name"], 
                is_computer,
                i
            ))
            
            if i == 0:
                first_player_id = player_id
        
        conn.commit()
        
        # Get created game data
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game = dict(cursor.fetchone())
        
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        # Process players for response
        game_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["is_computer"] = bool(player_dict["is_computer"])  # Convert to boolean
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
        print(f"❌ Create game error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to create game: {str(e)}")

@app.post("/api/game/{room_code}/join")
async def join_game(room_code: str, request: JoinGameRequest):
    """Join an existing game"""
    print(f"🎮 Join game: {room_code}, player: {request.playerName}")
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Find game by room code
        cursor.execute("SELECT id, game_status, max_players FROM games WHERE room_code = ?", (room_code.upper(),))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, f"Game not found with code: {room_code}")
        
        game_id = game_row['id']
        
        if game_row['game_status'] != 'lobby':
            conn.close()
            raise HTTPException(400, "Game has already started")
        
        # Count current players
        cursor.execute("SELECT COUNT(*) as count FROM game_players WHERE game_id = ?", (game_id,))
        player_count = cursor.fetchone()['count']
        
        if player_count >= game_row['max_players']:
            conn.close()
            raise HTTPException(400, "Game is full (max 4 players)")
        
        # Check if player name already exists in this game
        cursor.execute("SELECT id FROM game_players WHERE game_id = ? AND name = ?", (game_id, request.playerName))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(400, f"Player name '{request.playerName}' is already taken in this game")
        
        # Create player
        player_id = str(uuid.uuid4())
        position = player_count
        
        cursor.execute('''
            INSERT INTO game_players (id, game_id, user_id, name, is_computer, position)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (player_id, game_id, request.userId, request.playerName, False, position))
        
        conn.commit()
        
        # Get updated game info
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game = dict(cursor.fetchone())
        
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        # Process game data
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
        
        # Process players
        game_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["hand"] = json.loads(player_dict["hand"]) if player_dict["hand"] else []
            player_dict["spreads"] = json.loads(player_dict["spreads"]) if player_dict["spreads"] else []
            player_dict["is_computer"] = bool(player_dict["is_computer"])  # Convert to boolean
            game_players.append(player_dict)
        
        game["players"] = game_players
        game["room_code"] = room_code.upper()
        
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
        print(f"❌ Join game error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to join game: {str(e)}")

@app.post("/api/game/{game_id}/start")
async def start_game(game_id: str):
    """Start a game"""
    print(f"🚀 Start game: {game_id}")
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get the game
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        if game_row['game_status'] != 'lobby':
            conn.close()
            raise HTTPException(400, f"Game is already {game_row['game_status']}")
        
        # Get players
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        if len(players) < 2:
            conn.close()
            raise HTTPException(400, "Need at least 2 players to start")
        
        # Create a fresh deck
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
        
        # Deal 5 cards to each player
        player_hands = {}
        for player in players:
            hand = []
            for _ in range(5):
                if deck:
                    card = deck.pop()
                    card["isFaceUp"] = True
                    hand.append(card)
            
            # Save hand to database
            cursor.execute(
                "UPDATE game_players SET hand = ? WHERE id = ?",
                (json.dumps(hand), player['id'])
            )
            player_hands[player['id']] = hand
        
        # Setup discard pile
        discard_pile = []
        if deck:
            first_card = deck.pop()
            first_card["isFaceUp"] = True
            discard_pile.append(first_card)
        
        # Setup under card
        under_card = deck.pop() if deck else None
        if under_card:
            under_card["isFaceUp"] = True
        
        # Update game status
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
        
        # Get updated game state to return
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        updated_game = dict(cursor.fetchone())
        
        # Parse JSON fields
        updated_game["deck"] = deck
        updated_game["discard_pile"] = discard_pile
        updated_game["under_card"] = under_card
        updated_game["last_move"] = last_move
        
        # Add players with their hands
        updated_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["hand"] = player_hands.get(player['id'], [])
            player_dict["spreads"] = json.loads(player_dict["spreads"]) if player_dict["spreads"] else []
            player_dict["is_computer"] = bool(player_dict["is_computer"])
            updated_players.append(player_dict)
        
        updated_game["players"] = updated_players
        
        conn.close()
        
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
        print(f"❌ Start game error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to start game: {str(e)}")

@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str):
    """Get game state"""
    print(f"📊 Get game state: {game_id}")
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get game
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        # Get players
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        # Parse game
        game = dict(game_row)
        game["deck"] = json.loads(game["deck"]) if game["deck"] else []
        game["discard_pile"] = json.loads(game["discard_pile"]) if game["discard_pile"] else []
        game["under_card"] = json.loads(game["under_card"]) if game["under_card"] else None
        game["table_spreads"] = json.loads(game["table_spreads"]) if game["table_spreads"] else []
        game["last_move"] = json.loads(game["last_move"]) if game["last_move"] else None
        game["settings"] = json.loads(game["settings"]) if game["settings"] else {"allow_under_card_any_turn": True}
        
        # Parse players - IMPORTANT: only show current player's hand
        game_players = []
        for player in players:
            player_dict = dict(player)
            # Convert is_computer to boolean
            player_dict["is_computer"] = bool(player_dict["is_computer"])
            
            # Only include hand if requested by the player themselves
            # (In real implementation, you'd check which player is requesting)
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
        print(f"❌ Get game state error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to get game state: {str(e)}")

@app.get("/api/game/{game_id}/lobby")
async def get_lobby_state(game_id: str):
    """Get lobby state (players without cards)"""
    print(f"🎪 Get lobby state: {game_id}")
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get game
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        # Get players
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        # Create lobby response (no cards shown)
        lobby_players = []
        for player in players:
            player_dict = dict(player)
            # Empty hands in lobby for security
            player_dict["hand"] = []
            player_dict["spreads"] = []
            player_dict["is_computer"] = bool(player_dict["is_computer"])  # Convert to boolean
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
        print(f"❌ Get lobby state error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to get lobby state: {str(e)}")

@app.get("/api/game/available")
async def get_available_games():
    """Get available games"""
    print("📋 Get available games")
    
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
            ORDER BY g.created_at DESC
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
        print(f"❌ Get available games error: {traceback.format_exc()}")
        return {"available_games": []}

@app.get("/api/game/user/{user_id}/active")
async def get_user_active_game(user_id: str):
    """Get user's active game"""
    print(f"🔍 Get active game for user: {user_id}")
    
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
        print(f"❌ Get active game error: {traceback.format_exc()}")
        return {"hasActiveGame": False}

# ============ DEBUG ENDPOINTS ============
@app.get("/api/debug/db")
async def debug_db():
    """Debug database state"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Count tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        counts = {}
        for table in tables:
            table_name = table['name']
            cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
            count = cursor.fetchone()['count']
            counts[table_name] = count
        
        conn.close()
        
        return {
            "tables": [t['name'] for t in tables],
            "counts": counts,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}

# ============ ROOT ENDPOINT ============
@app.get("/")
async def root():
    return {
        "message": "Tonk Game API",
        "status": "running",
        "version": API_VERSION,
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
                "user_active": "GET /api/game/user/{id}/active"
            },
            "system": {
                "ping": "GET /api/ping",
                "warmup": "GET /api/warmup",
                "debug": "GET /api/debug/db"
            }
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)