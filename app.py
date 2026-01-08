# app.py - WITH EXPLICIT DB INIT
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime
import json

# Import managers
from auth_manager import AuthManager
from game_manager import GameManager

app = FastAPI(title="Tonk Game API")

# CORS
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

# Models
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

# --- DIRECT DATABASE INITIALIZATION ---
@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    print("🚀 Starting up...")
    try:
        # Force database initialization
        from database import db
        db.ensure_tables_exist()
        print("✅ Database ready")
    except Exception as e:
        print(f"⚠️ Startup warning: {e}")

# --- SIMPLE TEST ENDPOINTS FIRST ---
@app.get("/api/test")
async def test_endpoint():
    """Test if server is running"""
    return {
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "message": "Server is alive"
    }

@app.get("/api/test/db")
async def test_db():
    """Test database connection"""
    try:
        from database import db
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 as test")
        result = cursor.fetchone()
        conn.close()
        return {
            "database": "connected",
            "test": result["test"] if result else None
        }
    except Exception as e:
        return {
            "database": "error",
            "error": str(e)
        }

# --- AUTH ENDPOINTS WITH EXCEPTION HANDLING ---
@app.post("/api/auth/register")
async def register_user(user_data: UserRegister):
    """Register a new user - WITH PROPER ERROR HANDLING"""
    print(f"📝 Register attempt: {user_data.username}")
    
    try:
        result = auth_manager.create_user(
            user_data.username,
            user_data.email,
            user_data.password
        )
        
        print(f"✅ User registered: {user_data.username}")
        
        return {
            "access_token": result["token"],
            "token_type": "bearer",
            "user_id": result["id"],
            "username": result["username"]
        }
        
    except ValueError as e:
        print(f"❌ Registration validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"❌ Registration error: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Registration failed. Please try again. Error: {str(e)[:100]}"
        )

@app.post("/api/auth/login")
async def login_user(user_data: UserLogin):
    """Login user"""
    print(f"🔐 Login attempt: {user_data.username}")
    
    try:
        result = auth_manager.authenticate_user(
            user_data.username,
            user_data.password
        )
        
        if not result:
            print(f"❌ Login failed for: {user_data.username}")
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        print(f"✅ User logged in: {user_data.username}")
        
        return {
            "access_token": result["token"],
            "token_type": "bearer",
            "user_id": result["id"],
            "username": result["username"]
        }
        
    except Exception as e:
        print(f"❌ Login error: {e}")
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")

# --- GAME ENDPOINTS ---
@app.post("/api/game/create")
async def create_game(request: CreateGameRequest):
    """Create a new game - SIMPLIFIED"""
    print(f"🎮 Create game request: {len(request.players)} players")
    
    try:
        result = game_manager.create_game(
            request.players,
            request.game_name,
            request.userId
        )
        
        print(f"✅ Game created: {result['room_code']}")
        
        # Get basic game info for response
        return {
            "success": True,
            "gameId": result["game_id"],
            "roomCode": result["room_code"],
            "playerId": result["player_id"],
            "players": request.players,
            "gameName": request.game_name or "Tonk Game"
        }
        
    except Exception as e:
        print(f"❌ Create game error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create game: {str(e)[:100]}"
        )

# --- HEALTH ENDPOINTS ---
@app.get("/api/ping")
async def ping():
    return {"status": "pong", "timestamp": datetime.now().isoformat()}

@app.get("/api/warmup")
async def warmup():
    """Warm up the server"""
    try:
        from database import db
        db.ensure_tables_exist()
        return {
            "status": "ready",
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "starting",
            "error": str(e)[:100],
            "timestamp": datetime.now().isoformat()
        }
        
# Add to app.py - MISSING ENDPOINTS

@app.post("/api/game/{room_code}/join")
async def join_game(room_code: str, request: JoinGameRequest):
    """Join an existing game"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Find game by room code
        cursor.execute("SELECT id FROM games WHERE room_code = ?", (room_code,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            raise HTTPException(404, "Game not found")
        
        game_id = game_row['id']
        
        # Get game to check status
        cursor.execute("SELECT game_status, max_players FROM games WHERE id = ?", (game_id,))
        game_info = cursor.fetchone()
        
        if game_info['game_status'] != 'lobby':
            conn.close()
            raise HTTPException(400, "Game already started")
        
        # Count current players
        cursor.execute("SELECT COUNT(*) as count FROM game_players WHERE game_id = ?", (game_id,))
        player_count = cursor.fetchone()['count']
        
        if player_count >= game_info['max_players']:
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
        conn.close()
        
        return {
            "success": True,
            "gameId": game_id,
            "playerId": player_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to join game: {str(e)}")

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

@app.get("/api/auth/profile")
async def get_profile(authorization: Optional[str] = Header(None)):
    """Get user profile"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    
    token = authorization.split(" ")[1]
    payload = decode_token(token)
    
    if not payload:
        raise HTTPException(401, "Invalid token")
    
    username = payload.get("sub")
    if not username:
        raise HTTPException(401, "Invalid token")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        raise HTTPException(404, "User not found")
    
    return {
        "id": user['id'],
        "username": user['username'],
        "email": user['email'],
        "games_played": user['games_played'],
        "games_won": user['games_won'],
        "online": bool(user['online']),
        "last_seen": user['last_seen']
    }

@app.get("/api/health")
async def health_check():
    """Health check"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as user_count FROM users")
        user_count = cursor.fetchone()['user_count']
        cursor.execute("SELECT COUNT(*) as game_count FROM games")
        game_count = cursor.fetchone()['game_count']
        conn.close()
        
        return {
            "status": "healthy",
            "users": user_count,
            "games": game_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.get("/api/status")
async def server_status():
    """Server status"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as table_count FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()['table_count']
        conn.close()
        
        return {
            "online": True,
            "status": "healthy",
            "database": {
                "tables": table_count,
                "connected": True
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "online": False,
            "status": "starting",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.get("/")
async def root():
    return {
        "message": "Tonk Game API",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "test": "/api/test",
            "test_db": "/api/test/db",
            "register": "POST /api/auth/register",
            "login": "POST /api/auth/login",
            "create_game": "POST /api/game/create",
            "ping": "/api/ping",
            "warmup": "/api/warmup"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)