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