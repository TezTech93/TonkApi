from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Optional
import uuid
import json
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import asyncio
from enum import Enum
import random
from passlib.context import CryptContext
from jose import JWTError, jwt

# Security configuration
SECRET_KEY = "your-secret-key-here-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="Tonk Game API")

# CORS middleware - Enhanced for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Authentication Models ---
class UserRegister(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class User(BaseModel):
    id: str
    username: str
    email: str
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.now)
    games_played: int = 0
    games_won: int = 0
    online: bool = False
    last_seen: Optional[datetime] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    username: str

class TokenData(BaseModel):
    username: Optional[str] = None

# --- Request Models for API endpoints ---
class CreateGameRequest(BaseModel):
    players: List[Dict]
    game_name: Optional[str] = None
    userId: Optional[str] = None  # Changed to match frontend

class JoinGameRequest(BaseModel):
    playerName: str
    userId: Optional[str] = None  # Changed to match frontend

class MoveRequest(BaseModel):
    playerId: str
    moveType: str
    moveData: Dict

# --- Game Models ---
class MoveType(str, Enum):
    DRAW = "draw"
    DISCARD = "discard"
    CREATE_SPREAD = "createSpread"
    ADD_TO_SPREAD = "addToSpread"
    TONK = "tonk"
    DROP = "drop"
    HIT = "hit"
    START_GAME = "startGame"

class Player(BaseModel):
    id: str
    user_id: Optional[str] = None
    name: str
    is_computer: bool = False
    hand: List[Dict] = []
    spreads: List[Dict] = []
    has_dropped: bool = False
    score: int = 0
    last_move: Optional[str] = None
    turns: int = 0
    has_drawn_from_under: bool = False
    is_online: bool = True

class Game(BaseModel):
    id: str
    room_code: str
    game_name: Optional[str] = None
    players: List[Player]
    deck: List[Dict]
    discard_pile: List[Dict]
    under_card: Optional[Dict] = None
    current_player_index: int = 0
    turn_phase: str = "draw"
    table_spreads: List[Dict] = []
    turn_count: int = 1
    game_status: str = "playing"
    created_at: datetime = Field(default_factory=datetime.now)
    last_move: Optional[Dict] = None
    settings: Dict = {"allow_under_card_any_turn": True}
    winner: Optional[str] = None
    win_reason: Optional[str] = None
    creator_id: Optional[str] = None
    max_players: int = 4

# Data storage
users: Dict[str, User] = {}
games: Dict[str, Game] = {}
connections: Dict[str, List[WebSocket]] = {}
player_connections: Dict[str, WebSocket] = {}
user_connections: Dict[str, WebSocket] = {}
active_games_by_user: Dict[str, str] = {}  # user_id -> game_id

# --- Authentication Functions ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def get_user_by_username(username: str):
    for user in users.values():
        if user.username == username:
            return user
    return None

def get_user_by_email(email: str):
    for user in users.values():
        if user.email == email:
            return user
    return None

def authenticate_user(username: str, password: str):
    user = get_user_by_username(username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# NEW: Simple authorization header dependency
async def get_current_user(authorization: Optional[str] = Header(None)):
    """Get current user from Authorization header"""
    if not authorization:
        # Allow guest users for game creation
        return None
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    token = authorization.split(" ")[1]
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            return None
        
        user = get_user_by_username(username)
        if not user:
            return None
            
        return user
    except JWTError:
        # Invalid token - treat as guest
        return None

# --- Authentication Endpoints ---
@app.post("/api/auth/register", response_model=Token)
async def register(user_data: UserRegister):
    # Check if username already exists
    if get_user_by_username(user_data.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Check if email already exists
    if get_user_by_email(user_data.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create new user
    user_id = str(uuid.uuid4())
    hashed_password = get_password_hash(user_data.password)
    
    user = User(
        id=user_id,
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_password
    )
    
    users[user_id] = user
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_data.username}, expires_delta=access_token_expires
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        user_id=user_id,
        username=user_data.username
    )

@app.post("/api/auth/login", response_model=Token)
async def login(user_data: UserLogin):
    user = authenticate_user(user_data.username, user_data.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update user status
    user.online = True
    user.last_seen = datetime.now()
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        username=user.username
    )

@app.get("/api/auth/profile")
async def get_user_profile(current_user: Optional[User] = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return {
        "id": current_user.id,
        "username": current_user.username,
        "games_played": current_user.games_played,
        "games_won": current_user.games_won,
        "online": current_user.online,
        "last_seen": current_user.last_seen.isoformat() if current_user.last_seen else None
    }

@app.get("/api/auth/online-users")
async def get_online_users():
    online_users = []
    for user in users.values():
        if user.online:
            online_users.append({
                "id": user.id,
                "username": user.username,
                "last_seen": user.last_seen.isoformat() if user.last_seen else None
            })
    return {"online_users": online_users}

@app.get("/api/auth/validate-token")
async def validate_token(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return {"valid": False}
    
    token = authorization.split(" ")[1]
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            return {"valid": False}
        
        user = get_user_by_username(username)
        if not user:
            return {"valid": False}
        
        return {
            "valid": True,
            "user_id": user.id,
            "username": user.username
        }
    except JWTError:
        return {"valid": False}

# --- Game Endpoints ---
@app.post("/api/game/create")
async def create_game(request: CreateGameRequest, current_user: Optional[User] = Depends(get_current_user)):
    """Create a new game - supports both authenticated and guest users"""
    game_id = str(uuid.uuid4())
    room_code = game_id[:6].upper()
    
    # Create game players
    game_players = []
    for i, player_data in enumerate(request.players):
        player_name = player_data["name"]
        user_id = None
        
        # First player gets the authenticated user or guest ID
        if i == 0:
            if current_user:
                player_name = current_user.username
                user_id = current_user.id
            elif request.userId:
                user_id = request.userId  # Guest user ID from frontend
        
        player = Player(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=player_name,
            is_computer=player_data.get("is_computer", False)
        )
        game_players.append(player)
    
    # Initialize deck
    suits = ["hearts", "diamonds", "clubs", "spades"]
    ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    deck = []
    
    for suit in suits:
        for rank in ranks:
            value = 10 if rank in ["J", "Q", "K"] else 1 if rank == "A" else int(rank)
            deck.append({
                "id": str(uuid.uuid4()),
                "suit": suit,
                "rank": rank,
                "value": value,
                "isFaceUp": False,
                "recentlyDrawn": False
            })
    
    # Shuffle deck
    random.shuffle(deck)
    
    # Create game in lobby state
    creator_id = current_user.id if current_user else request.userId
    game = Game(
        id=game_id,
        room_code=room_code,
        game_name=request.game_name,
        players=game_players,
        deck=deck,
        discard_pile=[],
        under_card=None,
        game_status="lobby",
        creator_id=creator_id
    )
    
    games[game_id] = game
    connections[game_id] = []
    
    # Track active game for user
    if creator_id:
        active_games_by_user[creator_id] = game_id
    
    return {
        "success": True,
        "gameId": game_id,
        "roomCode": room_code,
        "playerId": game_players[0].id,
        "players": [p.model_dump() for p in game_players],
        "gameName": game.game_name
    }

@app.post("/api/game/{room_code}/join")
async def join_game(room_code: str, request: JoinGameRequest, current_user: Optional[User] = Depends(get_current_user)):
    """Join an existing game - supports both authenticated and guest users"""
    # Find game by room code
    game = next((g for g in games.values() if g.room_code == room_code), None)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    if game.game_status != "lobby":
        raise HTTPException(status_code=400, detail="Game already started")
    
    if len(game.players) >= game.max_players:
        raise HTTPException(status_code=400, detail="Game is full")
    
    # Determine user ID
    user_id = current_user.id if current_user else request.userId
    
    # Check if user is already in the game
    if user_id and any(p.user_id == user_id for p in game.players):
        raise HTTPException(status_code=400, detail="You are already in this game")
    
    # Create new player
    player = Player(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=request.playerName,
        is_computer=False
    )
    
    game.players.append(player)
    
    # Track active game for user
    if user_id:
        active_games_by_user[user_id] = game.id
    
    # Broadcast update
    await broadcast_game_state(game.id)
    
    return {
        "success": True,
        "gameId": game.id,
        "playerId": player.id,
        "gameState": game.model_dump()
    }

@app.get("/api/game/available")
async def get_available_games():
    """Get list of available games - no auth required"""
    available_games = []
    for game in games.values():
        if game.game_status == "lobby" and len(game.players) < game.max_players:
            available_games.append({
                "gameId": game.id,
                "roomCode": game.room_code,
                "gameName": game.game_name,
                "players": [p.model_dump() for p in game.players],
                "currentPlayers": len(game.players),
                "maxPlayers": game.max_players,
                "creator": game.creator_id,
                "createdAt": game.created_at.isoformat()
            })
    return {"available_games": available_games}

@app.get("/api/game/user/{user_id}/active")
async def get_user_active_game(user_id: str):
    if user_id in active_games_by_user:
        game_id = active_games_by_user[user_id]
        if game_id in games:
            game = games[game_id]
            player_index = next((i for i, p in enumerate(game.players) if p.user_id == user_id), -1)
            return {
                "hasActiveGame": True,
                "gameId": game_id,
                "roomCode": game.room_code,
                "playerId": game.players[player_index].id if player_index != -1 else None,
                "gameStatus": game.game_status
            }
    
    return {"hasActiveGame": False}

@app.post("/api/game/{game_id}/start")
async def start_game(game_id: str, current_user: Optional[User] = Depends(get_current_user)):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    
    game = games[game_id]
    
    # Check if user can start the game (creator or any player if no creator)
    if game.creator_id and current_user and game.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the game creator can start the game")
    
    if len(game.players) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 players")
    
    if game.game_status != "lobby":
        raise HTTPException(status_code=400, detail="Game already started")
    
    # Deal 5 cards to each player
    for player in game.players:
        for _ in range(5):
            if game.deck:
                card = game.deck.pop()
                card["isFaceUp"] = True
                player.hand.append(card)
    
    # Setup discard pile and under card
    if game.deck:
        first_card = game.deck.pop()
        first_card["isFaceUp"] = True
        game.discard_pile.append(first_card)
    
    game.under_card = game.deck.pop() if game.deck else None
    if game.under_card:
        game.under_card["isFaceUp"] = True
    
    game.game_status = "playing"
    game.current_player_index = 0
    game.turn_phase = "draw"
    game.turn_count = 1
    
    # Broadcast game start
    await broadcast_game_state(game_id)
    
    return {
        "success": True,
        "gameState": game.model_dump(),
    }

@app.post("/api/game/{game_id}/move")
async def make_move(game_id: str, request: MoveRequest, current_user: Optional[User] = Depends(get_current_user)):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    
    game = games[game_id]
    player_index = next((i for i, p in enumerate(game.players) if p.id == request.playerId), -1)
    
    if player_index == -1:
        raise HTTPException(status_code=404, detail="Player not found")
    
    # Check if it's the player's turn
    if game.current_player_index != player_index:
        raise HTTPException(status_code=400, detail="Not your turn")
    
    player = game.players[player_index]
    
    # Verify the user owns this player (if authenticated)
    if current_user and player.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You don't own this player")
    
    # Process move
    move_result = process_move(game, player_index, request.moveType, request.moveData)
    
    # Update last move
    game.last_move = {
        "playerId": request.playerId,
        "playerName": player.name,
        "moveType": request.moveType,
        "moveData": request.moveData,
        "timestamp": datetime.now().isoformat()
    }
    
    # Check for game over
    if move_result.get("game_over"):
        game.game_status = "game_over"
        game.winner = move_result.get("winner")
        game.win_reason = move_result.get("win_reason")
        
        # Update user stats for all players
        for p in game.players:
            if p.user_id and p.user_id in users:
                user = users[p.user_id]
                user.games_played += 1
                if p.id == game.winner:
                    user.games_won += 1
    
    # Broadcast update
    await broadcast_game_state(game_id)
    
    return {
        "success": True,
        "gameState": game.model_dump(),
        "lastMove": game.last_move
    }

@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str):
    """Get game state - no auth required for public viewing"""
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    
    game = games[game_id]
    
    # Enhance player info with user data
    enhanced_players = []
    for player in game.players:
        player_data = player.model_dump()
        if player.user_id and player.user_id in users:
            user = users[player.user_id]
            player_data["user"] = {
                "username": user.username,
                "games_played": user.games_played,
                "games_won": user.games_won,
                "online": user.online
            }
        enhanced_players.append(player_data)
    
    game_state = game.model_dump()
    game_state["players"] = enhanced_players
    
    return {
        "success": True,
        "gameState": game_state,
        "lastMove": game.last_move
    }

@app.get("/api/game/{game_id}/lobby")
async def get_lobby_state(game_id: str):
    """Get lobby state - no auth required"""
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    
    game = games[game_id]
    
    # Enhance player info with user data
    enhanced_players = []
    for player in game.players:
        player_data = player.model_dump()
        if player.user_id and player.user_id in users:
            user = users[player.user_id]
            player_data["user"] = {
                "username": user.username,
                "online": user.online
            }
        enhanced_players.append(player_data)
    
    return {
        "success": True,
        "players": enhanced_players,
        "status": game.game_status,
        "roomCode": game.room_code,
        "gameName": game.game_name,
        "createdAt": game.created_at.isoformat(),
        "maxPlayers": game.max_players,
        "canStart": len(game.players) >= 2,
    }

@app.websocket("/ws/game/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, token: Optional[str] = None):
    await websocket.accept()
    
    user_id = None
    username = "Guest"
    
    # Authenticate user if token provided
    if token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            user = get_user_by_username(username)
            if user:
                user_id = user.id
                user.online = True
                user.last_seen = datetime.now()
                user_connections[user_id] = websocket
        except:
            pass
    
    if game_id not in connections:
        connections[game_id] = []
    
    connections[game_id].append(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message["type"] == "join":
                player_id = message["playerId"]
                player_connections[player_id] = websocket
                
                # Update player online status
                if game_id in games:
                    game = games[game_id]
                    for player in game.players:
                        if player.id == player_id and user_id:
                            player.user_id = user_id
                            player.is_online = True
                
                # Broadcast updated game state
                await broadcast_game_state(game_id)
                
            elif message["type"] == "chat":
                # Broadcast chat message
                await broadcast_message(game_id, {
                    "type": "chat",
                    "player": username,
                    "message": message["message"],
                    "timestamp": datetime.now().isoformat()
                })
                
            elif message["type"] == "ping":
                # Keep connection alive and update user status
                if user_id and user_id in users:
                    users[user_id].last_seen = datetime.now()
                await websocket.send_text(json.dumps({"type": "pong"}))
                
    except WebSocketDisconnect:
        if game_id in connections:
            if websocket in connections[game_id]:
                connections[game_id].remove(websocket)
        
        # Remove player connection
        player_id = next((pid for pid, ws in player_connections.items() if ws == websocket), None)
        if player_id:
            del player_connections[player_id]
            
            # Update player offline status
            if game_id in games:
                game = games[game_id]
                for player in game.players:
                    if player.id == player_id:
                        player.is_online = False
                await broadcast_game_state(game_id)
        
        # Remove user connection
        if user_id and user_id in user_connections:
            del user_connections[user_id]
            if user_id in users:
                users[user_id].online = False
                users[user_id].last_seen = datetime.now()

async def broadcast_game_state(game_id: str):
    if game_id in connections and game_id in games:
        game = games[game_id]
        
        # Enhance player info with user data
        enhanced_players = []
        for player in game.players:
            player_data = player.model_dump()
            if player.user_id and player.user_id in users:
                user = users[player.user_id]
                player_data["user"] = {
                    "username": user.username,
                    "games_played": user.games_played,
                    "games_won": user.games_won,
                    "online": user.online
                }
            enhanced_players.append(player_data)
        
        game_state = game.model_dump()
        game_state["players"] = enhanced_players
        
        message = json.dumps({
            "type": "state_update", 
            "gameState": game_state,
            "timestamp": datetime.now().isoformat()
        })
        
        for connection in connections[game_id]:
            try:
                await connection.send_text(message)
            except:
                pass

async def broadcast_message(game_id: str, message: Dict):
    if game_id in connections:
        message_json = json.dumps(message)
        for connection in connections[game_id]:
            try:
                await connection.send_text(message_json)
            except:
                pass

def process_move(game: Game, player_index: int, move_type: str, move_data: Dict) -> Dict:
    """Process game move logic"""
    player = game.players[player_index]
    
    if move_type == MoveType.DRAW:
        source = move_data.get("source", "deck")
        
        if source == "deck" and game.deck:
            card = game.deck.pop()
            card["isFaceUp"] = True
            player.hand.append(card)
            player.last_move = f"Drew from deck"
            game.turn_phase = "action"
            
        elif source == "discard" and game.discard_pile:
            card = game.discard_pile.pop()
            card["isFaceUp"] = True
            player.hand.append(card)
            player.last_move = f"Drew from discard"
            game.turn_phase = "action"
            
        elif source == "under" and game.under_card:
            can_draw_under = game.settings.get("allow_under_card_any_turn", True) or player.turns > 0
            
            if can_draw_under:
                card = game.under_card
                card["isFaceUp"] = True
                game.under_card = None
                player.hand.append(card)
                player.has_drawn_from_under = True
                player.last_move = f"Drew under card"
                game.turn_phase = "action"
    
    elif move_type == MoveType.DISCARD:
        card_id = move_data.get("cardId")
        if card_id:
            card_index = next((i for i, c in enumerate(player.hand) if c["id"] == card_id), -1)
            if card_index != -1:
                card = player.hand.pop(card_index)
                card["isFaceUp"] = True
                game.discard_pile.append(card)
                player.last_move = f"Discarded {card['rank']} of {card['suit']}"
                
                # Check for Tonk Out (win condition)
                if len(player.hand) == 0:
                    return {
                        "game_over": True,
                        "winner": player.id,
                        "win_reason": "Tonk Out!"
                    }
                else:
                    # End turn
                    game.current_player_index = (game.current_player_index + 1) % len(game.players)
                    game.turn_count += 1
                    game.turn_phase = "draw"
                    next_player = game.players[game.current_player_index]
                    next_player.turns += 1
    
    elif move_type == MoveType.TONK:
        # Calculate hand value
        hand_value = sum(card["value"] for card in player.hand)
        if hand_value <= 5:
            return {
                "game_over": True,
                "winner": player.id,
                "win_reason": f"Tonk! (Hand value: {hand_value})"
            }
        else:
            # Penalty for false Tonk call
            player.score += 10  # Add penalty points
            game.current_player_index = (game.current_player_index + 1) % len(game.players)
            game.turn_phase = "draw"
    
    elif move_type == MoveType.DROP:
        player.has_dropped = True
        player.last_move = "Dropped out"
        # Calculate score for dropped player
        player.score = sum(card["value"] for card in player.hand)
        
        # Check if all but one player have dropped
        active_players = [p for p in game.players if not p.has_dropped]
        if len(active_players) == 1:
            return {
                "game_over": True,
                "winner": active_players[0].id,
                "win_reason": "All other players dropped"
            }
        else:
            # Move to next active player
            next_index = (player_index + 1) % len(game.players)
            while game.players[next_index].has_dropped:
                next_index = (next_index + 1) % len(game.players)
            game.current_player_index = next_index
            game.turn_phase = "draw"
    
    elif move_type == MoveType.CREATE_SPREAD:
        card_ids = move_data.get("cards", [])
        if len(card_ids) >= 3:  # Minimum 3 cards for a spread
            spread_cards = []
            for card_id in card_ids:
                card_index = next((i for i, c in enumerate(player.hand) if c["id"] == card_id), -1)
                if card_index != -1:
                    spread_cards.append(player.hand.pop(card_index))
            
            if len(spread_cards) >= 3:
                spread = {
                    "id": str(uuid.uuid4()),
                    "cards": spread_cards,
                    "owner": player.id,
                    "type": "player"  # Can be "player" or "table"
                }
                player.spreads.append(spread)
                player.last_move = f"Created spread with {len(spread_cards)} cards"
    
    elif move_type == MoveType.ADD_TO_SPREAD:
        spread_id = move_data.get("spreadId")
        card_id = move_data.get("cardId")
        
        if spread_id and card_id:
            # Find the card in player's hand
            card_index = next((i for i, c in enumerate(player.hand) if c["id"] == card_id), -1)
            if card_index != -1:
                card = player.hand.pop(card_index)
                
                # Try to find spread in player's spreads
                spread = None
                for s in player.spreads:
                    if s["id"] == spread_id:
                        spread = s
                        break
                
                # If not found in player's spreads, check table spreads
                if not spread:
                    for s in game.table_spreads:
                        if s["id"] == spread_id:
                            spread = s
                            break
                
                if spread:
                    spread["cards"].append(card)
                    player.last_move = f"Added card to spread"
    
    elif move_type == MoveType.HIT:
        spread_id = move_data.get("spreadId")
        card_id = move_data.get("cardId")
        
        if spread_id and card_id:
            # Find the card in player's hand
            card_index = next((i for i, c in enumerate(player.hand) if c["id"] == card_id), -1)
            if card_index != -1:
                card = player.hand.pop(card_index)
                
                # Find the spread on table
                spread_index = next((i for i, s in enumerate(game.table_spreads) if s["id"] == spread_id), -1)
                if spread_index != -1:
                    spread = game.table_spreads.pop(spread_index)
                    # Add all cards from spread to player's hand
                    player.hand.extend(spread["cards"])
                    # Add the hitting card to hand as well
                    player.hand.append(card)
                    player.last_move = f"Hit a spread and took {len(spread['cards'])} cards"
    
    return {"success": True}
    
@app.get("/api/game/room/{room_code}/id")
async def get_game_id_by_room_code(room_code: str):
    """Get game ID from room code"""
    game = next((g for g in games.values() if g.room_code == room_code), None)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    return {
        "success": True,
        "gameId": game.id,
        "roomCode": game.room_code,
        "status": game.game_status
    }

@app.get("/api/game/room/{room_code}/state")
async def get_game_state_by_room_code(room_code: str):
    """Get game state using room code"""
    game = next((g for g in games.values() if g.room_code == room_code), None)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    # Enhance player info with user data
    enhanced_players = []
    for player in game.players:
        player_data = player.model_dump()
        if player.user_id and player.user_id in users:
            user = users[player.user_id]
            player_data["user"] = {
                "username": user.username,
                "games_played": user.games_played,
                "games_won": user.games_won,
                "online": user.online
            }
        enhanced_players.append(player_data)
    
    game_state = game.model_dump()
    game_state["players"] = enhanced_players
    
    return {
        "success": True,
        "gameState": game_state,
        "lastMove": game.last_move
    }

@app.get("/")
async def root():
    return {"message": "Tonk Game API is running", "status": "ok", "docs": "/docs"}

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "games_count": len(games),
        "users_count": len(users),
        "connections_count": sum(len(conns) for conns in connections.values())
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)