from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import uuid
import json
import random
from passlib.context import CryptContext
import sqlite3
import os

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

# Security
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Database setup
DATABASE_FILE = "tonk_game.db"

def init_db():
    """Initialize database tables"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP
    )
    ''')
    
    # Games table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS games (
        id TEXT PRIMARY KEY,
        room_code TEXT UNIQUE NOT NULL,
        game_name TEXT,
        creator_id TEXT,
        game_status TEXT DEFAULT 'lobby',
        max_players INTEGER DEFAULT 4,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        FOREIGN KEY (creator_id) REFERENCES users (id)
    )
    ''')
    
    # Players table (players in games)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS game_players (
        id TEXT PRIMARY KEY,
        game_id TEXT NOT NULL,
        user_id TEXT,
        player_name TEXT NOT NULL,
        position INTEGER,
        is_computer BOOLEAN DEFAULT FALSE,
        is_ready BOOLEAN DEFAULT FALSE,
        is_host BOOLEAN DEFAULT FALSE,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        left_at TIMESTAMP,
        FOREIGN KEY (game_id) REFERENCES games (id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    # Game states table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS game_states (
        id TEXT PRIMARY KEY,
        game_id TEXT UNIQUE NOT NULL,
        state_json TEXT NOT NULL,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        turn_count INTEGER DEFAULT 0,
        current_player_index INTEGER DEFAULT 0,
        turn_phase TEXT DEFAULT 'waiting',
        FOREIGN KEY (game_id) REFERENCES games (id)
    )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

# Pydantic models
class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class PlayerCreate(BaseModel):
    name: str
    is_computer: bool = False
    position: Optional[int] = None

class GameCreate(BaseModel):
    players: List[PlayerCreate]
    game_name: Optional[str] = None
    userId: Optional[str] = None

class GameJoin(BaseModel):
    playerName: str
    userId: Optional[str] = None

class MoveRequest(BaseModel):
    playerId: str
    moveType: str
    moveData: Dict[str, Any] = {}

# Helper functions
def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(user_id: str, username: str) -> str:
    """Create a JWT token (simplified version)"""
    # In a real app, use proper JWT with jose library
    token_data = {
        "sub": username,
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(days=7)
    }
    return f"mock_jwt.{user_id}.{username}"

def verify_token(token: str) -> Optional[Dict]:
    """Verify a token (simplified)"""
    try:
        parts = token.split(".")
        if len(parts) == 3 and parts[0] == "mock_jwt":
            return {"user_id": parts[1], "username": parts[2]}
    except:
        return None
    return None

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from token"""
    token = credentials.credentials
    user = verify_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

# Deck and card utilities
def create_deck():
    """Create a standard deck of 52 cards"""
    suits = ['hearts', 'diamonds', 'clubs', 'spades']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    deck = []
    for suit in suits:
        for rank in ranks:
            # Assign point values
            if rank in ['J', 'Q', 'K']:
                value = 10
            elif rank == 'A':
                value = 1  # In Tonk, Ace is low
            else:
                value = int(rank)
            
            deck.append({
                'id': f"{rank}_{suit}",
                'rank': rank,
                'suit': suit,
                'value': value,
                'display': f"{rank}{suit[0].upper()}"
            })
    return deck

def deal_cards(deck, num_players):
    """Deal cards to players"""
    random.shuffle(deck)
    
    # In Tonk, each player gets 7 cards
    hands = [[] for _ in range(num_players)]
    for i in range(7):  # 7 cards each
        for player_idx in range(num_players):
            if deck:
                hands[player_idx].append(deck.pop())
    
    return deck, hands

def create_initial_game_state(game_id, room_code, players):
    """Create initial game state for a new game"""
    deck = create_deck()
    num_players = len(players)
    deck, hands = deal_cards(deck, num_players)
    
    # Assign cards to players
    game_players = []
    for i, player in enumerate(players):
        game_players.append({
            'id': player['id'],
            'name': player['name'],
            'hand': hands[i],
            'is_computer': player['is_computer'],
            'is_current_turn': i == 0,  # First player starts
            'position': i,
            'points': 0,
            'is_ready': False
        })
    
    game_state = {
        'id': game_id,
        'room_code': room_code,
        'game_status': 'lobby',
        'turn_count': 0,
        'turn_phase': 'waiting',
        'deck': deck,
        'discard_pile': [],
        'players': game_players,
        'current_player_index': 0,
        'last_move': None,
        'created_at': datetime.utcnow().isoformat()
    }
    
    return game_state

# API Endpoints
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Tonk Game API",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/ping")
async def ping():
    """Health check endpoint"""
    return {
        "status": "pong",
        "timestamp": datetime.utcnow().isoformat(),
        "server": "TonkAPI",
        "environment": "Render.com"
    }

@app.get("/api/ping")
async def api_ping():
    """API health check"""
    return await ping()

@app.post("/api/auth/register")
async def register(user_data: UserRegister):
    """Register a new user"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Check if user already exists
        cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", 
                      (user_data.username, user_data.email))
        existing_user = cursor.fetchone()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username or email already exists"
            )
        
        # Create new user
        user_id = str(uuid.uuid4())
        password_hash = hash_password(user_data.password)
        
        cursor.execute(
            "INSERT INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
            (user_id, user_data.username, user_data.email, password_hash)
        )
        
        # Create token
        access_token = create_access_token(user_id, user_data.username)
        
        conn.commit()
        
        return {
            "success": True,
            "message": "Registration successful",
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user_id,
            "username": user_data.username
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )
    finally:
        conn.close()

@app.post("/api/auth/login")
async def login(user_data: UserLogin):
    """Login user"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Find user by username
        cursor.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (user_data.username,)
        )
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        # Verify password
        if not verify_password(user_data.password, user['password_hash']):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        # Update last login
        cursor.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
            (user['id'],)
        )
        
        # Create token
        access_token = create_access_token(user['id'], user['username'])
        
        conn.commit()
        
        return {
            "success": True,
            "message": "Login successful",
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user['id'],
            "username": user['username']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}"
        )
    finally:
        conn.close()

@app.get("/api/auth/validate-token")
async def validate_token(current_user: Dict = Depends(get_current_user)):
    """Validate token"""
    return {
        "valid": True,
        "user_id": current_user["user_id"],
        "username": current_user["username"]
    }

@app.post("/api/game/create")
async def create_game(game_data: GameCreate):
    """Create a new game"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        print(f"🎮 Creating game with data: {game_data}")
        
        # Generate game ID and room code
        game_id = str(uuid.uuid4())
        
        # Generate a 6-character room code without confusing characters
        room_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        
        print(f"🎮 Generated game_id: {game_id}, room_code: {room_code}")
        
        # Create game record
        cursor.execute(
            """INSERT INTO games (id, room_code, game_name, creator_id, game_status) 
               VALUES (?, ?, ?, ?, ?)""",
            (game_id, room_code, game_data.game_name, game_data.userId, 'lobby')
        )
        
        # Add players to game
        player_ids = []
        for i, player in enumerate(game_data.players):
            player_id = str(uuid.uuid4())
            player_ids.append(player_id)
            
            # Get user ID for human player (first non-computer)
            user_id_for_player = None
            if i == 0 and not player.is_computer and game_data.userId:
                user_id_for_player = game_data.userId
            
            cursor.execute(
                """INSERT INTO game_players 
                   (id, game_id, user_id, player_name, position, is_computer, is_host) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (player_id, game_id, user_id_for_player,
                 player.name, i, player.is_computer, i == 0)
            )
        
        # Create initial game state
        players_for_state = []
        for i, (player, player_id) in enumerate(zip(game_data.players, player_ids)):
            players_for_state.append({
                'id': player_id,
                'name': player.name,
                'is_computer': player.is_computer,
                'position': i
            })
        
        game_state = create_initial_game_state(game_id, room_code, players_for_state)
        
        # Save game state
        cursor.execute(
            "INSERT INTO game_states (id, game_id, state_json) VALUES (?, ?, ?)",
            (str(uuid.uuid4()), game_id, json.dumps(game_state))
        )
        
        conn.commit()
        
        # Return human player's ID (first non-computer player)
        human_player_id = None
        for i, (player, pid) in enumerate(zip(game_data.players, player_ids)):
            if not player.is_computer:
                human_player_id = pid
                break
        
        if not human_player_id and player_ids:
            human_player_id = player_ids[0]
        
        print(f"✅ Game created: {room_code}, player_id: {human_player_id}")
        
        return {
            "success": True,
            "message": "Game created successfully",
            "gameId": game_id,
            "roomCode": room_code,
            "playerId": human_player_id,
            "gameState": game_state
        }
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error creating game: {str(e)}")
        import traceback
        traceback.print_exc()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create game: {str(e)}"
        )
    finally:
        conn.close()

@app.post("/api/game/{room_code}/join")
async def join_game(room_code: str, join_data: GameJoin):
    """Join an existing game"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Find game by room code
        cursor.execute(
            "SELECT id, game_status, max_players FROM games WHERE room_code = ?",
            (room_code.upper(),)
        )
        game = cursor.fetchone()
        
        if not game:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
        
        if game['game_status'] != 'lobby':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Game has already started"
            )
        
        # Check if game is full
        cursor.execute(
            "SELECT COUNT(*) as count FROM game_players WHERE game_id = ?",
            (game['id'],)
        )
        player_count = cursor.fetchone()['count']
        
        if player_count >= game['max_players']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Game is full"
            )
        
        # Add player to game
        player_id = str(uuid.uuid4())
        position = player_count
        
        cursor.execute(
            """INSERT INTO game_players 
               (id, game_id, user_id, player_name, position, is_computer, is_host) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (player_id, game['id'], join_data.userId, join_data.playerName, 
             position, False, False)
        )
        
        # Get updated game state
        cursor.execute(
            "SELECT state_json FROM game_states WHERE game_id = ?",
            (game['id'],)
        )
        state_record = cursor.fetchone()
        
        if state_record:
            game_state = json.loads(state_record['state_json'])
            
            # Add new player to game state
            game_state['players'].append({
                'id': player_id,
                'name': join_data.playerName,
                'hand': [],
                'is_computer': False,
                'is_current_turn': False,
                'position': position,
                'points': 0,
                'is_ready': False
            })
            
            # Update game state
            cursor.execute(
                "UPDATE game_states SET state_json = ? WHERE game_id = ?",
                (json.dumps(game_state), game['id'])
            )
        else:
            # Should not happen, but create basic state
            game_state = {
                'id': game['id'],
                'room_code': room_code.upper(),
                'game_status': 'lobby',
                'players': [{
                    'id': player_id,
                    'name': join_data.playerName,
                    'hand': [],
                    'is_computer': False,
                    'is_current_turn': False,
                    'position': 0,
                    'points': 0,
                    'is_ready': False
                }]
            }
        
        conn.commit()
        
        return {
            "success": True,
            "message": "Joined game successfully",
            "gameId": game['id'],
            "playerId": player_id,
            "gameState": game_state
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to join game: {str(e)}"
        )
    finally:
        conn.close()

@app.get("/api/game/{identifier}/state")
async def get_game_state(identifier: str):
    """Get current game state"""
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
        
        if result['state_json']:
            game_state = json.loads(result['state_json'])
        else:
            # Create basic state if none exists
            cursor.execute(
                "SELECT player_name, is_computer FROM game_players WHERE game_id = ? ORDER BY position",
                (result['id'],)
            )
            players_data = cursor.fetchall()
            
            players = []
            for i, player_data in enumerate(players_data):
                players.append({
                    'id': f"player-{i}",
                    'name': player_data['player_name'],
                    'hand': [],
                    'is_computer': bool(player_data['is_computer']),
                    'is_current_turn': i == 0,
                    'position': i,
                    'points': 0,
                    'is_ready': False
                })
            
            game_state = {
                'id': result['id'],
                'room_code': result['room_code'],
                'game_status': result['game_status'],
                'players': players,
                'deck': [],
                'discard_pile': [],
                'turn_count': 0,
                'turn_phase': 'waiting',
                'current_player_index': 0
            }
        
        return {
            "success": True,
            "gameState": game_state
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get game state: {str(e)}"
        )
    finally:
        conn.close()

@app.get("/api/game/{identifier}/lobby")
async def get_lobby_state(identifier: str):
    """Get lobby state (without cards)"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Try to find game by ID or room code
        cursor.execute(
            """SELECT g.id, g.room_code, g.game_name, g.game_status, g.max_players, 
                      g.creator_id, g.created_at 
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
        
        # Get players
        cursor.execute(
            """SELECT id, player_name, position, is_computer, is_ready, is_host, 
                      joined_at 
               FROM game_players 
               WHERE game_id = ? 
               ORDER BY position""",
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
                'joined_at': player['joined_at']
            })
        
        return {
            "success": True,
            "gameState": {
                'id': game['id'],
                'room_code': game['room_code'],
                'game_name': game['game_name'],
                'game_status': game['game_status'],
                'max_players': game['max_players'],
                'creator_id': game['creator_id'],
                'created_at': game['created_at'],
                'players': players,
                'player_count': len(players),
                'can_start': len(players) >= 2  # Need at least 2 players to start
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
async def start_game(identifier: str, current_user: Dict = Depends(get_current_user)):
    """Start a game"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Find game
        cursor.execute(
            "SELECT id, room_code, game_status FROM games WHERE id = ? OR room_code = ?",
            (identifier, identifier.upper())
        )
        game = cursor.fetchone()
        
        if not game:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
        
        if game['game_status'] != 'lobby':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Game has already started"
            )
        
        # Check if user is host
        cursor.execute(
            """SELECT is_host FROM game_players 
               WHERE game_id = ? AND user_id = ?""",
            (game['id'], current_user['user_id'])
        )
        player = cursor.fetchone()
        
        if not player or not player['is_host']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the host can start the game"
            )
        
        # Check if enough players
        cursor.execute(
            "SELECT COUNT(*) as count FROM game_players WHERE game_id = ?",
            (game['id'],)
        )
        player_count = cursor.fetchone()['count']
        
        if player_count < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Need at least 2 players to start"
            )
        
        # Update game status
        cursor.execute(
            "UPDATE games SET game_status = 'playing', started_at = CURRENT_TIMESTAMP WHERE id = ?",
            (game['id'],)
        )
        
        # Get game state
        cursor.execute(
            "SELECT state_json FROM game_states WHERE game_id = ?",
            (game['id'],)
        )
        state_record = cursor.fetchone()
        
        if state_record:
            game_state = json.loads(state_record['state_json'])
            game_state['game_status'] = 'playing'
            game_state['turn_phase'] = 'draw'
            game_state['current_player_index'] = 0
            
            # Update first player's turn
            if game_state['players']:
                for i, player in enumerate(game_state['players']):
                    player['is_current_turn'] = (i == 0)
            
            # Update state
            cursor.execute(
                "UPDATE game_states SET state_json = ? WHERE game_id = ?",
                (json.dumps(game_state), game['id'])
            )
        else:
            # Should not happen, but create a basic state
            game_state = {
                'id': game['id'],
                'room_code': game['room_code'],
                'game_status': 'playing',
                'turn_phase': 'draw',
                'turn_count': 0,
                'current_player_index': 0
            }
        
        conn.commit()
        
        return {
            "success": True,
            "message": "Game started successfully",
            "gameState": game_state
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start game: {str(e)}"
        )
    finally:
        conn.close()

@app.post("/api/game/{game_id}/move")
async def make_move(game_id: str, move_request: MoveRequest):
    """Make a move in the game"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Verify game exists and is playing
        cursor.execute(
            "SELECT game_status FROM games WHERE id = ?",
            (game_id,)
        )
        game = cursor.fetchone()
        
        if not game:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
        
        if game['game_status'] != 'playing':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Game is not in progress"
            )
        
        # Get current game state
        cursor.execute(
            "SELECT state_json FROM game_states WHERE game_id = ?",
            (game_id,)
        )
        state_record = cursor.fetchone()
        
        if not state_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game state not found"
            )
        
        game_state = json.loads(state_record['state_json'])
        
        # Update game state based on move
        # This is a simplified move handler - you'll need to implement actual game logic
        move_result = {
            'success': True,
            'message': f"Move {move_request.moveType} processed",
            'gameState': game_state  # Return updated state
        }
        
        # Update last move
        game_state['last_move'] = {
            'playerId': move_request.playerId,
            'moveType': move_request.moveType,
            'moveData': move_request.moveData,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Save updated state
        cursor.execute(
            "UPDATE game_states SET state_json = ? WHERE game_id = ?",
            (json.dumps(game_state), game_id)
        )
        
        conn.commit()
        
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

@app.post("/api/game/{game_id}/ai-move")
async def ai_move(game_id: str):
    """Trigger AI move"""
    # This would handle AI player moves
    # For now, just return success
    return {
        "success": True,
        "message": "AI move will be processed",
        "timestamp": datetime.utcnow().isoformat()
    }

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
            "gameId": game['id']
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

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)