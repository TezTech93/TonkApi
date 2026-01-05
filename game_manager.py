# game_manager.py
import sqlite3
import uuid
import json
import random
from datetime import datetime
from typing import Optional, List, Dict, Any

class GameManager:
    def __init__(self, db_path: str = "tonk_game.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize game tables only"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Games table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            room_code TEXT UNIQUE NOT NULL,
            game_name TEXT,
            deck TEXT,  -- JSON serialized
            discard_pile TEXT,  -- JSON serialized
            under_card TEXT,  -- JSON serialized
            current_player_index INTEGER DEFAULT 0,
            turn_phase TEXT DEFAULT 'waiting',
            table_spreads TEXT,  -- JSON serialized
            turn_count INTEGER DEFAULT 0,
            game_status TEXT DEFAULT 'lobby',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_move TEXT,  -- JSON serialized
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
            hand TEXT DEFAULT '[]',  -- JSON serialized
            spreads TEXT DEFAULT '[]',  -- JSON serialized
            has_dropped BOOLEAN DEFAULT 0,
            score INTEGER DEFAULT 0,
            last_move TEXT,
            turns INTEGER DEFAULT 0,
            has_drawn_from_under BOOLEAN DEFAULT 0,
            is_online BOOLEAN DEFAULT 1,
            position INTEGER
        )
        ''')
        
        # Active games lookup
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_games (
            user_id TEXT PRIMARY KEY,
            game_id TEXT NOT NULL
        )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Game database initialized")
    
    def get_db_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # Card utilities
    def create_deck(self) -> List[Dict]:
        """Create a standard 52-card deck"""
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
        
        random.shuffle(deck)
        return deck
    
    # Game CRUD operations
    def create_game(self, players: List[Dict], game_name: Optional[str] = None, creator_id: Optional[str] = None) -> Dict:
        """Create a new game"""
        game_id = str(uuid.uuid4())
        room_code = game_id[:6].upper()
        
        # Create deck
        deck = self.create_deck()
        
        # Create game players
        game_players = []
        for i, player_data in enumerate(players):
            player = {
                "id": str(uuid.uuid4()),
                "user_id": creator_id if i == 0 else None,
                "name": player_data["name"],
                "is_computer": player_data.get("is_computer", False),
                "hand": [],  # Empty in lobby
                "spreads": [],
                "position": i
            }
            game_players.append(player)
        
        # Create game object
        game = {
            "id": game_id,
            "room_code": room_code,
            "game_name": game_name,
            "deck": json.dumps(deck),
            "discard_pile": json.dumps([]),
            "under_card": json.dumps(None),
            "current_player_index": 0,
            "turn_phase": "waiting",
            "table_spreads": json.dumps([]),
            "turn_count": 0,
            "game_status": "lobby",
            "created_at": datetime.now().isoformat(),
            "last_move": json.dumps(None),
            "settings": json.dumps({"allow_under_card_any_turn": True}),
            "winner": None,
            "win_reason": None,
            "creator_id": creator_id,
            "max_players": 4
        }
        
        # Save to database
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        # Save game
        cursor.execute('''
            INSERT INTO games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            game["id"], game["room_code"], game["game_name"], game["deck"], 
            game["discard_pile"], game["under_card"], game["current_player_index"],
            game["turn_phase"], game["table_spreads"], game["turn_count"],
            game["game_status"], game["created_at"], game["last_move"],
            game["settings"], game["winner"], game["win_reason"],
            game["creator_id"], game["max_players"]
        ))
        
        # Save players
        for player in game_players:
            cursor.execute('''
                INSERT INTO game_players 
                (id, game_id, user_id, name, is_computer, hand, spreads, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                player["id"], game_id, player["user_id"], player["name"],
                player["is_computer"], json.dumps(player["hand"]), 
                json.dumps(player["spreads"]), player["position"]
            ))
        
        # Track active game for creator
        if creator_id:
            cursor.execute('''
                INSERT OR REPLACE INTO active_games (user_id, game_id)
                VALUES (?, ?)
            ''', (creator_id, game_id))
        
        conn.commit()
        conn.close()
        
        return {
            "game_id": game_id,
            "room_code": room_code,
            "player_id": game_players[0]["id"] if game_players else None
        }
    
    def get_game(self, game_id: str) -> Optional[Dict]:
        """Get game by ID"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        # Get game
        cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        game_row = cursor.fetchone()
        
        if not game_row:
            conn.close()
            return None
        
        # Get players
        cursor.execute(
            "SELECT * FROM game_players WHERE game_id = ? ORDER BY position",
            (game_id,)
        )
        player_rows = cursor.fetchall()
        
        conn.close()
        
        # Parse JSON fields
        game = dict(game_row)
        game["deck"] = json.loads(game["deck"]) if game["deck"] else []
        game["discard_pile"] = json.loads(game["discard_pile"]) if game["discard_pile"] else []
        game["under_card"] = json.loads(game["under_card"]) if game["under_card"] else None
        game["table_spreads"] = json.loads(game["table_spreads"]) if game["table_spreads"] else []
        game["last_move"] = json.loads(game["last_move"]) if game["last_move"] else None
        game["settings"] = json.loads(game["settings"]) if game["settings"] else {}
        
        # Parse player JSON fields
        players = []
        for row in player_rows:
            player = dict(row)
            player["hand"] = json.loads(player["hand"]) if player["hand"] else []
            player["spreads"] = json.loads(player["spreads"]) if player["spreads"] else []
            players.append(player)
        
        game["players"] = players
        return game
    
    def get_game_by_room_code(self, room_code: str) -> Optional[Dict]:
        """Get game by room code"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM games WHERE room_code = ?", (room_code,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self.get_game(row["id"])
        return None
    
    def join_game(self, room_code: str, player_name: str, user_id: Optional[str] = None) -> Dict:
        """Join an existing game"""
        game = self.get_game_by_room_code(room_code)
        if not game:
            raise ValueError("Game not found")
        
        if game["game_status"] != "lobby":
            raise ValueError("Game already started")
        
        if len(game["players"]) >= game["max_players"]:
            raise ValueError("Game is full")
        
        # Check if user already in game
        if user_id and any(p["user_id"] == user_id for p in game["players"]):
            raise ValueError("You are already in this game")
        
        # Create new player
        player_id = str(uuid.uuid4())
        position = len(game["players"])
        
        new_player = {
            "id": player_id,
            "game_id": game["id"],
            "user_id": user_id,
            "name": player_name,
            "is_computer": False,
            "hand": [],
            "spreads": [],
            "position": position
        }
        
        # Save player to database
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO game_players 
            (id, game_id, user_id, name, is_computer, hand, spreads, position)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            player_id, game["id"], user_id, player_name, 
            False, json.dumps([]), json.dumps([]), position
        ))
        
        # Track active game for user
        if user_id:
            cursor.execute('''
                INSERT OR REPLACE INTO active_games (user_id, game_id)
                VALUES (?, ?)
            ''', (user_id, game["id"]))
        
        conn.commit()
        conn.close()
        
        # Update game players list
        game["players"].append(new_player)
        
        return {
            "game_id": game["id"],
            "player_id": player_id
        }
    
    def start_game(self, game_id: str) -> Dict:
        """Start a game"""
        game = self.get_game(game_id)
        if not game:
            raise ValueError("Game not found")
        
        if len(game["players"]) < 2:
            raise ValueError("Need at least 2 players")
        
        if game["game_status"] != "lobby":
            raise ValueError("Game already started")
        
        # Reset hands
        for player in game["players"]:
            player["hand"] = []
        
        # Deal 5 cards to each player
        for player in game["players"]:
            for _ in range(5):
                if game["deck"]:
                    card = game["deck"].pop()
                    card["isFaceUp"] = True
                    player["hand"].append(card)
        
        # Setup discard pile
        if game["deck"]:
            first_card = game["deck"].pop()
            first_card["isFaceUp"] = True
            game["discard_pile"] = [first_card]
        
        # Setup under card
        game["under_card"] = game["deck"].pop() if game["deck"] else None
        
        # Update game state
        game["game_status"] = "playing"
        game["turn_phase"] = "draw"
        game["turn_count"] = 1
        
        # Save updated game
        self.save_game(game)
        
        return {
            "success": True,
            "game_id": game_id
        }
    
    # In game_manager.py, update save_game method:
    def save_game(self, game: Dict):
      """Save game to database"""
      conn = self.get_db_connection()
      cursor = conn.cursor()
      
      # Update game
      cursor.execute('''
          UPDATE games SET
              deck = ?, discard_pile = ?, under_card = ?,
              current_player_index = ?, turn_phase = ?, table_spreads = ?,
              turn_count = ?, game_status = ?, last_move = ?, settings = ?,
              winner = ?, win_reason = ?
          WHERE id = ?
      ''', (
          json.dumps(game.get("deck", [])), 
          json.dumps(game.get("discard_pile", [])),
          json.dumps(game.get("under_card")),
          game.get("current_player_index", 0),
          game.get("turn_phase", "waiting"),
          json.dumps(game.get("table_spreads", [])),
          game.get("turn_count", 0),
          game.get("game_status", "lobby"),
          json.dumps(game.get("last_move")),
          json.dumps(game.get("settings", {})),
          game.get("winner"),
          game.get("win_reason"),
          game["id"]
      ))
      
      # Update players
      for player in game.get("players", []):
          cursor.execute('''
              UPDATE game_players SET
                  hand = ?, spreads = ?, has_dropped = ?, score = ?,
                  last_move = ?, turns = ?, has_drawn_from_under = ?,
                  is_online = ?
              WHERE id = ?
          ''', (
              json.dumps(player.get("hand", [])),
              json.dumps(player.get("spreads", [])),
              player.get("has_dropped", False),
              player.get("score", 0),
              player.get("last_move"),
              player.get("turns", 0),
              player.get("has_drawn_from_under", False),
              player.get("is_online", True),
              player["id"]
          ))
      
      conn.commit()
      conn.close()
      
    def get_available_games(self) -> List[Dict]:
        """Get all available games"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT g.*, COUNT(p.id) as player_count
            FROM games g
            LEFT JOIN game_players p ON g.id = p.game_id
            WHERE g.game_status = 'lobby'
            GROUP BY g.id
            HAVING player_count < g.max_players
        ''')
        
        games = []
        for row in cursor.fetchall():
            games.append({
                "gameId": row["id"],
                "roomCode": row["room_code"],
                "gameName": row["game_name"],
                "currentPlayers": row["player_count"],
                "maxPlayers": row["max_players"],
                "creator": row["creator_id"],
                "createdAt": row["created_at"]
            })
        
        conn.close()
        return gam