import logging
import re
import os
import uuid
import subprocess
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class SpotifyService:
    """Service for handling Spotify API interactions and music downloads."""
    
    def __init__(self, client_id: str, client_secret: str, download_dir: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.download_dir = download_dir
        self.sp = self._initialize_spotify()
        
        # Ensure download directory exists
        os.makedirs(self.download_dir, exist_ok=True)
        
    def _initialize_spotify(self) -> spotipy.Spotify:
        """Initialize Spotify client with credentials."""
        try:
            return spotipy.Spotify(
                client_credentials_manager=SpotifyClientCredentials(
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
            )
        except Exception as e:
            logger.error(f"Failed to initialize Spotify client: {str(e)}")
            raise

    def extract_playlist_id(self, playlist_url: str) -> str:
        """Extract playlist ID from Spotify URL."""
        match = re.search(r'playlist/([a-zA-Z0-9]+)', playlist_url)
        if not match:
            raise ValueError("Invalid playlist URL format")
        return match.group(1)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def get_tracks_from_playlist(self, playlist_url: str) -> List[str]:
        """Get all track URIs from a Spotify playlist."""
        try:
            playlist_id = self.extract_playlist_id(playlist_url)
            track_uris = []
            
            results = self.sp.playlist_items(playlist_id)
            track_items = results['items']
            
            # Paginate through all results
            while results['next']:
                results = self.sp.next(results)
                track_items.extend(results['items'])
            
            for item in track_items:
                track = item.get('track')
                if track:
                    track_uris.append(track['external_urls']['spotify'])
            
            return track_uris
        except Exception as e:
            logger.error(f"Error fetching playlist tracks: {str(e)}")
            raise

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
    def download_song(self, track_uri: str) -> Optional[str]:
        """Download a song from Spotify using spotdl."""
        try:
            # Create a unique directory for this download
            unique_dir = os.path.join(self.download_dir, str(uuid.uuid4()))
            os.makedirs(unique_dir, exist_ok=True)
            
            # Run spotdl command
            cmd = ["spotdl", "--output", unique_dir, "--bitrate", "320k", track_uri]
            logger.info(f"Downloading song {track_uri} to {unique_dir}")
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                encoding="utf-8", 
                errors="replace", 
                timeout=120
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to download {track_uri}: {result.stderr}")
                return None
            
            # Get the downloaded file
            files = os.listdir(unique_dir)
            if not files:
                logger.error(f"No files found after download for {track_uri}")
                return None
            
            file_path = os.path.join(unique_dir, files[0])
            return file_path
            
        except Exception as e:
            logger.exception(f"Exception during download of {track_uri}: {str(e)}")
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def get_track_info(self, track_uri: str) -> Dict[str, any]:
        """Get track information from Spotify."""
        try:
            # Extract track ID from URI or URL
            if "/track/" in track_uri:
                track_id = track_uri.split("/track/")[1].split("?")[0]
            else:
                track_id = track_uri
                
            track = self.sp.track(track_id)
            
            return {
                "title": track["name"],
                "artist": track["artists"][0]["name"],
                "album": track["album"]["name"],
                "duration_ms": track["duration_ms"],
                "preview_url": track["preview_url"],
                "image_url": track["album"]["images"][0]["url"] if track["album"]["images"] else None
            }
        except Exception as e:
            logger.error(f"Error fetching track info: {str(e)}")
            # If all retries failed, return default values
            if isinstance(e, (ConnectionError, spotipy.SpotifyException)):
                raise  # Allow retry to work
            return {
                "title": "Unknown Track",
                "artist": "Unknown Artist",
                "album": "Unknown Album",
                "duration_ms": 0,
                "preview_url": None,
                "image_url": None
            }

    def delete_file(self, file_path: str) -> None:
        """Delete a downloaded file and cleanup."""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                
                # Try to remove parent directory if it's empty
                parent_dir = os.path.dirname(file_path)
                if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                    os.rmdir(parent_dir)
            else:
                logger.warning(f"File {file_path} doesn't exist and can't be deleted.")
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {str(e)}")

    def create_playlist_from_tracks(self, track_uris: List[str], playlist_name: str) -> str:
        """Generate a text representation of a playlist from the given tracks."""
        playlist_text = f"🎵 {playlist_name} 🎵\n\n"
        
        for i, uri in enumerate(track_uris, 1):
            try:
                info = self.get_track_info(uri)
                playlist_text += f"{i}. {info['artist']} - {info['title']}\n"
            except Exception:
                playlist_text += f"{i}. {uri}\n"
                
        return playlist_text
