# game_manager.py - SIMPLIFIED
import uuid
import json
import random
from datetime import datetime
from typing import Optional, List, Dict
from database import db  # Import shared DB instance

class GameManager:
    def __init__(self):
        # Database will auto-initialize
        pass
    
    def _ensure_db(self):
        """Ensure database is ready"""
        db.ensure_tables_exist()
    
    def create_deck(self) -> List[Dict]:
        """Create a standard 52-card deck"""
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
                    "recentlyDrawn": False,
                    "image": f"card_{rank}{suit_symbol}".lower(),
                    "backImage": "card_back",
                    "suitSymbol": suit_symbol,
                    "color": "red" if suit in ["hearts", "diamonds"] else "black"
                })
        
        random.shuffle(deck)
        return deck
    
    def create_game(self, players: List[Dict], game_name: Optional[str] = None, creator_id: Optional[str] = None) -> Dict:
        """Create a new game - SIMPLIFIED"""
        self._ensure_db()
        
        game_id = str(uuid.uuid4())
        room_code = game_id[:6].upper()
        deck = self.create_deck()
        created_at = datetime.now().isoformat()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Save game
            cursor.execute('''
                INSERT INTO games (id, room_code, game_name, deck, creator_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (game_id, room_code, game_name, json.dumps(deck), creator_id, created_at))
            
            # Create and save players
            player_ids = []
            for i, player_data in enumerate(players):
                player_id = str(uuid.uuid4())
                player_user_id = creator_id if i == 0 else None
                
                # Generate guest ID for human players
                if not player_data.get("is_computer", False) and not player_user_id:
                    player_user_id = f"guest_{str(uuid.uuid4())[:8]}"
                
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
                    player_ids.append(player_id)
            
            conn.commit()
            conn.close()
            
            return {
                "game_id": game_id,
                "room_code": room_code,
                "player_id": player_ids[0] if player_ids else None
            }
            
        except Exception as e:
            conn.close()
            raise e
    
    def get_game(self, game_id: str) -> Optional[Dict]:
        """Get game by ID"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
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
            
            # Parse game
            game = dict(game_row)
            game["deck"] = json.loads(game["deck"]) if game["deck"] else []
            game["discard_pile"] = json.loads(game["discard_pile"]) if game["discard_pile"] else []
            game["under_card"] = json.loads(game["under_card"]) if game["under_card"] else None
            game["table_spreads"] = json.loads(game["table_spreads"]) if game["table_spreads"] else []
            game["last_move"] = json.loads(game["last_move"]) if game["last_move"] else None
            game["settings"] = json.loads(game["settings"]) if game["settings"] else {}
            
            # Parse players
            players = []
            for row in player_rows:
                player = dict(row)
                player["hand"] = json.loads(player["hand"]) if player["hand"] else []
                player["spreads"] = json.loads(player["spreads"]) if player["spreads"] else []
                player["is_computer"] = bool(player["is_computer"])
                player["has_dropped"] = bool(player["has_dropped"])
                player["has_drawn_from_under"] = bool(player["has_drawn_from_under"])
                player["is_online"] = bool(player["is_online"])
                players.append(player)
            
            game["players"] = players
            return game
            
        except Exception as e:
            conn.close()
            raise e