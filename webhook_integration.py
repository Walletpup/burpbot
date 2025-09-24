"""
Webhook integration helper for connecting Gas Streaks app to Discord bot
Add these functions to your Gas Streaks backend to automatically post to Discord
"""

import requests
import os
import logging

logger = logging.getLogger(__name__)

class DiscordWebhookIntegration:
    def __init__(self, webhook_base_url=None):
        """
        Initialize Discord webhook integration
        
        Args:
            webhook_base_url: Base URL of your Discord bot's webhook endpoints
                             (e.g., "https://your-bot-app.herokuapp.com")
        """
        self.webhook_base_url = webhook_base_url or os.environ.get('DISCORD_WEBHOOK_URL')
        
    def announce_winner(self, winner_address, prize_amount, streak_length, game_id):
        """
        Announce a Gas Streaks winner to Discord
        
        Args:
            winner_address: Winner's wallet address
            prize_amount: Amount won in ADA
            streak_length: Length of the winning streak
            game_id: Unique game identifier
        """
        try:
            if not self.webhook_base_url:
                logger.warning("Discord webhook URL not configured")
                return False
                
            payload = {
                "winner_address": winner_address,
                "prize_amount": str(prize_amount),
                "streak_length": str(streak_length),
                "game_id": game_id
            }
            
            response = requests.post(
                f"{self.webhook_base_url}/webhook/winner",
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"Successfully announced winner {winner_address} to Discord")
                return True
            else:
                logger.error(f"Failed to announce winner to Discord: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error announcing winner to Discord: {e}")
            return False
    
    def announce_new_prize_pool(self, total_prize, game_id):
        """
        Announce a new prize pool to Discord
        
        Args:
            total_prize: Total prize amount in ADA
            game_id: Unique game identifier
        """
        try:
            if not self.webhook_base_url:
                logger.warning("Discord webhook URL not configured")
                return False
                
            payload = {
                "total_prize": str(total_prize),
                "game_id": game_id
            }
            
            response = requests.post(
                f"{self.webhook_base_url}/webhook/new_pool",
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"Successfully announced new prize pool {game_id} to Discord")
                return True
            else:
                logger.error(f"Failed to announce prize pool to Discord: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error announcing prize pool to Discord: {e}")
            return False

# Example usage in your Gas Streaks app:
"""
# In your Gas Streaks backend, add this integration:

from webhook_integration import DiscordWebhookIntegration

# Initialize the integration
discord = DiscordWebhookIntegration()

# When someone wins:
def handle_game_winner(winner_address, prize_amount, streak_length, game_id):
    # Your existing winner logic...
    
    # Announce to Discord
    discord.announce_winner(
        winner_address=winner_address,
        prize_amount=prize_amount,
        streak_length=streak_length,
        game_id=game_id
    )

# When a new prize pool is created:
def create_new_prize_pool(total_prize, game_id):
    # Your existing prize pool creation logic...
    
    # Announce to Discord
    discord.announce_new_prize_pool(
        total_prize=total_prize,
        game_id=game_id
    )
"""
