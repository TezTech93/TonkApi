# game_manager.py - UPDATED FOR NEW SYSTEM
import uuid
import json
import random
from datetime import datetime
from typing import Optional, List, Dict
from database import db

class GameManager:
    def __init__(self):
        pass
    
    def _ensure_db(self):
        """Ensure database is ready"""
        db.ensure_tables_exist()
    
    def create_deck(self) -> List[Dict]:
        """Create a standard 52-card deck"""
        suits = ["hearts", "diamonds", "clubs", "spades"]
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        deck = []
        
        for suit in suits:
            for rank in ranks:
                # Assign point values for Tonk
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
        
        random.shuffle(deck)
        return deck
    
    def deal_cards(self, deck: List[Dict], num_players: int):
        """Deal cards to players"""
        hands = [[] for _ in range(num_players)]
        
        # Deal 7 cards to each player (standard for Tonk)
        for i in range(7):
            for player_idx in range(num_players):
                if deck:
                    hands[player_idx].append(deck.pop())
        
        return deck, hands
    
    def create_game(self, players: List[Dict], game_name: Optional[str] = None, creator_id: Optional[str] = None) -> Dict:
        """Create a new game"""
        self._ensure_db()
        
        game_id = str(uuid.uuid4())
        room_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        created_at = datetime.now().isoformat()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Create game record
            cursor.execute('''
                INSERT INTO games (id, room_code, game_name, game_status, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (game_id, room_code, game_name, 'lobby', created_at))
            
            # Create players and game state
            player_ids = []
            game_players = []
            
            # Create initial deck
            deck = self.create_deck()
            
            # Deal cards
            remaining_deck, hands = self.deal_cards(deck, len(players))
            
            for i, player_data in enumerate(players):
                player_id = str(uuid.uuid4())
                player_ids.append(player_id)
                
                # Assign user_id: creator for first human player, or provided user_id
                user_id = None
                if i == 0 and creator_id and not player_data.get("is_computer", False):
                    user_id = creator_id
                elif player_data.get("user_id") and not player_data.get("is_computer", False):
                    user_id = player_data["user_id"]
                
                # Add to game_players table
                cursor.execute('''
                    INSERT INTO game_players (id, game_id, user_id, player_name, position, is_computer, is_host, is_ready)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    player_id, game_id, user_id, 
                    player_data["name"], 
                    i,
                    1 if player_data.get("is_computer", False) else 0,
                    1 if i == 0 else 0,  # First player is host
                    1 if not player_data.get("is_computer", False) else 0  # Human players start ready
                ))
                
                # Add to game state players list
                game_players.append({
                    'id': player_id,
                    'name': player_data["name"],
                    'user_id': user_id,
                    'hand': hands[i] if i < len(hands) else [],
                    'is_computer': bool(player_data.get("is_computer", False)),
                    'is_current_turn': i == 0,
                    'position': i,
                    'points': 0,
                    'is_ready': not player_data.get("is_computer", False)
                })
            
            # Create game state
            game_state = {
                'id': game_id,
                'room_code': room_code,
                'game_status': 'lobby',
                'turn_count': 0,
                'turn_phase': 'waiting',
                'deck': remaining_deck,
                'discard_pile': [],
                'players': game_players,
                'current_player_index': 0,
                'last_move': None,
                'created_at': created_at
            }
            
            # Save game state
            state_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO game_states (id, game_id, state_json)
                VALUES (?, ?, ?)
            ''', (state_id, game_id, json.dumps(game_state)))
            
            conn.commit()
            conn.close()
            
            return {
                "success": True,
                "game_id": game_id,
                "room_code": room_code,
                "player_id": player_ids[0] if player_ids else None,
                "game_state": game_state,
                "message": "Game created successfully"
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
            # Get game basic info
            cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
            game_row = cursor.fetchone()
            
            if not game_row:
                conn.close()
                return None
            
            # Get game state
            cursor.execute("SELECT state_json FROM game_states WHERE game_id = ?", (game_id,))
            state_row = cursor.fetchone()
            
            if not state_row:
                conn.close()
                return None
            
            # Get players from game_players table
            cursor.execute(
                "SELECT * FROM game_players WHERE game_id = ? ORDER BY position",
                (game_id,)
            )
            player_rows = cursor.fetchall()
            conn.close()
            
            # Parse game
            game = dict(game_row)
            
            # Parse game state
            game_state = json.loads(state_row['state_json'])
            game['game_state'] = game_state
            
            # Parse players from game_players table
            players = []
            for row in player_rows:
                player = dict(row)
                player['is_computer'] = bool(player['is_computer'])
                player['is_host'] = bool(player['is_host'])
                player['is_ready'] = bool(player['is_ready'])
                players.append(player)
            
            game['players_info'] = players
            
            return game
            
        except Exception as e:
            conn.close()
            raise e
    
    def join_game(self, game_id: str, user_id: str, player_name: str) -> Optional[Dict]:
        """Join an existing game"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if game exists and is in lobby
            cursor.execute("SELECT id, game_status FROM games WHERE id = ?", (game_id,))
            game = cursor.fetchone()
            
            if not game:
                conn.close()
                raise ValueError("Game not found")
            
            if game['game_status'] != 'lobby':
                conn.close()
                raise ValueError("Game has already started")
            
            # Check if user is already in the game
            cursor.execute(
                "SELECT id FROM game_players WHERE game_id = ? AND user_id = ?",
                (game_id, user_id)
            )
            existing_player = cursor.fetchone()
            
            if existing_player:
                conn.close()
                raise ValueError("You are already in this game")
            
            # Get current player count
            cursor.execute(
                "SELECT COUNT(*) as count FROM game_players WHERE game_id = ?",
                (game_id,)
            )
            player_count = cursor.fetchone()['count']
            
            if player_count >= 4:
                conn.close()
                raise ValueError("Game is full")
            
            # Add player to game_players
            player_id = str(uuid.uuid4())
            position = player_count
            
            cursor.execute('''
                INSERT INTO game_players (id, game_id, user_id, player_name, position, is_computer, is_host, is_ready)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                player_id, game_id, user_id, player_name, 
                position, 0, 0, 1
            ))
            
            # Update game state
            cursor.execute("SELECT state_json FROM game_states WHERE game_id = ?", (game_id,))
            state_row = cursor.fetchone()
            
            if state_row:
                game_state = json.loads(state_row['state_json'])
                
                # Add new player to game state
                game_state['players'].append({
                    'id': player_id,
                    'name': player_name,
                    'user_id': user_id,
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
                    (json.dumps(game_state), game_id)
                )
            
            conn.commit()
            conn.close()
            
            return {
                "success": True,
                "game_id": game_id,
                "player_id": player_id,
                "message": "Joined game successfully"
            }
            
        except Exception as e:
            conn.close()
            raise e
    
    def start_game(self, game_id: str, user_id: str) -> Optional[Dict]:
        """Start a game"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if user is host
            cursor.execute(
                "SELECT is_host FROM game_players WHERE game_id = ? AND user_id = ?",
                (game_id, user_id)
            )
            player = cursor.fetchone()
            
            if not player:
                conn.close()
                raise ValueError("User not in game")
            
            if not player['is_host']:
                conn.close()
                raise ValueError("Only the host can start the game")
            
            # Check if enough players
            cursor.execute(
                "SELECT COUNT(*) as count FROM game_players WHERE game_id = ?",
                (game_id,)
            )
            player_count = cursor.fetchone()['count']
            
            if player_count < 2:
                conn.close()
                raise ValueError("Need at least 2 players to start")
            
            # Update game status
            cursor.execute(
                "UPDATE games SET game_status = 'playing', started_at = ? WHERE id = ?",
                (datetime.now().isoformat(), game_id)
            )
            
            # Update game state
            cursor.execute("SELECT state_json FROM game_states WHERE game_id = ?", (game_id,))
            state_row = cursor.fetchone()
            
            if state_row:
                game_state = json.loads(state_row['state_json'])
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
                    (json.dumps(game_state), game_id)
                )
            
            conn.commit()
            
            # Get updated game state
            cursor.execute("SELECT state_json FROM game_states WHERE game_id = ?", (game_id,))
            updated_state_row = cursor.fetchone()
            conn.close()
            
            if updated_state_row:
                return {
                    "success": True,
                    "game_state": json.loads(updated_state_row['state_json']),
                    "message": "Game started successfully"
                }
            else:
                return {
                    "success": True,
                    "message": "Game started successfully"
                }
            
        except Exception as e:
            conn.close()
            raise e
    
    def make_move(self, game_id: str, player_id: str, user_id: str, move_type: str, move_data: Dict) -> Optional[Dict]:
        """Make a move in the game"""
        self._ensure_db()
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Verify player belongs to user
            cursor.execute(
                "SELECT user_id FROM game_players WHERE game_id = ? AND id = ?",
                (game_id, player_id)
            )
            player = cursor.fetchone()
            
            if not player or player['user_id'] != user_id:
                conn.close()
                raise ValueError("Player does not belong to user")
            
            # Get game state
            cursor.execute("SELECT state_json FROM game_states WHERE game_id = ?", (game_id,))
            state_row = cursor.fetchone()
            
            if not state_row:
                conn.close()
                raise ValueError("Game state not found")
            
            game_state = json.loads(state_row['state_json'])
            
            # Process move (simplified - you'd add actual game logic here)
            game_state['last_move'] = {
                'player_id': player_id,
                'user_id': user_id,
                'move_type': move_type,
                'move_data': move_data,
                'timestamp': datetime.now().isoformat()
            }
            
            # Update game state
            cursor.execute(
                "UPDATE game_states SET state_json = ?, last_updated = ? WHERE game_id = ?",
                (json.dumps(game_state), datetime.now().isoformat(), game_id)
            )
            
            conn.commit()
            conn.close()
            
            return {
                "success": True,
                "game_state": game_state,
                "message": f"Move {move_type} processed"
            }
            
        except Exception as e:
            conn.close()
            raise e