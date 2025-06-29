import json
import logging
import random
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from telebot import types
import telebot

from .database_service import DatabaseService
from .spotify_service import SpotifyService

logger = logging.getLogger(__name__)


class TournamentService:
    """Service for managing music tournament brackets and matchups."""
    
    def __init__(self, state_file: str, bot: telebot.TeleBot, chat_id: int, 
                 db_manager: DatabaseService, spotify_service: SpotifyService):
        self.state_file = state_file
        self.bot = bot
        self.chat_id = chat_id
        self.db_manager = db_manager
        self.spotify_service = spotify_service
        
        # Tournament state
        self.bracket = []  # List of rounds
        self.current_round_index = 0
        self.current_matchup_index = 0
        self.active_matchup = None

    def load_tournament_state(self) -> bool:
        """Load tournament state from file."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                    
                self.bracket = state.get("bracket", [])
                self.current_round_index = state.get("current_round_index", 0)
                self.current_matchup_index = state.get("current_matchup_index", 0)
                
                logger.info(f"Tournament state loaded: Round {self.current_round_index + 1}, match {self.current_matchup_index + 1}")
                return True
            else:
                logger.info("No tournament state file found")
                return False
        except Exception as e:
            logger.error(f"Error loading tournament state: {str(e)}")
            return False

    def save_tournament_state(self) -> bool:
        """Save tournament state to file."""
        try:
            state = {
                "bracket": self.bracket,
                "current_round_index": self.current_round_index,
                "current_matchup_index": self.current_matchup_index
            }
            
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
                
            logger.info("Tournament state saved")
            return True
        except Exception as e:
            logger.error(f"Error saving tournament state: {str(e)}")
            return False

    def initialize_tournament(self, song_pools: Dict[str, List[str]]) -> bool:
        """Initialize a new tournament with songs from pools."""
        try:
            # Create list of all songs
            all_songs = []
            for friend, songs in song_pools.items():
                for track_uri in songs:
                    all_songs.append({"track_uri": track_uri, "friend": friend})
            
            # Create first round pairs
            first_round = self.create_pairs(all_songs)
            
            # Set initial tournament state
            self.bracket = [first_round]
            self.current_round_index = 0
            self.current_matchup_index = 0
            
            # Save state
            self.save_tournament_state()
            
            # Notify users
            self.bot.send_message(
                self.chat_id, 
                f"🎉 New tournament started! Round 1, matches: {len(first_round)}."
            )
            
            return True
        except Exception as e:
            logger.error(f"Error initializing tournament: {str(e)}")
            return False

    def create_pairs(self, songs: List[Dict[str, str]]) -> List[Tuple[Dict[str, str], Optional[Dict[str, str]]]]:
        """Create balanced matchup pairs from songs list."""
        try:
            # Group songs by friend
            groups = {}
            for song in songs:
                groups.setdefault(song["friend"], []).append(song)
            
            pairs = []
            remaining_songs = songs.copy()
            
            while len(remaining_songs) > 1:
                # Pick first song randomly
                song1 = random.choice(remaining_songs)
                remaining_songs.remove(song1)
                
                # Try to find song from different friend
                other_songs = [s for s in remaining_songs if s["friend"] != song1["friend"]]
                
                if other_songs:
                    song2 = random.choice(other_songs)
                else:
                    song2 = random.choice(remaining_songs)
                
                remaining_songs.remove(song2)
                pairs.append((song1, song2))
            
            # If one song remains, give it a bye
            if remaining_songs:
                pairs.append((remaining_songs[0], None))
            
            return pairs
        except Exception as e:
            logger.error(f"Error creating pairs: {str(e)}")
            raise

    def post_daily_matchup(self) -> bool:
        """Post the next matchup for voting."""
        try:
            # Check if current round is finished
            if self.current_matchup_index >= len(self.bracket[self.current_round_index]):
                self.bot.send_message(
                    self.chat_id, 
                    f"Round {self.current_round_index + 1} completed. Preparing next round..."
                )
                self.build_next_round()
                return True
            
            # Get current matchup
            matchup = self.bracket[self.current_round_index][self.current_matchup_index]
            
            # Handle bye
            if matchup[1] is None:
                self.bot.send_message(
                    self.chat_id,
                    f"Song from {matchup[0]['friend']} ({matchup[0]['track_uri']}) gets a bye and advances to the next round!"
                )
                self.record_matchup_result(matchup, winner=matchup[0], vote1=0, vote2=0)
                self.current_matchup_index += 1
                self.save_tournament_state()
                self.post_daily_matchup()
                return True
            
            # Check for existing matchup in DB
            matchup_id = self._check_existing_matchup(matchup)
            
            # Get song metadata for better UI
            song1_info = self.spotify_service.get_track_info(matchup[0]["track_uri"])
            song2_info = self.spotify_service.get_track_info(matchup[1]["track_uri"])
            
            # Download and send audio for both songs
            file1 = self.spotify_service.download_song(matchup[0]["track_uri"])
            if not file1:
                self.bot.send_message(self.chat_id, f"Failed to download song from {matchup[0]['friend']}")
                return False
            
            # Send first song
            try:
                with open(file1, 'rb') as f:
                    self.bot.send_audio(self.chat_id, audio=f)
                self.spotify_service.delete_file(file1)
            except Exception as e:
                self.bot.send_message(self.chat_id, f"Error sending first song: {str(e)}")
                self.spotify_service.delete_file(file1)
                return False
            
            # Download and send second song
            file2 = self.spotify_service.download_song(matchup[1]["track_uri"])
            if not file2:
                self.bot.send_message(self.chat_id, f"Failed to download song from {matchup[1]['friend']}")
                return False
            
            # Send second song
            try:
                with open(file2, 'rb') as f:
                    self.bot.send_audio(self.chat_id, audio=f)
                self.spotify_service.delete_file(file2)
            except Exception as e:
                self.bot.send_message(self.chat_id, f"Error sending second song: {str(e)}")
                self.spotify_service.delete_file(file2)
                return False
            
            # Create voting keyboard
            markup = types.InlineKeyboardMarkup(row_width=1)
            btn1 = types.InlineKeyboardButton(
                f"Song 1",
                callback_data="bracket_vote|1"
            )
            btn2 = types.InlineKeyboardButton(
                f"Song 2",
                callback_data="bracket_vote|2"
            )
            markup.add(btn1, btn2)
            
            # Get existing votes if matchup exists
            existing_votes = {"1": set(), "2": set()}
            if matchup_id:
                existing_votes = self.db_manager.get_existing_votes(matchup_id)
                vote1_count = len(existing_votes["1"])
                vote2_count = len(existing_votes["2"])
                msg_text = (
                    f"🎵 Choose the winner of this matchup:\n\n"
                    f"Current votes:\n"
                    f"Song 1: {vote1_count}\n"
                    f"Song 2: {vote2_count}"
                )
            else:
                msg_text = (
                    f"🎵 Choose the winner of this matchup:\n\n"
                )
                # Create new matchup in DB
                matchup_id = self.db_manager.insert_matchup({
                    "song1": matchup[0],
                    "song2": matchup[1]
                }, self.current_round_index + 1)
            
            # Send voting message
            msg = self.bot.send_message(self.chat_id, msg_text, reply_markup=markup)
            
            # Store active matchup info
            self.active_matchup = {
                "round": self.current_round_index + 1,
                "match_index": self.current_matchup_index,
                "song1": matchup[0],
                "song2": matchup[1],
                "song1_info": song1_info,
                "song2_info": song2_info,
                "votes": existing_votes,
                "trivia_msg_id": msg.message_id,
                "chat_id": self.chat_id,
                "reply_markup": markup,
                "matchup_id": matchup_id,
                "start_time": datetime.now()
            }
            
            logger.info(f"Matchup posted: {matchup[0]['track_uri']} vs {matchup[1]['track_uri']}")
            
            return True
        except Exception as e:
            logger.error(f"Error posting matchup: {str(e)}")
            return False

    def _check_existing_matchup(self, matchup: Tuple[Dict[str, str], Dict[str, str]]) -> Optional[int]:
        """Check if matchup already exists in database."""
        try:
            # Use the database manager to check for existing matchup
            # This method should be implemented in the database manager
            return self.db_manager.check_existing_matchup(
                matchup[0]["track_uri"], 
                matchup[1]["track_uri"], 
                self.current_round_index + 1
            )
        except Exception as e:
            logger.error(f"Error checking existing matchup: {str(e)}")
            return None

    def handle_vote(self, user_id: int, vote_value: str) -> Tuple[str, bool]:
        """Handle a user's vote for the active matchup."""
        if not self.active_matchup:
            return "No active matchup", False
        
        voter_id = str(user_id)
        
        # Check if user already voted
        if voter_id in self.active_matchup["votes"]["1"] or voter_id in self.active_matchup["votes"]["2"]:
            return "You've already voted!", False
        
        # Record vote
        self.active_matchup["votes"][vote_value].add(voter_id)
        
        # Record vote in database
        if self.active_matchup["matchup_id"]:
            self.db_manager.insert_vote(self.active_matchup["matchup_id"], voter_id, vote_value)
        
        # Update vote counts
        vote1_count = len(self.active_matchup["votes"]["1"])
        vote2_count = len(self.active_matchup["votes"]["2"])

        new_text = (
            f"🎵 Choose the winner of this matchup:\n\n"
            f"Current votes:\n"
            f"Song 1: {vote1_count}\n"
            f"Song 2: {vote2_count}"
        )
        
        try:
            self.bot.edit_message_text(
                new_text,
                chat_id=self.active_matchup["chat_id"],
                message_id=self.active_matchup["trivia_msg_id"],
                reply_markup=self.active_matchup["reply_markup"]
            )
        except Exception as e:
            logger.error(f"Error updating message: {str(e)}")
        
        # Check if we have enough votes to finalize (this should come from config)
        total_votes = vote1_count + vote2_count
        MIN_VOTES_TO_FINALIZE = 3  # This should be configured
        
        if total_votes >= MIN_VOTES_TO_FINALIZE:
            self.finalize_matchup()
            
        return "Vote counted!", True

    def handle_admin_vote(self, voter_id: str, vote_value: str) -> Tuple[str, bool]:
        """Handle admin-submitted vote for a user."""
        if not self.active_matchup:
            return "No active matchup", False
            
        if voter_id in self.active_matchup["votes"]["1"] or voter_id in self.active_matchup["votes"]["2"]:
            return f"User {voter_id} has already voted!", False
            
        if vote_value not in ["1", "2"]:
            return "Vote must be 1 or 2", False
            
        # Record vote
        self.active_matchup["votes"][vote_value].add(voter_id)
        
        # Record in database
        if self.active_matchup["matchup_id"]:
            self.db_manager.insert_vote(self.active_matchup["matchup_id"], voter_id, vote_value)
            
        # Update vote counts
        vote1_count = len(self.active_matchup["votes"]["1"])
        vote2_count = len(self.active_matchup["votes"]["2"])

        new_text = (
            f"🎵 Choose the winner of this matchup:\n\n"
            f"Current votes:\n"
            f"Song 1: {vote1_count}\n"
            f"Song 2: {vote2_count}"
        )
        
        try:
            self.bot.edit_message_text(
                new_text,
                chat_id=self.active_matchup["chat_id"],
                message_id=self.active_matchup["trivia_msg_id"],
                reply_markup=self.active_matchup["reply_markup"]
            )
        except Exception as e:
            logger.error(f"Error updating message: {str(e)}")
            
        # Check if we have enough votes to finalize
        total_votes = vote1_count + vote2_count
        MIN_VOTES_TO_FINALIZE = 3  # This should be configured
        
        if total_votes >= MIN_VOTES_TO_FINALIZE:
            self.finalize_matchup()
            
        return f"Vote for user {voter_id} counted for song {vote_value}!", True

    def notify_non_voters(self, participants: Dict[int, Dict[str, str]]) -> bool:
        """Send notification to users who haven't voted yet."""
        if not self.active_matchup:
            return False
            
        # Check if matchup has been active for less than 30 minutes
        match_start_time = self.active_matchup.get('start_time')
        if match_start_time and (datetime.now() - match_start_time).total_seconds() > 1800:
            return False
            
        # Check if we already have minimum required votes
        MIN_VOTES_TO_FINALIZE = 3  # This should be configured
        total_votes = len(self.active_matchup["votes"]["1"]) + len(self.active_matchup["votes"]["2"])
        if total_votes >= MIN_VOTES_TO_FINALIZE:
            return False
            
        # Find users who haven't voted
        voted_participants = set().union(
            self.active_matchup["votes"].get("1", set()),
            self.active_matchup["votes"].get("2", set())
        )
        
        # Convert string IDs to integers for comparison
        voted_participants = {int(id) if id.isdigit() else id for id in voted_participants}
        non_voters = set(participants.keys()) - voted_participants
        
        if non_voters:
            mention_text = " ".join([
                f"<a href='https://t.me/{participants[uid]['username']}'>@{participants[uid]['display_name']}</a>" 
                for uid in non_voters
            ])
            
            self.bot.send_message(
                self.active_matchup["chat_id"],
                f"⚠️ Reminder! {mention_text}\n"
                f"You have 30 minutes to vote in the current matchup!",
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            
            return True
        
        return False

    def finalize_matchup(self) -> bool:
        """Finalize the current matchup and move to the next one."""
        if not self.active_matchup:
            return False
            
        vote1 = len(self.active_matchup["votes"]["1"])
        vote2 = len(self.active_matchup["votes"]["2"])
        
        # Handle tie
        if vote1 == vote2:
            self.bot.send_message(self.chat_id, "It's a tie! Voting will continue.")
            return False
            
        # Determine winner
        winner_vote = "1" if vote1 > vote2 else "2"
        loser_vote = "2" if winner_vote == "1" else "1"
        winner_song = self.active_matchup["song1"] if winner_vote == "1" else self.active_matchup["song2"]
        loser_song = self.active_matchup["song1"] if loser_vote == "1" else self.active_matchup["song2"]
        
        # Get winner song info
        song_info = self.active_matchup.get(
            "song1_info" if winner_vote == "1" else "song2_info", 
            self.spotify_service.get_track_info(winner_song["track_uri"])
        )
        
        # Send winner announcement
        self.bot.send_message(
            self.chat_id, 
            f"🏆 Winner: {song_info['artist']} - {song_info['title']} from {winner_song['friend']}'s playlist!\n"
            f"Final score: {vote1}-{vote2}"
        )
        
        # Update database
        if self.active_matchup["matchup_id"]:
            self.db_manager.finalize_matchup(self.active_matchup["matchup_id"], vote1, vote2, winner_song)
            
        # Record result in tournament bracket
        self.record_matchup_result(
            self.bracket[self.current_round_index][self.current_matchup_index], 
            winner_song, 
            vote1, 
            vote2
        )
        
        # Reset active matchup and move to next
        self.active_matchup = None
        self.current_matchup_index += 1
        self.save_tournament_state()
        
        return True

    def record_matchup_result(self, matchup: Tuple[Dict[str, str], Optional[Dict[str, str]]], 
                            winner: Dict[str, str], vote1: int = 0, vote2: int = 0) -> None:
        """Record matchup result in the bracket."""
        matchup_result = {"winner": winner, "vote1": vote1, "vote2": vote2}
        self.bracket[self.current_round_index][self.current_matchup_index] = [matchup[0], matchup[1], matchup_result]

    def build_next_round(self) -> bool:
        """Build the next round from winners of the current round."""
        winners = []
        
        # Collect all winners
        for match in self.bracket[self.current_round_index]:
            if isinstance(match, list) and len(match) == 3 and "winner" in match[2]:
                winners.append(match[2]["winner"])
                
        if not winners:
            self.bot.send_message(self.chat_id, "Error: No winners found for the current round.")
            return False
            
        # If only one winner remains, we have a champion
        if len(winners) == 1:
            # Get winner song info
            song_info = self.spotify_service.get_track_info(winners[0]['track_uri'])
            
            self.bot.send_message(
                self.chat_id, 
                f"🏆 Tournament Champion: {song_info['artist']} - {song_info['title']} from {winners[0]['friend']}'s playlist!"
            )
            
            # Reset tournament
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
                
            return False
            
        # Create matchups for next round
        next_round = self.create_pairs(winners)
        self.bracket.append(next_round)
        self.current_round_index += 1
        self.current_matchup_index = 0
        self.save_tournament_state()
        
        self.bot.send_message(
            self.chat_id, 
            f"Starting Round {self.current_round_index + 1} with {len(next_round)} matches!"
        )
        
        # Post first matchup of new round
        self.post_daily_matchup()
        
        return True

    def visualize_bracket(self) -> str:
        """Generate a text representation of the tournament bracket."""
        visual = ""
        
        for r_idx, round_matches in enumerate(self.bracket):
            visual += f"Round {r_idx + 1}:\n"
            
            for m_idx, match in enumerate(round_matches):
                if isinstance(match, list) and len(match) == 3 and "winner" in match[2]:
                    # Completed match
                    song1 = match[0]
                    song2 = match[1]
                    winner = match[2]["winner"]
                    vote1 = match[2].get("vote1", 0)
                    vote2 = match[2].get("vote2", 0)
                    
                    # Handle different match types
                    if song1 is None and song2 is None:
                        visual += f"  Match {m_idx + 1}: Empty match\n"
                    elif song1 is None:
                        visual += f"  Match {m_idx + 1}: BYE vs {song2['friend']} → Winner: {winner['friend']}\n"
                    elif song2 is None:
                        visual += f"  Match {m_idx + 1}: {song1['friend']} (BYE) → Winner: {winner['friend']}\n"
                    else:
                        visual += f"  Match {m_idx + 1}: {song1['friend']} vs {song2['friend']} → Winner: {winner['friend']} ({vote1}-{vote2})\n"
                else:
                    # Upcoming match
                    song1 = match[0] if match else None
                    song2 = match[1] if match and len(match) > 1 else None
                    
                    if song1 is None and song2 is None:
                        visual += f"  Match {m_idx + 1}: Empty match\n"
                    elif song1 is None:
                        visual += f"  Match {m_idx + 1}: BYE vs {song2['friend']}\n"
                    elif song2 is None:
                        visual += f"  Match {m_idx + 1}: {song1['friend']} → BYE\n"
                    else:
                        visual += f"  Match {m_idx + 1}: {song1['friend']} vs {song2['friend']} → (awaiting vote)\n"
            
            visual += "\n"
            
        return visual

    def get_leaderboard(self) -> str:
        """Get tournament leaderboard."""
        leaderboard = self.db_manager.get_leaderboard(limit=10)
        
        if not leaderboard:
            return "No leaderboard data available yet."
            
        text = "🏆 SONG LEADERBOARD 🏆\n\n"
        
        for i, song in enumerate(leaderboard, 1):
            song_info = self.spotify_service.get_track_info(song["track_uri"])
            text += (
                f"{i}. {song_info['artist']} - {song_info['title']}\n"
                f"   From: {song['friend']}'s playlist\n"
                f"   W/L: {song['wins']}-{song['losses']} ({song['win_rate']}%)\n\n"
            )
            
        return text

    def get_friend_stats(self) -> str:
        """Get statistics for each friend's playlist."""
        stats = self.db_manager.get_friend_stats()
        
        if not stats:
            return "No friend statistics available yet."
            
        text = "👥 PLAYLIST STATISTICS 👥\n\n"
        
        for i, stat in enumerate(stats, 1):
            text += (
                f"{i}. {stat['friend']}'s Playlist\n"
                f"   Songs: {stat['songs']}\n"
                f"   W/L: {stat['total_wins']}-{stat['total_losses']} ({stat['win_rate']}%)\n\n"
            )
            
        return text
