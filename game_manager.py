# game_manager.py - PostgreSQL compatible with boolean fixes
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
        db.ensure_tables_exist()

    def create_deck(self) -> List[Dict]:
        suits = ["hearts", "diamonds", "clubs", "spades"]
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        deck = []
        for suit in suits:
            for rank in ranks:
                if rank in ['J', 'Q', 'K']:
                    value = 10
                elif rank == 'A':
                    value = 1
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
        hands = [[] for _ in range(num_players)]
        for i in range(5):
            for player_idx in range(num_players):
                if deck:
                    hands[player_idx].append(deck.pop())
        return deck, hands

    def create_game(self, players: List[Dict], game_name: Optional[str] = None, creator_id: Optional[str] = None) -> Dict:
        self._ensure_db()
        game_id = str(uuid.uuid4())
        room_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        created_at = datetime.now().isoformat()

        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO games (id, room_code, game_name, game_status, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (game_id, room_code, game_name, 'lobby', created_at))

                player_ids = []
                game_players = []
                deck = self.create_deck()
                remaining_deck, hands = self.deal_cards(deck, len(players))

                for i, player_data in enumerate(players):
                    player_id = str(uuid.uuid4())
                    player_ids.append(player_id)

                    user_id = None
                    if i == 0 and creator_id and not player_data.get("is_computer", False):
                        user_id = creator_id
                    elif player_data.get("user_id") and not player_data.get("is_computer", False):
                        user_id = player_data["user_id"]

                    # Insert with proper booleans
                    cursor.execute("""
                        INSERT INTO game_players (id, game_id, user_id, player_name, position, is_computer, is_host, is_ready)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        player_id, game_id, user_id,
                        player_data["name"],
                        i,
                        player_data.get("is_computer", False),  # boolean
                        i == 0,                                  # boolean
                        not player_data.get("is_computer", False)  # boolean
                    ))

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

                game_state = {
                    'id': game_id,
                    'room_code': room_code,
                    'game_status': 'lobby',
                    'turn_count': 0,
                    'turn_phase': 'waiting',
                    'deck': remaining_deck,
                    'deck_length': len(remaining_deck),
                    'discard_pile': [],
                    'players': game_players,
                    'current_player_index': 0,
                    'last_move': None,
                    'created_at': created_at
                }

                state_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO game_states (id, game_id, state_json)
                    VALUES (%s, %s, %s)
                """, (state_id, game_id, json.dumps(game_state)))

                conn.commit()

            return {
                "success": True,
                "game_id": game_id,
                "room_code": room_code,
                "player_id": player_ids[0] if player_ids else None,
                "game_state": game_state,
                "message": "Game created successfully"
            }
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            db.return_connection(conn)

    def get_game(self, game_id: str) -> Optional[Dict]:
        self._ensure_db()
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM games WHERE id = %s", (game_id,))
                game_row = cursor.fetchone()
                if not game_row:
                    return None

                cursor.execute("SELECT state_json FROM game_states WHERE game_id = %s", (game_id,))
                state_row = cursor.fetchone()
                if not state_row:
                    return None

                cursor.execute(
                    "SELECT * FROM game_players WHERE game_id = %s ORDER BY position",
                    (game_id,)
                )
                player_rows = cursor.fetchall()

                game = dict(game_row)
                game_state = json.loads(state_row['state_json'])
                game['game_state'] = game_state

                players = []
                for row in player_rows:
                    player = dict(row)
                    player['is_computer'] = bool(player['is_computer'])
                    player['is_host'] = bool(player['is_host'])
                    player['is_ready'] = bool(player['is_ready'])
                    players.append(player)

                game['players_info'] = players
                return game
        finally:
            db.return_connection(conn)

    def join_game(self, game_id: str, user_id: str, player_name: str) -> Optional[Dict]:
        self._ensure_db()
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, game_status FROM games WHERE id = %s", (game_id,))
                game = cursor.fetchone()
                if not game:
                    raise ValueError("Game not found")
                if game['game_status'] != 'lobby':
                    raise ValueError("Game has already started")

                cursor.execute(
                    "SELECT id FROM game_players WHERE game_id = %s AND user_id = %s",
                    (game_id, user_id)
                )
                if cursor.fetchone():
                    raise ValueError("You are already in this game")

                cursor.execute(
                    "SELECT COUNT(*) as count FROM game_players WHERE game_id = %s",
                    (game_id,)
                )
                player_count = cursor.fetchone()['count']
                if player_count >= 4:
                    raise ValueError("Game is full")

                player_id = str(uuid.uuid4())
                position = player_count

                # Insert with proper booleans
                cursor.execute("""
                    INSERT INTO game_players (id, game_id, user_id, player_name, position, is_computer, is_host, is_ready)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (player_id, game_id, user_id, player_name, position, False, False, True))

                cursor.execute("SELECT state_json FROM game_states WHERE game_id = %s", (game_id,))
                state_row = cursor.fetchone()
                if state_row:
                    game_state = json.loads(state_row['state_json'])
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
                    cursor.execute(
                        "UPDATE game_states SET state_json = %s WHERE game_id = %s",
                        (json.dumps(game_state), game_id)
                    )

                conn.commit()
            return {
                "success": True,
                "game_id": game_id,
                "player_id": player_id,
                "message": "Joined game successfully"
            }
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            db.return_connection(conn)

    def start_game(self, game_id: str, user_id: str) -> Optional[Dict]:
        self._ensure_db()
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT is_host FROM game_players WHERE game_id = %s AND user_id = %s",
                    (game_id, user_id)
                )
                player = cursor.fetchone()
                if not player:
                    raise ValueError("User not in game")
                if not player['is_host']:
                    raise ValueError("Only the host can start the game")

                cursor.execute(
                    "SELECT COUNT(*) as count FROM game_players WHERE game_id = %s",
                    (game_id,)
                )
                player_count = cursor.fetchone()['count']
                if player_count < 2:
                    raise ValueError("Need at least 2 players to start")

                cursor.execute(
                    "UPDATE games SET game_status = 'playing', started_at = %s WHERE id = %s",
                    (datetime.now().isoformat(), game_id)
                )

                cursor.execute("SELECT state_json FROM game_states WHERE game_id = %s", (game_id,))
                state_row = cursor.fetchone()
                if state_row:
                    game_state = json.loads(state_row['state_json'])
                    game_state['game_status'] = 'playing'
                    game_state['turn_phase'] = 'draw'
                    game_state['current_player_index'] = 0
                    for i, p in enumerate(game_state['players']):
                        p['is_current_turn'] = (i == 0)
                    cursor.execute(
                        "UPDATE game_states SET state_json = %s WHERE game_id = %s",
                        (json.dumps(game_state), game_id)
                    )

                conn.commit()

                cursor.execute("SELECT state_json FROM game_states WHERE game_id = %s", (game_id,))
                updated_state = cursor.fetchone()
                if updated_state:
                    return {
                        "success": True,
                        "game_state": json.loads(updated_state['state_json']),
                        "message": "Game started successfully"
                    }
                else:
                    return {"success": True, "message": "Game started successfully"}
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            db.return_connection(conn)

    def make_move(self, game_id: str, player_id: str, user_id: str, move_type: str, move_data: Dict) -> Optional[Dict]:
        self._ensure_db()
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id FROM game_players WHERE game_id = %s AND id = %s",
                    (game_id, player_id)
                )
                player = cursor.fetchone()
                if not player or player['user_id'] != user_id:
                    raise ValueError("Player does not belong to user")

                cursor.execute("SELECT state_json FROM game_states WHERE game_id = %s", (game_id,))
                state_row = cursor.fetchone()
                if not state_row:
                    raise ValueError("Game state not found")

                game_state = json.loads(state_row['state_json'])
                game_state['last_move'] = {
                    'player_id': player_id,
                    'user_id': user_id,
                    'move_type': move_type,
                    'move_data': move_data,
                    'timestamp': datetime.now().isoformat()
                }

                cursor.execute(
                    "UPDATE game_states SET state_json = %s, last_updated = %s WHERE game_id = %s",
                    (json.dumps(game_state), datetime.now().isoformat(), game_id)
                )
                conn.commit()

            return {
                "success": True,
                "game_state": game_state,
                "message": f"Move {move_type} processed"
            }
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            db.return_connection(conn)