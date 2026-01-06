# app.py - Updated for frontend compatibility
from fastapi import FastAPI, HTTPException, Depends, Header, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import time
from datetime import datetime, timedelta
import json

# Import our managers
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

# Models (keep as before)
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

# Helper function to get current user from token
async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return None
    
    token = authorization.split(" ")[1]
    user = auth_manager.validate_token(token)
    
    if not user:
        return None
    
    return user

# --- Health & Warmup Endpoints ---
@app.get("/api/warmup")
async def warmup():
    """Warm up the server - FRONTEND COMPATIBLE"""
    try:
        # Test database connections
        auth_manager.get_user_by_username("test")
        game_manager.get_available_games()
        
        return {
            "status": "ready",
            "database": "connected",
            "timestamp": datetime.now().isoformat(),
            "message": "Server is warmed up and ready"
        }
    except Exception as e:
        return {
            "status": "warming",
            "timestamp": datetime.now().isoformat(),
            "message": f"Server is starting up: {str(e)}",
            "database": "initializing",
            "retry_in": 5
        }

@app.get("/api/ping")
async def ping():
    """Simple ping - FRONTEND COMPATIBLE"""
    return {"status": "pong", "timestamp": datetime.now().isoformat()}

@app.get("/api/status")
async def server_status():
    """Server status - FRONTEND COMPATIBLE"""
    try:
        online_users = auth_manager.get_online_users()
        available_games = game_manager.get_available_games()
        
        return {
            "online": True,
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now().isoformat(),
            "online_users": len(online_users)
        }
    except Exception as e:
        return {
            "online": False,
            "status": "starting",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.get("/api/health")
async def health_check():
    """Health check - FRONTEND COMPATIBLE"""
    try:
        online_users = auth_manager.get_online_users()
        available_games = game_manager.get_available_games()
        
        return {
            "status": "healthy",
            "online": True,
            "database": {"connected": True},
            "connections": {"websocket": 0, "games": 0},
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "online": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# --- Auth Endpoints (FRONTEND COMPATIBLE FORMAT) ---
@app.post("/api/auth/register", response_model=Dict)
async def register_user(user_data: UserRegister):
    """Register a new user - OLD FRONTEND FORMAT"""
    auth_manager.init_db()
    try:
        result = auth_manager.create_user(
            user_data.username,
            user_data.email,
            user_data.password
        )
        
        # Return OLD FRONTEND FORMAT
        return {
            "access_token": result["token"],
            "token_type": "bearer", 
            "user_id": result["id"],
            "username": result["username"]
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.post("/api/auth/login", response_model=Dict)
async def login_user(user_data: UserLogin):
    """Login user - OLD FRONTEND FORMAT"""
    result = auth_manager.authenticate_user(
        user_data.username,
        user_data.password
    )
    
    if not result:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )
    
    # Return OLD FRONTEND FORMAT
    return {
        "access_token": result["token"],
        "token_type": "bearer",
        "user_id": result["id"],
        "username": result["username"]
    }

@app.get("/api/auth/profile")
async def get_profile(current_user: Optional[Dict] = Depends(get_current_user)):
    """Get user profile - OLD FRONTEND FORMAT"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user = auth_manager.get_user_by_id(current_user["id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Return OLD FRONTEND FORMAT
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "games_played": user["games_played"],
        "games_won": user["games_won"],
        "online": bool(user["online"]),
        "last_seen": user["last_seen"]
    }

@app.get("/api/auth/online-users")
async def get_online_users():
    """Get online users - OLD FRONTEND FORMAT"""
    users = auth_manager.get_online_users()
    return {"online_users": users}

@app.get("/api/auth/validate-token")
async def validate_token(authorization: Optional[str] = Header(None)):
    """Validate token - OLD FRONTEND FORMAT"""
    if not authorization or not authorization.startswith("Bearer "):
        return {"valid": False}
    
    token = authorization.split(" ")[1]
    user = auth_manager.validate_token(token)
    
    if not user:
        return {"valid": False}
    
    return {
        "valid": True,
        "user_id": user["id"],
        "username": user["username"]
    }

# --- Game Endpoints (FRONTEND COMPATIBLE FORMAT) ---
@app.post("/api/game/create")
async def create_game(
    request: CreateGameRequest,
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Create a new game - OLD FRONTEND FORMAT"""
    # Get user ID (authenticated or guest)
    user_id = current_user["id"] if current_user else request.userId
    game_manager.init_db()
    try:
        result = game_manager.create_game(
            request.players,
            request.game_name,
            user_id
        )
        
        # Get the full game to return players
        game = game_manager.get_game(result["game_id"])
        
        # Return OLD FRONTEND FORMAT
        return {
            "success": True,
            "gameId": result["game_id"],
            "roomCode": result["room_code"],
            "playerId": result["player_id"],
            "players": [{"name": p["name"], "is_computer": p["is_computer"]} for p in game["players"]],
            "gameName": game["game_name"]
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/game/{room_code}/join")
async def join_game(
    room_code: str,
    request: JoinGameRequest,
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Join an existing game - OLD FRONTEND FORMAT"""
    user_id = current_user["id"] if current_user else request.userId
    
    try:
        result = game_manager.join_game(
            room_code,
            request.playerName,
            user_id
        )
        
        # Get the full game
        game = game_manager.get_game(result["game_id"])
        
        # Find the player in the game
        player = next((p for p in game["players"] if p["id"] == result["player_id"]), None)
        
        if not player:
            raise HTTPException(status_code=500, detail="Player not found in game")
        
        # Return OLD FRONTEND FORMAT
        return {
            "success": True,
            "gameId": result["game_id"],
            "playerId": result["player_id"],
            "gameState": game  # Full game state for frontend
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/game/available")
async def get_available_games():
    """Get available games - OLD FRONTEND FORMAT"""
    games = game_manager.get_available_games()
    return {"available_games": games}

@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str):
    """Get game state - OLD FRONTEND FORMAT"""
    game = game_manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    # Return OLD FRONTEND FORMAT
    return {
        "success": True,
        "gameState": game,
        "lastMove": game.get("last_move")
    }

@app.get("/api/game/{game_id}/lobby")
async def get_lobby_state(game_id: str):
    """Get lobby state - OLD FRONTEND FORMAT"""
    game = game_manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    # Don't show cards in lobby (frontend expects empty hands in lobby)
    lobby_players = []
    for player in game["players"]:
        player_copy = player.copy()
        player_copy["hand"] = []  # Empty hand in lobby
        player_copy["spreads"] = []  # Empty spreads in lobby
        lobby_players.append(player_copy)
    
    # Return OLD FRONTEND FORMAT
    return {
        "success": True,
        "players": lobby_players,
        "status": game["game_status"],
        "roomCode": game["room_code"],
        "gameName": game["game_name"],
        "createdAt": game["created_at"],
        "maxPlayers": game["max_players"],
        "canStart": len(game["players"]) >= 2
    }

@app.post("/api/game/{game_id}/start")
async def start_game(
    game_id: str,
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Start a game - OLD FRONTEND FORMAT"""
    game = game_manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    # Check permission (creator only)
    if current_user and game["creator_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Only creator can start game")
    
    try:
        result = game_manager.start_game(game_id)
        
        # Get updated game state
        updated_game = game_manager.get_game(game_id)
        
        # Return OLD FRONTEND FORMAT
        return {
            "success": True,
            "gameId": game_id,
            "roomCode": game["room_code"],
            "status": updated_game["game_status"],
            "gameState": updated_game
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/game/room/{room_code}/id")
async def get_game_id_by_room(room_code: str):
    """Get game ID from room code - OLD FRONTEND FORMAT"""
    game = game_manager.get_game_by_room_code(room_code)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    return {
        "success": True,
        "gameId": game["id"],
        "roomCode": game["room_code"],
        "status": game["game_status"]
    }

@app.get("/api/game/room/{room_code}/state")
async def get_game_state_by_room(room_code: str):
    """Get game state by room code - OLD FRONTEND FORMAT"""
    game = game_manager.get_game_by_room_code(room_code)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    return {
        "success": True,
        "gameState": game,
        "lastMove": game.get("last_move")
    }

@app.post("/api/game/{game_id}/move")
async def make_move(
    game_id: str,
    request: MoveRequest,
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Make a move - OLD FRONTEND FORMAT"""
    game = game_manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    # Find player
    player_index = next((i for i, p in enumerate(game["players"]) if p["id"] == request.playerId), -1)
    if player_index == -1:
        raise HTTPException(status_code=404, detail="Player not found")
    
    # Verify it's the player's turn
    if game["current_player_index"] != player_index:
        raise HTTPException(status_code=400, detail="Not your turn")
    
    # Process move (simplified - you'll need to implement full move logic)
    move_result = {
        "playerId": request.playerId,
        "playerName": game["players"][player_index]["name"],
        "moveType": request.moveType,
        "moveData": request.moveData,
        "timestamp": datetime.now().isoformat()
    }
    
    # Update last move
    game["last_move"] = move_result
    
    # Save game
    game_manager.save_game(game)
    
    # Return OLD FRONTEND FORMAT
    return {
        "success": True,
        "gameState": game,
        "lastMove": move_result
    }

@app.get("/api/game/user/{user_id}/active")
async def get_user_active_game(user_id: str):
    """Get user's active game - OLD FRONTEND FORMAT"""
    # This would require adding a method to game_manager
    # For now, return a placeholder
    return {"hasActiveGame": False}

# --- WebSocket Endpoint (Keep as before) ---
active_connections = {}

@app.websocket("/ws/game/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, token: Optional[str] = None):
    await websocket.accept()
    
    user = None
    if token:
        user = auth_manager.validate_token(token)
    
    if game_id not in active_connections:
        active_connections[game_id] = []
    
    active_connections[game_id].append((websocket, user))
    
    try:
        while True:
            data = await websocket.receive_text()
            # Handle messages here
            
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        if game_id in active_connections:
            active_connections[game_id] = [
                (conn, u) for conn, u in active_connections[game_id]
                if conn != websocket
            ]

# --- Root Endpoint ---
@app.get("/")
async def root():
    return {
        "message": "Tonk Game API",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/api/health",
            "warmup": "/api/warmup",
            "status": "/api/status",
            "ping": "/api/ping"
        },
        "timestamp": datetime.now().isoformat()
    }

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)