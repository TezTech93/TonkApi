from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Optional
import uuid
import json
from datetime import datetime
from pydantic import BaseModel
import asyncio
from enum import Enum

app = FastAPI(title="Tonk Game API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
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
    name: str
    is_computer: bool = False
    hand: List[Dict] = []
    spreads: List[Dict] = []
    has_dropped: bool = False
    score: int = 0
    last_move: Optional[str] = None
    turns: int = 0
    has_drawn_from_under: bool = False

class Game(BaseModel):
    id: str
    room_code: str
    players: List[Player]
    deck: List[Dict]
    discard_pile: List[Dict]
    under_card: Optional[Dict]
    current_player_index: int = 0
    turn_phase: str = "draw"
    table_spreads: List[Dict] = []
    turn_count: int = 1
    game_status: str = "playing"
    created_at: datetime = datetime.now()
    last_move: Optional[Dict] = None
    settings: Dict = {"allow_under_card_any_turn": True}

# Data storage
games: Dict[str, Game] = {}
connections: Dict[str, List[WebSocket]] = {}
player_connections: Dict[str, WebSocket] = {}

@app.post("/api/game/create")
async def create_game(players: List[Dict]):
    game_id = str(uuid.uuid4())
    room_code = game_id[:4].upper()
    
    # Create game players
    game_players = []
    for i, player_data in enumerate(players):
        player = Player(
            id=str(uuid.uuid4()),
            name=player_data["name"],
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
    import random
    random.shuffle(deck)
    
    # Create game in lobby state (no cards dealt yet)
    game = Game(
        id=game_id,
        room_code=room_code,
        players=game_players,
        deck=deck,  # Full deck, not dealt yet
        discard_pile=[],
        under_card=None,
        game_status="lobby"
    )
    
    games[game_id] = game
    connections[game_id] = []
    
    return {
        "gameId": game_id,
        "roomCode": room_code,
        "playerId": game_players[0].id,
        "players": [p.dict() for p in game_players]
    }

@app.post("/api/game/{room_code}/join")
async def join_game(room_code: str, player_name: str):
    # Find game by room code
    game = next((g for g in games.values() if g.room_code == room_code), None)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    if game.game_status != "lobby":
        raise HTTPException(status_code=400, detail="Game already started")
    
    if len(game.players) >= 4:
        raise HTTPException(status_code=400, detail="Game is full")
    
    # Create new player
    player = Player(
        id=str(uuid.uuid4()),
        name=player_name,
        is_computer=False
    )
    
    game.players.append(player)
    
    # Broadcast update
    await broadcast_game_state(game.id)
    
    return {
        "gameId": game.id,
        "playerId": player.id,
        "gameState": game.dict()
    }

@app.post("/api/game/{game_id}/start")
async def start_game(game_id: str):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    
    game = games[game_id]
    
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
        "gameState": game.dict(),
    }

@app.post("/api/game/{game_id}/move")
async def make_move(game_id: str, player_id: str, move_type: MoveType, move_data: Dict):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    
    game = games[game_id]
    player_index = next((i for i, p in enumerate(game.players) if p.id == player_id), -1)
    
    if player_index == -1:
        raise HTTPException(status_code=404, detail="Player not found")
    
    if game.current_player_index != player_index:
        raise HTTPException(status_code=400, detail="Not your turn")
    
    player = game.players[player_index]
    
    # Process move
    move_result = process_move(game, player_index, move_type, move_data)
    
    # Update last move
    game.last_move = {
        "playerId": player_id,
        "playerName": player.name,
        "moveType": move_type,
        "moveData": move_data,
        "timestamp": datetime.now().isoformat()
    }
    
    # Check for game over
    if move_result.get("game_over"):
        game.game_status = "game_over"
        game.winner = move_result.get("winner")
        game.win_reason = move_result.get("win_reason")
    
    # Broadcast update
    await broadcast_game_state(game_id)
    
    return {
        "success": True,
        "gameState": game.dict(),
        "lastMove": game.last_move
    }

@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    
    return {
        "gameState": games[game_id].dict(),
        "lastMove": games[game_id].last_move
    }

@app.get("/api/game/{game_id}/lobby")
async def get_lobby_state(game_id: str):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    
    game = games[game_id]
    
    return {
        "players": [p.dict() for p in game.players],
        "status": game.game_status,
        "roomCode": game.room_code,
        "createdAt": game.created_at.isoformat(),
        "maxPlayers": 4,
        "canStart": len(game.players) >= 2,
    }

@app.post("/api/game/restart")
async def restart_game(old_game_id: str, players: List[Dict]):
    if old_game_id not in games:
        raise HTTPException(status_code=404, detail="Original game not found")
    
    # Create new game
    game_id = str(uuid.uuid4())
    room_code = game_id[:4].upper()
    
    # Create game players
    game_players = []
    for player_data in players:
        player = Player(
            id=str(uuid.uuid4()),
            name=player_data["name"],
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
    import random
    random.shuffle(deck)
    
    # Deal 5 cards to each player
    for player in game_players:
        for _ in range(5):
            if deck:
                card = deck.pop()
                card["isFaceUp"] = True
                player.hand.append(card)
    
    # Setup discard pile and under card
    discard_pile = []
    if deck:
        first_card = deck.pop()
        first_card["isFaceUp"] = True
        discard_pile.append(first_card)
    
    under_card = deck.pop() if deck else None
    if under_card:
        under_card["isFaceUp"] = True
    
    # Create game
    game = Game(
        id=game_id,
        room_code=room_code,
        players=game_players,
        deck=deck,
        discard_pile=discard_pile,
        under_card=under_card
    )
    
    games[game_id] = game
    connections[game_id] = []
    
    return {
        "gameId": game_id,
        "roomCode": room_code,
        "gameState": game.dict()
    }

@app.websocket("/ws/game/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str):
    await websocket.accept()
    
    if game_id not in connections:
        connections[game_id] = []
    
    connections[game_id].append(websocket)
    
    try:
        while True:
            # Receive and broadcast messages
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message["type"] == "join":
                player_id = message["playerId"]
                player_connections[player_id] = websocket
                
            elif message["type"] == "chat":
                # Broadcast chat message
                await broadcast_message(game_id, {
                    "type": "chat",
                    "player": message["player"],
                    "message": message["message"],
                    "timestamp": datetime.now().isoformat()
                })
                
            elif message["type"] == "move":
                # Forward move to API
                await make_move(
                    game_id, 
                    message["playerId"], 
                    message["moveType"], 
                    message["moveData"]
                )
    
    except WebSocketDisconnect:
        if game_id in connections:
            connections[game_id].remove(websocket)
        
        # Remove player connection
        player_id = next((pid for pid, ws in player_connections.items() if ws == websocket), None)
        if player_id:
            del player_connections[player_id]

async def broadcast_game_state(game_id: str):
    if game_id in connections:
        game_state = games[game_id].dict()
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

def process_move(game: Game, player_index: int, move_type: MoveType, move_data: Dict) -> Dict:
    """Process game move logic - this would contain the full game rules"""
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
            # Feature #3: Check if player can draw under card
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
            # Find and remove card from hand
            card_index = next((i for i, c in enumerate(player.hand) if c["id"] == card_id), -1)
            if card_index != -1:
                card = player.hand.pop(card_index)
                card["isFaceUp"] = True
                game.discard_pile.append(card)
                player.last_move = f"Discarded {card['rank']} of {card['suit']}"
                
                # Check for Tonk Out
                if len(player.hand) == 0:
                    return {
                        "game_over": True,
                        "winner": player,
                        "win_reason": "Tonk Out!"
                    }
                else:
                    # End turn
                    game.current_player_index = (game.current_player_index + 1) % len(game.players)
                    game.turn_count += 1
                    game.turn_phase = "draw"
                    next_player = game.players[game.current_player_index]
                    next_player.turns += 1
    
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)