# app.py - COMPLETE WITH ALL MODELS
from fastapi import FastAPI, HTTPException, Depends, Header, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import json
import traceback
import uuid
import sqlite3
import random

app = FastAPI(title="Tonk Game API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

class JoinGameRequest(BaseModel):  # ADD THIS
    playerName: str
    userId: Optional[str] = None

class MoveRequest(BaseModel):  # Optional for future
    playerId: str
    moveType: str
    moveData: Dict

# ============ DATABASE SETUP ============
def init_db():
    """Initialize database"""
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
        settings TEXT DEFAULT '{"allow_under_card_any_turn": true}',
        winner TEXT,
        win_reason TEXT,
        creator_id TEXT,
        max_players INTEGER DEFAULT 4
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
        position INTEGER
    )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized")

# Initialize on startup
@app.on_event("startup")
def startup():
    init_db()

def get_db():
    conn = sqlite3.connect("tonk_game.db")
    conn.row_factory = sqlite3.Row
    return conn

# ============ HELPER FUNCTIONS ============
import bcrypt
import jwt

SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=24)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

# ============ AUTH ENDPOINTS ============
@app.post("/api/auth/register")
async def register_user(user_data: UserRegister):
    """Register a new user"""
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
        conn.close()
        
        # Create token
        token = create_token(user_data.username)
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user_id,
            "username": user_data.username
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Registration failed: {str(e)}")

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
        
        # Update last seen
        cursor.execute(
            "UPDATE users SET last_seen = ?, online = 1 WHERE id = ?",
            (datetime.now().isoformat(), user['id'])
        )
        conn.commit()
        conn.close()
        
        # Create token
        token = create_token(user_data.username)
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user['id'],
            "username": user['username']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Login failed: {str(e)}")

# ============ HEALTH ENDPOINTS ============
@app.get("/api/ping")
async def ping():
    return {"status": "pong", "timestamp": datetime.now().isoformat()}

@app.get("/api/warmup")
async def warmup():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        return {
            "status": "ready",
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "starting",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# ============ GAME ENDPOINTS ============
@app.post("/api/game/create")
async def create_game(request: CreateGameRequest):
    """Create a new game"""
    try:
        game_id = str(uuid.uuid4())
        room_code = game_id[:6].upper()
        
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
                    "image": f"card_{rank}{suit_symbol}".lower(),
                    "backImage": "card_back",
                    "suitSymbol": suit_symbol,
                    "color": "red" if suit in ["hearts", "diamonds"] else "black"
                })
        
        random.shuffle(deck)
        
        # Save game to database
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO games (id, room_code, game_name, deck, creator_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (game_id, room_code, request.game_name, json.dumps(deck), request.userId, datetime.now().isoformat()))
        
        # Save players
        first_player_id = None
        for i, player_data in enumerate(request.players):
            player_id = str(uuid.uuid4())
            player_user_id = request.userId if i == 0 else None
            
            cursor.execute('''
                INSERT INTO game_players (id, game_id, user_id, name, is_computer, position)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                player_id, game_id, player_user_id, 
                player_data["name"], 
                1 if player_data.get("is_computer", False) else 0,
                i
            ))
            
            if i == 0:
                first_player_id = player_id
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "gameId": game_id,
            "roomCode": room_code,
            "playerId": first_player_id,
            "players": request.players,
            "gameName": request.game_name or "Tonk Game"
        }
        
    except Exception as e:
        raise HTTPException(500, f"Failed to create game: {str(e)}")

@app.post("/api/game/{room_code}/join")
async def join_game(room_code: str, request: JoinGameRequest):  # NOW DEFINED
    """Join an existing game"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Find game by room code
        cursor.execute("SELECT id, game_status, max_players FROM games WHERE room_code = ?", (room_code,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        game_id = game_row['id']
        
        if game_row['game_status'] != 'lobby':
            conn.close()
            raise HTTPException(400, "Game already started")
        
        # Count current players
        cursor.execute("SELECT COUNT(*) as count FROM game_players WHERE game_id = ?", (game_id,))
        player_count = cursor.fetchone()['count']
        
        if player_count >= game_row['max_players']:
            conn.close()
            raise HTTPException(400, "Game is full")
        
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
        updated_game = dict(cursor.fetchone())
        
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        # Parse game data
        updated_game["deck"] = json.loads(updated_game["deck"]) if updated_game["deck"] else []
        updated_game["discard_pile"] = json.loads(updated_game["discard_pile"]) if updated_game["discard_pile"] else []
        updated_game["under_card"] = json.loads(updated_game["under_card"]) if updated_game["under_card"] else None
        
        # Parse players
        game_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["hand"] = json.loads(player_dict["hand"]) if player_dict["hand"] else []
            player_dict["spreads"] = json.loads(player_dict["spreads"]) if player_dict["spreads"] else []
            player_dict["is_computer"] = bool(player_dict["is_computer"])
            game_players.append(player_dict)
        
        updated_game["players"] = game_players
        
        conn.close()
        
        return {
            "success": True,
            "gameId": game_id,
            "playerId": player_id,
            "gameState": updated_game
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to join game: {str(e)}")

@app.post("/api/game/{game_id}/start")
async def start_game(game_id: str):
    """Start a game - COMPLETE WORKING VERSION"""
    print(f"🚀 START GAME endpoint called for: {game_id}")
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 1. Get the game
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            print(f"❌ Game {game_id} not found")
            raise HTTPException(status_code=404, detail="Game not found")
        
        print(f"📋 Game found: {game_id}, status: {game_row['game_status']}")
        
        # 2. Check if game is in lobby
        if game_row['game_status'] != 'lobby':
            conn.close()
            print(f"❌ Game already {game_row['game_status']}")
            raise HTTPException(status_code=400, detail=f"Game is already {game_row['game_status']}")
        
        # 3. Get players
        cursor.execute("SELECT * FROM game_players WHERE game_id = ? ORDER BY position", (game_id,))
        players = cursor.fetchall()
        
        if len(players) < 2:
            conn.close()
            print(f"❌ Not enough players: {len(players)}")
            raise HTTPException(status_code=400, detail="Need at least 2 players")
        
        print(f"👥 Players: {len(players)}")
        
        # 4. Create a fresh deck
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
                    "image": f"card_{rank}{suit_symbol}".lower(),
                    "backImage": "card_back",
                    "suitSymbol": suit_symbol,
                    "color": "red" if suit in ["hearts", "diamonds"] else "black"
                })
        
        random.shuffle(deck)
        print(f"🃏 Deck created: {len(deck)} cards")
        
        # 5. Deal 5 cards to each player
        player_hands = {}
        cards_dealt = 0
        
        for player in players:
            hand = []
            for _ in range(5):
                if deck:
                    card = deck.pop()
                    card["isFaceUp"] = True
                    hand.append(card)
                    cards_dealt += 1
            
            # Save hand to database
            cursor.execute(
                "UPDATE game_players SET hand = ? WHERE id = ?",
                (json.dumps(hand), player['id'])
            )
            player_hands[player['id']] = hand
        
        print(f"🎴 Dealt {cards_dealt} cards to {len(players)} players")
        
        # 6. Setup discard pile (first card from remaining deck)
        discard_pile = []
        if deck:
            first_card = deck.pop()
            first_card["isFaceUp"] = True
            discard_pile.append(first_card)
            print(f"🗑️ Discard pile: {first_card['rank']} of {first_card['suit']}")
        
        # 7. Setup under card (next card from deck)
        under_card = deck.pop() if deck else None
        if under_card:
            under_card["isFaceUp"] = True
            print(f"⬇️ Under card: {under_card['rank']} of {under_card['suit']}")
        
        # 8. Update game status
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
            json.dumps({
                "playerId": players[0]['id'] if players else None,
                "playerName": players[0]['name'] if players else "System",
                "moveType": "start_game",
                "timestamp": datetime.now().isoformat()
            }),
            game_id
        ))
        
        conn.commit()
        
        # 9. Get updated game state to return
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        updated_game = dict(cursor.fetchone())
        
        # Parse JSON fields
        updated_game["deck"] = deck
        updated_game["discard_pile"] = discard_pile
        updated_game["under_card"] = under_card
        updated_game["last_move"] = {
            "playerId": players[0]['id'] if players else None,
            "playerName": players[0]['name'] if players else "System",
            "moveType": "start_game",
            "timestamp": datetime.now().isoformat()
        }
        
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
        
        print(f"✅ Game {game_id} started successfully!")
        print(f"📊 Final state: Deck={len(deck)}, Players={len(updated_players)}")
        
        return {
            "success": True,
            "gameId": game_id,
            "roomCode": game_row['room_code'],
            "status": "playing",
            "gameState": updated_game
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ ERROR in start_game: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to start game: {str(e)}")

@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str):
    """Get game state"""
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
        
        conn.close()
        
        # Parse game
        game = dict(game_row)
        game["deck"] = json.loads(game["deck"]) if game["deck"] else []
        game["discard_pile"] = json.loads(game["discard_pile"]) if game["discard_pile"] else []
        game["under_card"] = json.loads(game["under_card"]) if game["under_card"] else None
        game["table_spreads"] = json.loads(game["table_spreads"]) if game["table_spreads"] else []
        game["last_move"] = json.loads(game["last_move"]) if game["last_move"] else None
        game["settings"] = json.loads(game["settings"]) if game["settings"] else {}
        
        # Parse players
        game_players = []
        for player in players:
            player_dict = dict(player)
            player_dict["hand"] = json.loads(player_dict["hand"]) if player_dict["hand"] else []
            player_dict["spreads"] = json.loads(player_dict["spreads"]) if player_dict["spreads"] else []
            player_dict["is_computer"] = bool(player_dict["is_computer"])
            game_players.append(player_dict)
        
        game["players"] = game_players
        
        return {
            "success": True,
            "gameState": game,
            "lastMove": game.get("last_move")
        }
        
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/game/{game_id}/lobby")
async def get_lobby_state(game_id: str):
    """Get lobby state (players without cards)"""
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
        
        conn.close()
        
        # Create lobby response (no cards shown)
        lobby_players = []
        for player in players:
            player_dict = dict(player)
            # Empty hands in lobby
            player_dict["hand"] = []
            player_dict["spreads"] = []
            player_dict["is_computer"] = bool(player_dict["is_computer"])
            lobby_players.append(player_dict)
        
        return {
            "success": True,
            "players": lobby_players,
            "status": game_row['game_status'],
            "roomCode": game_row['room_code'],
            "gameName": game_row['game_name'],
            "maxPlayers": game_row['max_players'],
            "canStart": len(players) >= 2
        }
        
    except Exception as e:
        raise HTTPException(500, str(e))

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
        raise HTTPException(500, str(e))

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
        return {"hasActiveGame": False}

# ============ DEBUG ENDPOINTS ============
@app.get("/api/debug/game/{game_id}")
async def debug_game(game_id: str):
    """Debug endpoint to check game status"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get game
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game = cursor.fetchone()
        
        if not game:
            conn.close()
            return {"error": "Game not found"}
        
        # Get players
        cursor.execute("SELECT * FROM game_players WHERE game_id = ?", (game_id,))
        players = cursor.fetchall()
        
        conn.close()
        
        # Count cards in deck if it exists
        deck_count = 0
        if game['deck']:
            try:
                deck = json.loads(game['deck'])
                deck_count = len(deck)
            except:
                deck_count = 0
        
        return {
            "game_id": game_id,
            "room_code": game['room_code'],
            "status": game['game_status'],
            "turn_phase": game['turn_phase'],
            "players_count": len(players),
            "deck_cards": deck_count,
            "players": [
                {
                    "id": p['id'],
                    "name": p['name'],
                    "is_computer": bool(p['is_computer']),
                    "hand_cards": len(json.loads(p['hand'])) if p['hand'] else 0
                }
                for p in players
            ]
        }
    except Exception as e:
        return {"error": str(e)}

# ============ ROOT ENDPOINT ============
@app.get("/")
async def root():
    return {
        "message": "Tonk Game API",
        "status": "running",
        "endpoints": {
            "register": "POST /api/auth/register",
            "login": "POST /api/auth/login",
            "create_game": "POST /api/game/create",
            "join_game": "POST /api/game/{code}/join",
            "start_game": "POST /api/game/{id}/start",
            "game_state": "GET /api/game/{id}/state",
            "lobby_state": "GET /api/game/{id}/lobby",
            "available_games": "GET /api/game/available",
            "ping": "/api/ping",
            "warmup": "/api/warmup"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)