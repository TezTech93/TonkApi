from fastapi import FastAPI, HTTPException, Depends, status,Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, validator
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import uuid
import json
import random
from passlib.context import CryptContext
import sqlite3
import os
import csv
import io
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi import UploadFile, File, Form
import jwt
import re

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

# JWT Configuration
SECRET_KEY = os.environ.get("SECRET_KEY", "tonk-game-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7  # Token expires in 7 days

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

# Pydantic models with custom email validation
class UserRegister(BaseModel):
    username: str
    email: str
    password: str
    
    @validator('email')
    def validate_email(cls, v):
        """Simple email validation using regex"""
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, v):
            raise ValueError('Invalid email address')
        return v
    
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
    """Create a JWT token"""
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    token_data = {
        "sub": username,
        "user_id": user_id,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    return token

def verify_token(token: str) -> Optional[Dict]:
    """Verify a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {
            "user_id": payload.get("user_id"),
            "username": payload.get("sub"),
            "exp": payload.get("exp")
        }
    except jwt.ExpiredSignatureError:
        print(f"❌ Token expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"❌ Invalid token: {e}")
        return None
    except Exception as e:
        print(f"❌ Token verification error: {e}")
        return None

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from token"""
    token = credentials.credentials
    user = verify_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
    
def get_user_by_id(user_id: str):
    """Get user by ID from database"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, username, email, created_at, last_login, games_played, games_won, total_score FROM users WHERE id = ?",
            (user_id,)
        )
        user = cursor.fetchone()
        return dict(user) if user else None
    finally:
        conn.close()

def get_user_by_username(username: str):
    """Get user by username from database"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, username, email, created_at, last_login, games_played, games_won, total_score FROM users WHERE username = ?",
            (username,)
        )
        user = cursor.fetchone()
        return dict(user) if user else None
    finally:
        conn.close()

def get_user_stats(user_id: str):
    """Get comprehensive user statistics"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Get basic user info
        cursor.execute(
            "SELECT username, games_played, games_won, total_score FROM users WHERE id = ?",
            (user_id,)
        )
        user = cursor.fetchone()
        
        if not user:
            return None
            
        stats = dict(user)
        
        # Get recent games
        cursor.execute(
            """
            SELECT g.id, g.room_code, g.game_name, g.game_status, g.created_at, 
                   g.started_at, g.completed_at, g.winner_id,
                   gp.score as player_score
            FROM games g
            JOIN game_players gp ON g.id = gp.game_id
            WHERE gp.user_id = ?
            ORDER BY g.created_at DESC
            LIMIT 10
            """,
            (user_id,)
        )
        recent_games = cursor.fetchall()
        stats['recent_games'] = [dict(game) for game in recent_games]
        
        # Get win rate
        if stats['games_played'] > 0:
            stats['win_rate'] = (stats['games_won'] / stats['games_played']) * 100
        else:
            stats['win_rate'] = 0
            
        return stats
    finally:
        conn.close()

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

# Enhanced game logic functions
def calculate_hand_points(hand):
    """Calculate total points in hand"""
    total = 0
    for card in hand:
        # Aces are 1, face cards are 10, others are their numeric value
        if card['rank'] in ['J', 'Q', 'K']:
            total += 10
        elif card['rank'] == 'A':
            total += 1
        else:
            total += int(card['rank'])
    return total

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

def check_for_tonk(hand):
    """Check if player has Tonk (5 points or less)"""
    return calculate_hand_points(hand) <= 5

def get_valid_moves(game_state, player_id):
    """Determine valid moves for player"""
    player = next((p for p in game_state['players'] if p['id'] == player_id), None)
    if not player:
        return []
    
    turn_phase = game_state.get('turn_phase', 'waiting')
    current_player_idx = game_state.get('current_player_index', 0)
    current_player = game_state['players'][current_player_idx] if game_state['players'] else None
    
    moves = []
    
    if player['id'] != current_player['id']:
        return moves  # Not player's turn
    
    if turn_phase == 'draw':
        moves.append('draw_from_deck')
        if game_state['discard_pile']:
            moves.append('draw_from_discard')
    
    elif turn_phase == 'play':
        moves.append('discard')
    
    elif turn_phase == 'discard':
        moves.append('discard')
    
    return moves

# Database export/import functions
def export_database():
    """Export entire database as JSON"""
    conn = get_db()
    cursor = conn.cursor()
    
    data = {}
    
    # Export users
    cursor.execute("SELECT * FROM users")
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
        
        # Import users
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
                       (id, room_code, game_name, creator_id, game_status, 
                        max_players, created_at, started_at, completed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (game['id'], game['room_code'], game['game_name'], 
                     game['creator_id'], game['game_status'], game['max_players'],
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
    
@app.get("/api/users")
async def get_all_users(
    current_user: Dict = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """Get all users (paginated) - Requires authentication"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Count total users
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total = cursor.fetchone()['total']
        
        # Get paginated users
        cursor.execute(
            """
            SELECT id, username, email, created_at, last_login, 
                   games_played, games_won, total_score
            FROM users 
            ORDER BY username
            LIMIT ? OFFSET ?
            """,
            (limit, offset)
        )
        users = cursor.fetchall()
        
        return {
            "success": True,
            "total": total,
            "limit": limit,
            "offset": offset,
            "users": [
                {
                    "id": user['id'],
                    "username": user['username'],
                    "email": user['email'],
                    "created_at": user['created_at'],
                    "last_login": user['last_login'],
                    "stats": {
                        "games_played": user['games_played'],
                        "games_won": user['games_won'],
                        "total_score": user['total_score']
                    }
                }
                for user in users
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get users: {str(e)}"
        )
    finally:
        conn.close()

@app.get("/api/users/me")
async def get_current_user_info(current_user: Dict = Depends(get_current_user)):
    """Get current authenticated user's information"""
    user_info = get_user_by_id(current_user["user_id"])
    
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {
        "success": True,
        "user": user_info
    }

@app.get("/api/users/{user_id}")
async def get_user_by_id_endpoint(
    user_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """Get specific user by ID - Requires authentication"""
    user_info = get_user_by_id(user_id)
    
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
async def get_user_by_username_endpoint(
    username: str,
    current_user: Dict = Depends(get_current_user)
):
    """Get user by username - Requires authentication"""
    user_info = get_user_by_username(username)
    
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {
        "success": True,
        "user": user_info
    }

@app.get("/api/users/{user_id}/stats")
async def get_user_statistics(
    user_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """Get comprehensive user statistics"""
    stats = get_user_stats(user_id)
    
    if not stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {
        "success": True,
        "stats": stats
    }

@app.get("/api/users/me/stats")
async def get_current_user_stats(current_user: Dict = Depends(get_current_user)):
    """Get current user's statistics"""
    stats = get_user_stats(current_user["user_id"])
    
    if not stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {
        "success": True,
        "stats": stats
    }

@app.put("/api/users/me")
async def update_current_user(
    update_data: UserUpdate,
    current_user: Dict = Depends(get_current_user)
):
    """Update current user's information"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Get current user from database
        cursor.execute(
            "SELECT email, password_hash FROM users WHERE id = ?",
            (current_user["user_id"],)
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
                (update_data.email, current_user["user_id"])
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
            if not verify_password(update_data.current_password, user['password_hash']):
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
            new_password_hash = hash_password(update_data.new_password)
            update_fields.append("password_hash = ?")
            update_values.append(new_password_hash)
        
        # If no fields to update
        if not update_fields:
            return {
                "success": True,
                "message": "No changes to update"
            }
        
        # Build and execute update query
        update_values.append(current_user["user_id"])
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

@app.delete("/api/users/me")
async def delete_current_user(
    current_user: Dict = Depends(get_current_user),
    confirm_password: Optional[str] = Form(None)
):
    """Delete current user account"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Verify password for security
        if not confirm_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password confirmation is required to delete account"
            )
        
        # Get user's password hash
        cursor.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (current_user["user_id"],)
        )
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Verify password
        if not verify_password(confirm_password, user['password_hash']):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password is incorrect"
            )
        
        # Delete user (cascade will handle related records based on foreign keys)
        cursor.execute("DELETE FROM users WHERE id = ?", (current_user["user_id"],))
        conn.commit()
        
        return {
            "success": True,
            "message": "User account deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user: {str(e)}"
        )
    finally:
        conn.close()

# Authentication Endpoints
@app.post("/api/auth/register")
async def register(user_data: UserRegister):
    """Register a new user"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        print(f"📝 Registration attempt for: {user_data.username}")
        
        # Check if user already exists
        cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", 
                      (user_data.username, user_data.email))
        existing_user = cursor.fetchone()
        
        if existing_user:
            print(f"❌ User already exists: {user_data.username}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username or email already exists"
            )
        
        # Create new user
        user_id = str(uuid.uuid4())
        password_hash = hash_password(user_data.password)
        
        print(f"✅ Creating user: {user_data.username} with ID: {user_id}")
        
        cursor.execute(
            "INSERT INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
            (user_id, user_data.username, user_data.email, password_hash)
        )
        
        # Create token
        access_token = create_access_token(user_id, user_data.username)
        
        conn.commit()
        
        print(f"✅ Registration successful for: {user_data.username}")
        
        return {
            "success": True,
            "message": "Registration successful",
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user_id,
            "username": user_data.username,
            "expires_in": f"{ACCESS_TOKEN_EXPIRE_DAYS} days"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        print(f"❌ Registration error: {str(e)}")
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
        print(f"🔐 Login attempt for: {user_data.username}")
        
        # Find user by username
        cursor.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (user_data.username,)
        )
        user = cursor.fetchone()
        
        if not user:
            print(f"❌ User not found: {user_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        print(f"✅ User found: {user['username']}")
        
        # Verify password
        if not verify_password(user_data.password, user['password_hash']):
            print(f"❌ Password incorrect for user: {user_data.username}")
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
        
        print(f"✅ Login successful for: {user['username']}")
        
        return {
            "success": True,
            "message": "Login successful",
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user['id'],
            "username": user['username'],
            "expires_in": f"{ACCESS_TOKEN_EXPIRE_DAYS} days"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        print(f"❌ Login error: {str(e)}")
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

@app.get("/api/auth/profile")
async def get_user_profile(current_user: Dict = Depends(get_current_user)):
    """Get user profile"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT id, username, email, created_at, last_login FROM users WHERE id = ?",
            (current_user["user_id"],)
        )
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return {
            "success": True,
            "profile": {
                "id": user['id'],
                "username": user['username'],
                "email": user['email'],
                "created_at": user['created_at'],
                "last_login": user['last_login']
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get profile: {str(e)}"
        )
    finally:
        conn.close()

# Game Endpoints
@app.post("/api/game/create")
async def create_game(game_data: GameCreate, current_user: Dict = Depends(get_current_user)):
    """Create a new game (requires authentication)"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        print(f"🎮 Creating game for user: {current_user['username']}")
        
        # Generate game ID and room code
        game_id = str(uuid.uuid4())
        
        # Generate a 6-character room code without confusing characters
        room_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        
        print(f"🎮 Generated game_id: {game_id}, room_code: {room_code}")
        
        # Create game record - use current_user's ID as creator
        cursor.execute(
            """INSERT INTO games (id, room_code, game_name, creator_id, game_status) 
               VALUES (?, ?, ?, ?, ?)""",
            (game_id, room_code, game_data.game_name, current_user['user_id'], 'lobby')
        )
        
        # Add players to game
        player_ids = []
        for i, player in enumerate(game_data.players):
            player_id = str(uuid.uuid4())
            player_ids.append(player_id)
            
            # Get user ID for human player (first non-computer)
            user_id_for_player = None
            if i == 0 and not player.is_computer:
                user_id_for_player = current_user['user_id']
            
            cursor.execute(
                """INSERT INTO game_players 
                   (id, game_id, user_id, player_name, position, is_computer, is_host, is_ready) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (player_id, game_id, user_id_for_player,
                 player.name, i, player.is_computer, i == 0, True)
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
        state_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO game_states (id, game_id, state_json) VALUES (?, ?, ?)",
            (state_id, game_id, json.dumps(game_state))
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
async def join_game(room_code: str, join_data: GameJoin, current_user: Dict = Depends(get_current_user)):
    """Join an existing game (requires authentication)"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        print(f"🎮 Join attempt for room: {room_code} by user: {current_user['username']}")
        
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
        
        if player_count >= 4:  # Max 4 players
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Game is full"
            )
        
        # Add player to game
        player_id = str(uuid.uuid4())
        position = player_count
        
        cursor.execute(
            """INSERT INTO game_players 
               (id, game_id, user_id, player_name, position, is_computer, is_host, is_ready) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (player_id, game['id'], current_user['user_id'], join_data.playerName, 
             position, False, False, True)
        )
        
        # Get updated game state
        cursor.execute(
            "SELECT state_json FROM game_states WHERE game_id = ?",
            (game['id'],)
        )
        state_record = cursor.fetchone()
        
        game_state = None
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
                'is_ready': True
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
                    'is_ready': True
                }]
            }
        
        conn.commit()
        
        print(f"✅ User {current_user['username']} joined game {room_code}")
        
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
        print(f"❌ Error joining game: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to join game: {str(e)}"
        )
    finally:
        conn.close()

@app.get("/api/game/{identifier}/state")
async def get_game_state(identifier: str):
    """Get current game state (public)"""
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
    """Get lobby state (without cards) - public"""
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
    """Start a game (requires authentication and host status)"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        print(f"🎮 Start game request for: {identifier} by user: {current_user['username']}")
        
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
            print(f"❌ User {current_user['username']} is not the host")
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
        
        print(f"✅ Game {identifier} started successfully")
        
        return {
            "success": True,
            "message": "Game started successfully",
            "gameState": game_state
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        print(f"❌ Error starting game: {str(e)}")
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

@app.post("/api/game/{game_id}/move-enhanced")
async def make_enhanced_move(game_id: str, move_request: MoveRequest):
    """Make a move with enhanced game logic"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
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
        
        if not current_player or current_player['id'] != move_request.playerId:
            raise HTTPException(status_code=400, detail="Not player's turn")
        
        # Process move based on type
        move_result = {
            'success': False,
            'message': '',
            'gameState': game_state
        }
        
        player = next((p for p in game_state['players'] if p['id'] == move_request.playerId), None)
        
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
                'player': player['name']
            })
            
            move_result['success'] = True
            move_result['message'] = f"{player['name']} played a spread"
        
        # Update last move
        game_state['last_move'] = {
            'playerId': move_request.playerId,
            'playerName': player['name'],
            'moveType': move_request.moveType,
            'moveData': move_request.moveData,
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
        
        move_result['gameState'] = game_state
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

# Admin Endpoints
@app.get("/api/admin/export/json")
async def export_database_json(admin_token: str = Form(...)):
    """Export entire database as JSON (protected)"""
    # Simple admin token check (in production, use proper auth)
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
    print(f"🔑 JWT Algorithm: {ALGORITHM}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")