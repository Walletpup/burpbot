import discord
from discord.ext import commands
import os
import random
import string
import asyncio
import logging
from datetime import datetime, timedelta
import requests
from typing import Optional
import re
import asyncpg
import psycopg2
from urllib.parse import urlparse
import glob
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.moderation = True  # For audit logs (bans, kicks, etc.)

bot = commands.Bot(command_prefix='!', intents=intents)

# Channel IDs
BURP_WINNERS_CHANNEL = 1420198836768346244
NEW_PRIZE_POOLS_CHANNEL = 1420198889918566541
VERIFICATION_CHANNEL = 1419189311139614841
WELCOME_CHANNEL = 1419154118085181523
LINKS_CHANNEL = 1419154016448938004
LOGS_CHANNEL = 1427883248201236540

# Winner notification settings
MIN_BURP_NOTIFICATION_THRESHOLD = 100000  # Minimum BURP amount to trigger winner notification

# Role configuration
BURPER_ROLE_NAME = "Burper"

# Admin user ID - only this user can use admin commands
ADMIN_USER_ID = 1419117925465460878

# Store verification challenges
verification_challenges = {}

# Command cooldowns (user_id -> last_used_timestamp)
burp_cooldowns = {}
burpfact_cooldowns = {}
stats_cooldowns = {}

# Auto-moderation settings
auto_mod_enabled = True
spam_detection_enabled = True

# Spam detection settings
SPAM_MESSAGE_THRESHOLD = 5  # Number of messages
SPAM_TIME_WINDOW = 5  # Seconds
SPAM_DUPLICATE_THRESHOLD = 3  # Same message repeated

# User message tracking for spam detection
user_message_history = {}  # {user_id: [(timestamp, message_content), ...]}

# Discord invite link patterns
DISCORD_INVITE_PATTERNS = [
    r'discord\.gg/[a-zA-Z0-9]+',
    r'discord\.com/invite/[a-zA-Z0-9]+',
    r'discordapp\.com/invite/[a-zA-Z0-9]+',
    r'discord\.gg/[a-zA-Z0-9]+',
    r'dsc\.gg/[a-zA-Z0-9]+',
]

# Compile regex patterns for better performance
COMPILED_INVITE_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in DISCORD_INVITE_PATTERNS]

# Links for the links channel
BURP_LINKS = {
    "Official Website": "https://www.burpcoin.site/",
    "Gas Streaks Game": "https://www.burpcoin.site/gas-streaks",
    "Twitter/X": "https://x.com/burpcoinada"
}

class BurpBot:
    def __init__(self, bot):
        self.bot = bot
        self.db_pool = None
        self.last_checked_winner_id = None
        self.last_checked_game_id = None
        self.last_checked_slots_winner_id = None  # For Gas Mixer winners
        self.monitoring_task = None
        self.pool_monitoring_task = None
        self.slots_monitoring_task = None  # For Gas Mixer monitoring
    
    async def init_database(self):
        """Initialize database connection pool"""
        try:
            database_url = os.environ.get('DATABASE_URL')
            if not database_url:
                logger.warning("DATABASE_URL not set, using fallback stats only")
                return
            
            # Parse the database URL for asyncpg
            parsed = urlparse(database_url)
            
            self.db_pool = await asyncpg.create_pool(
                host=parsed.hostname,
                port=parsed.port,
                user=parsed.username,
                password=parsed.password,
                database=parsed.path[1:],  # Remove leading slash
                ssl='require' if 'postgres://' in database_url else None,
                min_size=1,
                max_size=3
            )
            logger.info("Database connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            self.db_pool = None
    
    async def start_monitoring(self):
        """Start monitoring database for new winners"""
        if not self.db_pool:
            logger.warning("Cannot start monitoring - database not connected")
            return
        
        # Initialize the last checked winner IDs
        await self.init_last_winner_id()
        await self.init_last_slots_winner_id()
        
        # Start the monitoring tasks
        self.monitoring_task = asyncio.create_task(self.monitor_winners())
        self.pool_monitoring_task = asyncio.create_task(self.monitor_new_pool_types())
        self.slots_monitoring_task = asyncio.create_task(self.monitor_slots_winners())
        logger.info("Started database monitoring for new winners, new pool types, and Gas Mixer winners")
    
    async def init_last_winner_id(self):
        """Initialize the last checked winner ID to avoid duplicate notifications"""
        try:
            async with self.db_pool.acquire() as conn:
                # Get the most recent winner ID to start monitoring from
                result = await conn.fetchrow(
                    """SELECT id FROM gas_streaks 
                       WHERE won = true 
                       ORDER BY created_at DESC 
                       LIMIT 1"""
                )
                if result:
                    self.last_checked_winner_id = result['id']
                    logger.info(f"Initialized monitoring from winner ID: {self.last_checked_winner_id}")
        except Exception as e:
            logger.error(f"Error initializing last winner ID: {e}")
    
    async def init_last_slots_winner_id(self):
        """Initialize the last checked Gas Mixer winner ID to avoid duplicate notifications"""
        try:
            async with self.db_pool.acquire() as conn:
                # Get the most recent Gas Mixer winner (spin with payout > 0)
                result = await conn.fetchrow(
                    """SELECT id FROM burp_slots_spins 
                       WHERE payout > 0 
                       ORDER BY created_at DESC 
                       LIMIT 1"""
                )
                if result:
                    self.last_checked_slots_winner_id = result['id']
                    logger.info(f"Initialized Gas Mixer monitoring from winner ID: {self.last_checked_slots_winner_id}")
        except Exception as e:
            logger.error(f"Error initializing last Gas Mixer winner ID: {e}")
    
    async def monitor_winners(self):
        """Background task to monitor for new winners"""
        while True:
            try:
                if not self.db_pool:
                    await asyncio.sleep(60)  # Wait 1 minute if no database
                    continue
                
                async with self.db_pool.acquire() as conn:
                    # Check for new winners since last check
                    if self.last_checked_winner_id:
                        query = """
                            SELECT id, wallet_address, prize_amount, created_at, transaction_hash, streak_number, pool_id
                            FROM gas_streaks 
                            WHERE won = true 
                            AND id > $1
                            ORDER BY created_at ASC
                        """
                        new_winners = await conn.fetch(query, self.last_checked_winner_id)
                    else:
                        # First time check - get the most recent winner
                        query = """
                            SELECT id, wallet_address, prize_amount, created_at, transaction_hash, streak_number, pool_id
                            FROM gas_streaks 
                            WHERE won = true 
                            ORDER BY created_at DESC 
                            LIMIT 1
                        """
                        new_winners = await conn.fetch(query)
                    
                    # Process new winners
                    for winner in new_winners:
                        await self.process_new_winner(winner)
                        self.last_checked_winner_id = winner['id']
                
                # Check every 30 seconds for new winners
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"Error in winner monitoring: {e}")
                await asyncio.sleep(60)  # Wait longer on error
    
    async def process_new_winner(self, winner_row):
        """Process a new winner and send notification"""
        try:
            # Get token symbol for this pool
            async with self.db_pool.acquire() as conn:
                pool_info = await conn.fetchrow(
                    "SELECT prize_token_symbol, pool_name FROM gas_admin_settings WHERE pool_id = $1",
                    winner_row.get('pool_id', 'burp_default')
                )
            
            token_symbol = pool_info['prize_token_symbol'] if pool_info else 'TOKENS'
            pool_name = pool_info['pool_name'] if pool_info else 'Unknown Pool'
            
            # Check if prize amount meets minimum threshold for BURP tokens
            prize_amount = float(winner_row['prize_amount'])
            if token_symbol == 'BURP' and prize_amount < MIN_BURP_NOTIFICATION_THRESHOLD:
                logger.info(f"Skipping notification for {winner_row['wallet_address']}: {prize_amount} BURP is below threshold of {MIN_BURP_NOTIFICATION_THRESHOLD}")
                return
            
            # Convert database row to winner data format
            winner_data = {
                'winner_address': winner_row['wallet_address'],
                'prize_amount': str(winner_row['prize_amount']),
                'game_id': winner_row['transaction_hash'][:16],  # Use first part of tx hash as game ID
                'streak_length': str(winner_row['streak_number']),
                'token_symbol': token_symbol,
                'pool_name': pool_name,
                'pool_id': winner_row.get('pool_id', 'burp_default')
            }
            
            logger.info(f"New winner detected: {winner_data['winner_address']} won {winner_data['prize_amount']} {token_symbol} on streak {winner_data['streak_length']} in {pool_name}")
            
            # Send winner announcement
            await self.send_winner_announcement(winner_data)
            
        except Exception as e:
            logger.error(f"Error processing new winner: {e}")
    
    async def monitor_slots_winners(self):
        """Background task to monitor for new Gas Mixer winners"""
        while True:
            try:
                if not self.db_pool:
                    await asyncio.sleep(60)  # Wait 1 minute if no database
                    continue
                
                async with self.db_pool.acquire() as conn:
                    # Check for new winners since last check
                    if self.last_checked_slots_winner_id:
                        query = """
                            SELECT id, wallet_address, payout, bet_amount, created_at, transaction_hash
                            FROM burp_slots_spins 
                            WHERE payout > 0 
                            AND id > $1
                            ORDER BY created_at ASC
                        """
                        new_winners = await conn.fetch(query, self.last_checked_slots_winner_id)
                    else:
                        # First time check - get the most recent winner
                        query = """
                            SELECT id, wallet_address, payout, bet_amount, created_at, transaction_hash
                            FROM burp_slots_spins 
                            WHERE payout > 0 
                            ORDER BY created_at DESC 
                            LIMIT 1
                        """
                        new_winners = await conn.fetch(query)
                    
                    # Process new winners
                    for winner in new_winners:
                        await self.process_slots_winner(winner)
                        self.last_checked_slots_winner_id = winner['id']
                
                # Check every 30 seconds for new winners
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"Error in Gas Mixer winner monitoring: {e}")
                await asyncio.sleep(60)  # Wait longer on error
    
    async def process_slots_winner(self, winner_row):
        """Process a new Gas Mixer winner and send notification"""
        try:
            payout = float(winner_row['payout'])
            
            # Check if payout meets minimum threshold for BURP
            if payout < MIN_BURP_NOTIFICATION_THRESHOLD:
                logger.info(f"Skipping Gas Mixer notification for {winner_row['wallet_address']}: {payout} BURP is below threshold of {MIN_BURP_NOTIFICATION_THRESHOLD}")
                return
            
            # Convert database row to winner data format
            winner_data = {
                'winner_address': winner_row['wallet_address'],
                'prize_amount': str(winner_row['payout']),
                'bet_amount': str(winner_row['bet_amount']),
                'game_id': winner_row['transaction_hash'][:16] if winner_row['transaction_hash'] else f"spin-{winner_row['id']}",
                'token_symbol': 'BURP',
                'pool_name': 'Gas Mixer',
                'game_type': 'slots'
            }
            
            logger.info(f"New Gas Mixer winner detected: {winner_data['winner_address']} won {winner_data['prize_amount']} BURP")
            
            # Send winner announcement
            await self.send_slots_winner_announcement(winner_data)
            
        except Exception as e:
            logger.error(f"Error processing Gas Mixer winner: {e}")
    
    async def check_for_new_pool_types(self):
        """Monitor for newly created pool types (not prize pool resets)"""
        try:
            if not self.db_pool:
                return
            
            async with self.db_pool.acquire() as conn:
                # Get all active pools
                current_pools = await conn.fetch(
                    """SELECT pool_id, pool_name, prize_token_symbol, created_at
                       FROM gas_admin_settings 
                       WHERE is_active = true
                       ORDER BY created_at DESC"""
                )
                
                # Check if any pools were created in the last 5 minutes (new pool detection)
                recent_threshold = datetime.utcnow() - timedelta(minutes=5)
                
                for pool in current_pools:
                    if pool['created_at'] > recent_threshold:
                        # This is a newly created pool type
                        pool_prize = await conn.fetchval(
                            "SELECT total_amount FROM gas_streak_prize_pool WHERE pool_id = $1",
                            pool['pool_id']
                        )
                        
                        pool_data = {
                            'total_prize': str(int(float(pool_prize or 0))),
                            'game_id': f"newpool-{pool['pool_id']}-{int(datetime.utcnow().timestamp())}",
                            'pool_name': pool['pool_name'],
                            'token_symbol': pool['prize_token_symbol'],
                            'pool_id': pool['pool_id']
                        }
                        
                        logger.info(f"New pool type detected: {pool['prize_token_symbol']} - {pool['pool_name']}")
                        await self.send_new_pool_type_announcement(pool_data)
                    
        except Exception as e:
            logger.error(f"Error checking for new pool types: {e}")
    
    async def monitor_new_pool_types(self):
        """Background task to monitor for newly created pool types"""
        # Track the last time we checked (start from bot startup time)
        last_check_time = datetime.utcnow()
        logger.info(f"Started new pool monitoring from: {last_check_time}")
        
        while True:
            try:
                if not self.db_pool:
                    await asyncio.sleep(60)  # Wait 1 minute if no database
                    continue
                
                async with self.db_pool.acquire() as conn:
                    # Check for pools created since our last check
                    new_pools = await conn.fetch(
                        """SELECT gas.pool_id, gas.pool_name, gas.prize_token_symbol, gas.created_at,
                                  gpp.total_amount
                           FROM gas_admin_settings gas
                           LEFT JOIN gas_streak_prize_pool gpp ON gas.pool_id = gpp.pool_id
                           WHERE gas.is_active = true 
                           AND gas.created_at > $1
                           ORDER BY gas.created_at ASC""",
                        last_check_time
                    )
                    
                    for pool in new_pools:
                        pool_data = {
                            'total_prize': str(int(float(pool['total_amount'] or 0))),
                            'game_id': f"newpool-{pool['pool_id']}-{int(datetime.utcnow().timestamp())}",
                            'pool_name': pool['pool_name'],
                            'token_symbol': pool['prize_token_symbol'],
                            'pool_id': pool['pool_id']
                        }
                        
                        logger.info(f"NEW POOL DETECTED! {pool['prize_token_symbol']} - {pool['pool_name']} (created: {pool['created_at']})")
                        await self.send_new_pool_type_announcement(pool_data)
                        
                        # Update our last check time to this pool's creation time
                        last_check_time = pool['created_at']
                
                # Update last check time to now if no new pools found
                if not new_pools:
                    last_check_time = datetime.utcnow()
                
                # Check every 30 seconds for new pool types
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"Error in new pool type monitoring: {e}")
                await asyncio.sleep(60)  # Wait longer on error
    
    async def fetch_overall_stats(self):
        """Fetch overall statistics across both games"""
        try:
            if not self.db_pool:
                return None
            
            async with self.db_pool.acquire() as conn:
                # Total unique users across both games
                gas_users = await conn.fetchval("SELECT COUNT(*) FROM gas_streak_users")
                slots_users = await conn.fetchval("SELECT COUNT(*) FROM burp_slots_users")
                
                # Total payments (topups)
                gas_topups = await conn.fetchval(
                    "SELECT COALESCE(SUM(amount), 0) FROM gas_streak_topups"
                )
                slots_topups = await conn.fetchval(
                    "SELECT COALESCE(SUM(amount), 0) FROM burp_slots_topups"
                )
                
                # Total winnings
                gas_winnings = await conn.fetchval(
                    "SELECT COALESCE(SUM(prize_amount), 0) FROM gas_streaks WHERE won = true"
                )
                slots_winnings = await conn.fetchval(
                    "SELECT COALESCE(SUM(payout), 0) FROM burp_slots_spins WHERE payout > 0"
                )
                
                # Total games played
                gas_games = await conn.fetchval("SELECT COUNT(*) FROM gas_streaks")
                slots_games = await conn.fetchval("SELECT COUNT(*) FROM burp_slots_spins")
                
                return {
                    "total_users": (gas_users or 0) + (slots_users or 0),
                    "gas_users": gas_users or 0,
                    "slots_users": slots_users or 0,
                    "total_payments": int((gas_topups or 0) + (slots_topups or 0)),
                    "gas_payments": int(gas_topups or 0),
                    "slots_payments": int(slots_topups or 0),
                    "total_winnings": int((gas_winnings or 0) + (slots_winnings or 0)),
                    "gas_winnings": int(gas_winnings or 0),
                    "slots_winnings": int(slots_winnings or 0),
                    "total_games": (gas_games or 0) + (slots_games or 0),
                    "gas_games": gas_games or 0,
                    "slots_games": slots_games or 0
                }
        except Exception as e:
            logger.error(f"Error fetching overall stats: {e}")
            return None
    
    async def fetch_gas_streaks_stats(self, pool_id=None):
        """Fetch real-time stats from burpcoin database for specific pool or all pools"""
        try:
            if not self.db_pool:
                logger.warning("Database not connected, using fallback stats")
                return None
            
            async with self.db_pool.acquire() as conn:
                # Get total players
                total_players = await conn.fetchval(
                    "SELECT COUNT(*) FROM gas_streak_users"
                )
                
                # Get total streaks sent (pool-specific or all)
                if pool_id:
                    total_streaks = await conn.fetchval(
                        "SELECT COUNT(*) FROM gas_streaks WHERE pool_id = $1", pool_id
                    )
                else:
                    total_streaks = await conn.fetchval(
                        "SELECT COUNT(*) FROM gas_streaks"
                    )
                
                # Get total winners
                if pool_id:
                    total_winners = await conn.fetchval(
                        "SELECT COUNT(*) FROM gas_streaks WHERE won = true AND pool_id = $1", pool_id
                    )
                else:
                    total_winners = await conn.fetchval(
                        "SELECT COUNT(*) FROM gas_streaks WHERE won = true"
                    )
                
                # Get total tokens won
                if pool_id:
                    total_tokens_won = await conn.fetchval(
                        "SELECT COALESCE(SUM(prize_amount), 0) FROM gas_streaks WHERE won = true AND pool_id = $1", pool_id
                    )
                else:
                    total_tokens_won = await conn.fetchval(
                        "SELECT COALESCE(SUM(prize_amount), 0) FROM gas_streaks WHERE won = true"
                    )
                
                # Get active pools
                active_pools = await conn.fetch(
                    """SELECT gas.pool_id, gas.pool_name, gas.prize_token_symbol, 
                              gpp.total_amount, gas.is_active
                       FROM gas_admin_settings gas
                       LEFT JOIN gas_streak_prize_pool gpp ON gas.pool_id = gpp.pool_id
                       WHERE gas.is_active = true
                       ORDER BY gas.pool_order"""
                )
                
                # Get biggest win
                if pool_id:
                    biggest_win = await conn.fetchrow(
                        """SELECT gs.wallet_address, gs.prize_amount, gs.created_at, gas.prize_token_symbol
                           FROM gas_streaks gs
                           LEFT JOIN gas_admin_settings gas ON gs.pool_id = gas.pool_id
                           WHERE gs.won = true AND gs.pool_id = $1
                           ORDER BY gs.prize_amount DESC LIMIT 1""", pool_id
                    )
                else:
                    biggest_win = await conn.fetchrow(
                        """SELECT gs.wallet_address, gs.prize_amount, gs.created_at, gas.prize_token_symbol
                           FROM gas_streaks gs
                           LEFT JOIN gas_admin_settings gas ON gs.pool_id = gas.pool_id
                           WHERE gs.won = true
                           ORDER BY gs.prize_amount DESC LIMIT 1"""
                    )
                
                # Get recent winner
                if pool_id:
                    recent_winner = await conn.fetchrow(
                        """SELECT gs.wallet_address, gs.prize_amount, gs.created_at, gas.prize_token_symbol
                           FROM gas_streaks gs
                           LEFT JOIN gas_admin_settings gas ON gs.pool_id = gas.pool_id
                           WHERE gs.won = true AND gs.pool_id = $1
                           ORDER BY gs.created_at DESC LIMIT 1""", pool_id
                    )
                else:
                    recent_winner = await conn.fetchrow(
                        """SELECT gs.wallet_address, gs.prize_amount, gs.created_at, gas.prize_token_symbol
                           FROM gas_streaks gs
                           LEFT JOIN gas_admin_settings gas ON gs.pool_id = gas.pool_id
                           WHERE gs.won = true
                           ORDER BY gs.created_at DESC LIMIT 1"""
                    )
                
                # Calculate time since last winner
                last_winner_time = "N/A"
                if recent_winner:
                    time_diff = datetime.utcnow() - recent_winner['created_at']
                    total_minutes = int(time_diff.total_seconds() // 60)
                    if total_minutes < 1:
                        last_winner_time = "Just now"
                    elif total_minutes < 60:
                        last_winner_time = f"{total_minutes}m ago"
                    else:
                        hours = total_minutes // 60
                        last_winner_time = f"{hours}h {total_minutes % 60}m ago" if total_minutes % 60 else f"{hours}h ago"
                
                return {
                    "total_players": total_players or 0,
                    "total_streaks": total_streaks or 0,
                    "total_winners": total_winners or 0,
                    "total_tokens_won": int(total_tokens_won or 0),
                    "active_pools": active_pools,
                    "biggest_win": biggest_win,
                    "recent_winner": recent_winner,
                    "last_winner_time": last_winner_time,
                    "pool_id": pool_id
                }
                
        except Exception as e:
            logger.error(f"Error fetching gas streaks stats: {e}")
            return None
    
    async def fetch_burp_slots_stats(self):
        """Fetch Burp Slots statistics"""
        try:
            if not self.db_pool:
                return None
            
            async with self.db_pool.acquire() as conn:
                # Total players
                total_players = await conn.fetchval(
                    "SELECT COUNT(*) FROM burp_slots_users"
                )
                
                # Total spins
                total_spins = await conn.fetchval(
                    "SELECT COUNT(*) FROM burp_slots_spins"
                )
                
                # Total wagered
                total_wagered = await conn.fetchval(
                    "SELECT COALESCE(SUM(bet_amount), 0) FROM burp_slots_spins"
                )
                
                # Total won
                total_won = await conn.fetchval(
                    "SELECT COALESCE(SUM(payout), 0) FROM burp_slots_spins WHERE payout > 0"
                )
                
                # Biggest jackpot
                biggest_jackpot = await conn.fetchrow(
                    """SELECT wallet_address, payout, multiplier, created_at
                       FROM burp_slots_jackpots
                       ORDER BY payout DESC LIMIT 1"""
                )
                
                # Biggest regular win
                biggest_win = await conn.fetchrow(
                    """SELECT wallet_address, payout, bet_amount, created_at
                       FROM burp_slots_spins
                       WHERE payout > 0
                       ORDER BY payout DESC LIMIT 1"""
                )
                
                # Recent big win (last 24 hours)
                recent_big_win = await conn.fetchrow(
                    """SELECT wallet_address, payout, bet_amount, created_at
                       FROM burp_slots_spins
                       WHERE payout >= 50 AND created_at > NOW() - INTERVAL '24 hours'
                       ORDER BY created_at DESC LIMIT 1"""
                )
                
                # Total jackpots
                total_jackpots = await conn.fetchval(
                    "SELECT COUNT(*) FROM burp_slots_jackpots"
                )
                
                return {
                    "total_players": total_players or 0,
                    "total_spins": total_spins or 0,
                    "total_wagered": int(total_wagered or 0),
                    "total_won": int(total_won or 0),
                    "biggest_jackpot": biggest_jackpot,
                    "biggest_win": biggest_win,
                    "recent_big_win": recent_big_win,
                    "total_jackpots": total_jackpots or 0
                }
        except Exception as e:
            logger.error(f"Error fetching burp slots stats: {e}")
            return None
    
    def get_fallback_stats(self, guild):
        """Get fallback stats when API is unavailable"""
        burper_role = discord.utils.get(guild.roles, name=BURPER_ROLE_NAME)
        verified_count = len([m for m in guild.members if burper_role and burper_role in m.roles]) if burper_role else 0
        online_count = len([m for m in guild.members if m.status != discord.Status.offline])
        
        return {
            "gas_streaks": {
                "active_games": "N/A",
                "total_players": "N/A", 
                "games_completed": "N/A",
                "total_ada_won": "N/A"
            },
            "prize_pools": {
                "pools": [],
                "total_active": "N/A"
            },
            "community": {
                "discord_members": len(guild.members),
                "verified_burpers": verified_count,
                "online_now": online_count,
                "bot_status": "Online"
            },
            "recent_activity": {
                "last_winner": "N/A",
                "last_game": "N/A", 
                "new_members_today": "N/A",
                "messages_today": "N/A"
            }
        }
    
    def contains_discord_invite(self, message_content):
        """Check if message contains Discord invite links"""
        for pattern in COMPILED_INVITE_PATTERNS:
            if pattern.search(message_content):
                return True
        return False
    
    async def send_log(self, embed):
        """Send log embed to logs channel"""
        try:
            logs_channel = self.bot.get_channel(LOGS_CHANNEL)
            if logs_channel:
                await logs_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error sending log: {e}")
    
    def check_spam(self, user_id, message_content):
        """Check if user is spamming"""
        current_time = time.time()
        
        # Initialize user history if not exists
        if user_id not in user_message_history:
            user_message_history[user_id] = []
        
        # Clean old messages outside time window
        user_message_history[user_id] = [
            (timestamp, content) for timestamp, content in user_message_history[user_id]
            if current_time - timestamp < SPAM_TIME_WINDOW
        ]
        
        # Add current message
        user_message_history[user_id].append((current_time, message_content))
        
        # Check for rapid messages
        if len(user_message_history[user_id]) >= SPAM_MESSAGE_THRESHOLD:
            return True, "rapid_messages"
        
        # Check for duplicate messages
        recent_messages = [content for _, content in user_message_history[user_id]]
        if recent_messages.count(message_content) >= SPAM_DUPLICATE_THRESHOLD:
            return True, "duplicate_messages"
        
        return False, None
    
    async def handle_spam(self, message, spam_type):
        """Handle spam detection and moderation"""
        try:
            # Delete the message
            await message.delete()
            
            # Send warning message that auto-deletes
            if spam_type == "rapid_messages":
                warning_msg = await message.channel.send(
                    f"⚠️ {message.author.mention}, slow down! You're sending messages too quickly.",
                    delete_after=5
                )
            elif spam_type == "duplicate_messages":
                warning_msg = await message.channel.send(
                    f"⚠️ {message.author.mention}, please don't spam the same message repeatedly.",
                    delete_after=5
                )
            
            # Log to logs channel
            embed = discord.Embed(
                title="🚨 Spam Detected",
                color=0xff9900,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{message.author.mention} ({message.author})", inline=False)
            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
            embed.add_field(name="Type", value=spam_type.replace("_", " ").title(), inline=True)
            embed.add_field(name="Message", value=message.content[:1024] if message.content else "*No content*", inline=False)
            
            await self.send_log(embed)
            
            logger.info(f"Deleted spam ({spam_type}) from {message.author.name} ({message.author.id}) in #{message.channel.name}")
            
        except discord.errors.NotFound:
            pass
        except discord.errors.Forbidden:
            logger.error("Bot doesn't have permission to delete messages")
        except Exception as e:
            logger.error(f"Error handling spam: {e}")
    
    async def handle_discord_invite(self, message):
        """Handle Discord invite link detection and moderation"""
        try:
            # Delete the message
            await message.delete()
            
            # Send simple warning message that auto-deletes
            warning_msg = await message.channel.send(
                f"❌ {message.author.mention}, can't do that here! Discord invite links are not allowed.",
                delete_after=5
            )
            
            # Log to logs channel
            embed = discord.Embed(
                title="🚫 Discord Invite Blocked",
                color=0xff0000,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{message.author.mention} ({message.author})", inline=False)
            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
            embed.add_field(name="Message", value=message.content[:1024], inline=False)
            embed.set_footer(text=f"User ID: {message.author.id}")
            
            await self.send_log(embed)
            
            logger.info(f"Deleted Discord invite from {message.author.name} ({message.author.id}) in #{message.channel.name}")
            
        except discord.errors.NotFound:
            pass
        except discord.errors.Forbidden:
            logger.error("Bot doesn't have permission to delete messages")
        except Exception as e:
            logger.error(f"Error handling Discord invite: {e}")
    
    async def send_winner_announcement(self, winner_data):
        """Send gas streaks winner announcement to burp-winners channel"""
        try:
            channel = self.bot.get_channel(BURP_WINNERS_CHANNEL)
            if not channel:
                logger.error(f"Could not find burp-winners channel {BURP_WINNERS_CHANNEL}")
                return
            
            # Get token symbol and pool info
            token_symbol = winner_data.get('token_symbol', 'TOKENS')
            pool_name = winner_data.get('pool_name', 'Gas Streaks')
            
            embed = discord.Embed(
                title=f"{pool_name.upper()} WINNER!",
                description=f"Congratulations to our latest {token_symbol} winner!",
                color=0x00ff00
            )
            
            # Get winner address and create pool.pm link
            winner_address = winner_data.get('winner_address', 'Unknown')
            if len(winner_address) > 20:
                # Truncate address: first 8 + ... + last 8 characters
                truncated_address = f"{winner_address[:8]}...{winner_address[-8:]}"
            else:
                truncated_address = winner_address
            
            # Create pool.pm link
            pool_pm_link = f"https://pool.pm/{winner_address}"
            
            # Add winner information
            embed.add_field(
                name="Winner",
                value=f"[{truncated_address}]({pool_pm_link})",
                inline=False
            )
            
            # Format prize amount as whole number
            try:
                prize_amount = float(winner_data.get('prize_amount', '0'))
                prize_formatted = f"{int(prize_amount):,}"
            except:
                prize_formatted = winner_data.get('prize_amount', 'N/A')
            
            embed.add_field(
                name="Prize Won",
                value=f"```{prize_formatted} {token_symbol}```",
                inline=True
            )
            
            embed.add_field(
                name="Streak Length",
                value=f"```{winner_data.get('streak_length', 'N/A')}```",
                inline=True
            )
            
            # Add pool information
            embed.add_field(
                name="Pool",
                value=f"```{pool_name}```",
                inline=True
            )
            
            await channel.send(embed=embed)
            logger.info(f"Sent {token_symbol} winner announcement for {winner_address} in {pool_name}")
            
        except Exception as e:
            logger.error(f"Error sending winner announcement: {e}")
    
    async def send_slots_winner_announcement(self, winner_data):
        """Send Gas Mixer winner announcement to burp-winners channel"""
        try:
            channel = self.bot.get_channel(BURP_WINNERS_CHANNEL)
            if not channel:
                logger.error(f"Could not find burp-winners channel {BURP_WINNERS_CHANNEL}")
                return
            
            # Get token symbol and pool info
            token_symbol = winner_data.get('token_symbol', 'BURP')
            pool_name = winner_data.get('pool_name', 'Gas Mixer')
            
            embed = discord.Embed(
                title=f"🧪 {pool_name.upper()} WINNER!",
                description=f"Congratulations to our latest {token_symbol} winner!",
                color=0xED4245  # Red color for Gas Mixer
            )
            
            # Get winner address and create pool.pm link
            winner_address = winner_data.get('winner_address', 'Unknown')
            if len(winner_address) > 20:
                # Truncate address: first 8 + ... + last 8 characters
                truncated_address = f"{winner_address[:8]}...{winner_address[-8:]}"
            else:
                truncated_address = winner_address
            
            # Create pool.pm link
            pool_pm_link = f"https://pool.pm/{winner_address}"
            
            # Add winner information
            embed.add_field(
                name="Winner",
                value=f"[{truncated_address}]({pool_pm_link})",
                inline=False
            )
            
            # Format prize amount as whole number
            try:
                prize_amount = float(winner_data.get('prize_amount', '0'))
                prize_formatted = f"{int(prize_amount):,}"
            except:
                prize_formatted = winner_data.get('prize_amount', 'N/A')
            
            embed.add_field(
                name="Prize Won",
                value=f"```{prize_formatted} {token_symbol}```",
                inline=True
            )
            
            # Format bet amount
            try:
                bet_amount = float(winner_data.get('bet_amount', '0'))
                bet_formatted = f"{int(bet_amount):,}"
            except:
                bet_formatted = winner_data.get('bet_amount', 'N/A')
            
            embed.add_field(
                name="Bet Amount",
                value=f"```{bet_formatted} {token_symbol}```",
                inline=True
            )
            
            # Add game information
            embed.add_field(
                name="Game",
                value=f"```{pool_name}```",
                inline=True
            )
            
            await channel.send(embed=embed)
            logger.info(f"Sent Gas Mixer winner announcement for {winner_address}")
            
        except Exception as e:
            logger.error(f"Error sending Gas Mixer winner announcement: {e}")
    
    async def send_new_pool_type_announcement(self, pool_data):
        """Send new prize pool announcement"""
        try:
            channel = self.bot.get_channel(NEW_PRIZE_POOLS_CHANNEL)
            if not channel:
                logger.error(f"Could not find new prize pools channel {NEW_PRIZE_POOLS_CHANNEL}")
                return
            
            # Get token symbol and pool info
            token_symbol = pool_data.get('token_symbol', 'TOKENS')
            pool_name = pool_data.get('pool_name', 'Gas Streaks')
            
            embed = discord.Embed(
                title=f"NEW POOL TYPE: {token_symbol}",
                description=f"A brand new {token_symbol} pool has been added to Gas Streaks!",
                color=0x00ff00
            )
            
            # Format prize amount as whole number
            try:
                prize_amount = float(pool_data.get('total_prize', '0'))
                prize_formatted = f"{int(prize_amount):,}"
            except:
                prize_formatted = pool_data.get('total_prize', 'N/A')
            
            embed.add_field(
                name=f"{token_symbol} Pool Details",
                value=f"```Starting Prize: {prize_formatted} {token_symbol}\nPool Name: {pool_name}\nStatus: Active```",
                inline=False
            )
            
            await channel.send(embed=embed)
            logger.info(f"Sent new pool type announcement: {token_symbol} - {pool_name}")
            
        except Exception as e:
            logger.error(f"Error sending new pool type announcement: {e}")

# Initialize bot helper
burp_bot = BurpBot(bot)

# Custom check for admin commands
def is_admin_user():
    """Check if the user is the designated admin"""
    def predicate(ctx):
        return ctx.author.id == ADMIN_USER_ID
    return commands.check(predicate)

def check_cooldown(user_id, cooldown_dict, cooldown_seconds):
    """Check if user is on cooldown for a command"""
    current_time = time.time()
    if user_id in cooldown_dict:
        time_passed = current_time - cooldown_dict[user_id]
        if time_passed < cooldown_seconds:
            return False, cooldown_seconds - time_passed
    cooldown_dict[user_id] = current_time
    return True, 0

@bot.event
async def on_ready():
    """Bot startup event"""
    logger.info(f'{bot.user} has connected to Discord!')
    
    # Initialize database connection
    await burp_bot.init_database()
    
    # Start monitoring for new winners
    await burp_bot.start_monitoring()
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")
    
    # Send links embed to links channel
    await send_links_embed()
    
    # Send verification embed to verification channel
    await send_verification_embed()
    
    # Add persistent views for buttons
    bot.add_view(VerificationView())
    
    # Set bot status
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="The Burp Community"
        )
    )

@bot.tree.command(name='purge', description='Delete messages in bulk (Admin only)')
async def purge_command(interaction: discord.Interaction, amount: int):
    """Admin command to delete messages in bulk"""
    try:
        # Check if user is admin
        if interaction.user.id != ADMIN_USER_ID:
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        # Validate amount
        if amount < 1:
            await interaction.response.send_message("❌ Amount must be at least 1", ephemeral=True)
            return
        
        if amount > 100:
            await interaction.response.send_message("❌ Cannot delete more than 100 messages at once", ephemeral=True)
            return
        
        # Defer response
        await interaction.response.defer(ephemeral=True)
        
        # Purge messages
        deleted = await interaction.channel.purge(limit=amount)
        
        # Send confirmation
        await interaction.followup.send(f"🧹 Cleaned {len(deleted)} messages", ephemeral=True)
        
        logger.info(f"Admin {interaction.user.name} purged {len(deleted)} messages in #{interaction.channel.name}")
        
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to delete messages in this channel", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Error deleting messages: {str(e)}", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in purge command: {e}")
        try:
            await interaction.followup.send("❌ An error occurred while purging messages", ephemeral=True)
        except:
            pass

@bot.tree.command(name='burp', description='Post a random burp sound!')
async def burp_command(interaction: discord.Interaction):
    """Fun command that posts actual burp sound files"""
    try:
        # Check cooldown (10 seconds)
        can_use, time_left = check_cooldown(interaction.user.id, burp_cooldowns, 5)
        if not can_use:
            embed = discord.Embed(
                title="Cooldown Active",
                description=f"Please wait {time_left:.1f} more seconds before using `/burp` again!",
                color=0xff9900
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        # Defer response since file operations can take time
        await interaction.response.defer()
        
        # Get all burp sound files
        burp_folder = os.path.join(os.path.dirname(__file__), "burps")
        burp_files = []
        
        # Get all audio files from the burps folder
        for ext in ["*.mp3", "*.wav"]:
            burp_files.extend(glob.glob(os.path.join(burp_folder, ext)))
        
        if not burp_files:
            embed = discord.Embed(
                title="❌ No Burp Sounds Found",
                description="No burp sound files found in the burps folder!",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        # Select a random burp file
        selected_burp = random.choice(burp_files)
        burp_filename = os.path.basename(selected_burp)
        
        # Send just the audio file
        with open(selected_burp, 'rb') as audio_file:
            discord_file = discord.File(audio_file, filename=burp_filename)
            await interaction.followup.send(file=discord_file)
        
        logger.info(f"Burp command used by {interaction.user.name} - posted {burp_filename}")
        
    except Exception as e:
        logger.error(f"Error in burp command: {e}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Oops! My burp got stuck! Try again later.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Oops! My burp got stuck! Try again later.", ephemeral=True)
        except:
            pass

@bot.tree.command(name='burpfact', description='Get a random fun fact about burps!')
async def burpfact_command(interaction: discord.Interaction):
    """Command that shares random fun facts about burps"""
    try:
        # Check cooldown (5 seconds)
        can_use, time_left = check_cooldown(interaction.user.id, burpfact_cooldowns, 5)
        if not can_use:
            embed = discord.Embed(
                title="Cooldown Active",
                description=f"Please wait {time_left:.1f} more seconds before using `/burpfact` again!",
                color=0xff9900
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        # Curated list of interesting burp facts
        burp_facts = [
            "The average person burps 14 times a day!",
            "Burps can travel up to 10 mph!",
            "The longest burp is 1 minute 13 seconds 57 milliseconds by Michele Forgione in Italy!",
            "The loudest burp ever recorded was 109.9 decibels!",
            "The loudest burp by a male is 112.4 decibels, achieved by Neville Sharp in Australia!",
            "The loudest burp by a female is 107.3 decibels, by Kimberly Winter in the USA!",
            "Burping is called 'eructation' in medical terms!",
            "Cows burp about 300-500 liters of methane per day!",
            "Your stomach can hold up to 4 liters of gas!",
            "Fish can't burp because they don't have stomachs!",
            "Astronauts can't burp in space due to zero gravity!",
            "The word 'burp' was first used in 1932!",
            "The sound comes from vibrations in your esophagus!",
            "Helium makes your burps sound higher pitched!",
            "Eating too fast increases burping by 300%!",
            "The ancient Romans considered burping a sign of appreciation!",
            "Burping competitions are held worldwide!",
            "The scientific term for excessive burping is 'aerophagia'!",
            "Burps can contain up to 59% nitrogen!",
            "The average burp lasts 2.5 seconds!",
            "The fear of burping in public is called 'aerophobia'!",
            "Some Guinness records include burping while balancing objects, like a book on the head!",
            "The sound for Booger's epic burp in 'Revenge of the Nerds' was a mix of a camel's orgasm and a human burp!",
            "Gorillas burp when happy, producing a deep rumbling sound to show contentment!",
            "Horses cannot burp, which can lead to serious digestive issues like colic if gas builds up!",
            "In space, attempting to burp often results in a 'wet burp' or vomit due to lack of gravity!",
            "Astronauts use a 'push and burp' technique by shoving off walls to simulate gravity for burping!",
            "Vomiting in a spacesuit can cause it to ricochet back, a real hazard for astronauts!",
            "In zero gravity, more gas ends up as farts since it can't be easily burped out!",
            "NASA designs astronaut food to minimize gas production and avoid burping issues!",
            "Retired astronaut Chris Hadfield explained that burping in space means throwing up in your mouth!",
            "In China, burping after a meal is a polite way to compliment the chef's cooking!",
            "In Turkey and India, burping signifies you've enjoyed your meal and is socially acceptable!",
            "In some Inuit cultures, even farting after eating shows enjoyment of the food!",
            "In burping competitions, entries are judged on volume, duration, and sometimes artistic merit!",
            "Belching disorders can lead to anxiety and social discomfort for sufferers!",
            "The unpleasant smell in some burps comes from trace hydrogen sulfide gas!",
            "The human stomach can accumulate up to 4 liters of gas before discomfort sets in!",
            "A single cow burps methane every 40 seconds on average!",
            "Cows produce up to 220 pounds of methane annually, mostly via burps!",
            "Sheep, goats, and buffalo also burp methane as part of rumination!",
            "Some birds, like turkeys, are capable of burping gas!",
            "Insects can 'burp' if gas forms in their foregut!",
            "It would take about 10 average human burps to fill a 5-liter party balloon!",
            "If all 8 billion people burped simultaneously, it would release around 4 billion liters of gas!",
            "A cow's average burp volume is about 0.42 liters of gas!",
            "Human burps contain negligible methane, unlike cow burps which are methane-rich!",
            "To match one cow's daily methane output, it would require thousands of human burp equivalents in volume!",
            "Collective daily human burps worldwide amount to about 56 billion burps!",
            "An average person's lifetime burps could fill over 100 hot air balloons in gas volume!",
            "Some snakes can expel gas in a fire-like burp if consuming flammable prey!",
            "In movies, burp sounds are often enhanced with animal noises for effect!",
            "Professional eaters often master burping to continue consuming more food!",
            "Some cultures incorporate burping into traditional songs or rituals!",
            "The decibel level of a loud burp rivals a motorcycle engine!",
            "If burps were collectible, one day's global output could fill an Olympic pool with gas!",
            "Elephants, as non-ruminants, burp less methane than cows!",
            "In zero gravity, burping competitions would be impossible without artificial gravity!",
            "The first recorded burping contest dates back to the 20th century!",
            "Some yogis use controlled burping in breathing exercises!",
            "The pitch of a burp depends on the tightness of the esophagus!",
            "Collecting all cow burps could power methane-fueled generators!",
            "World Burp Day is unofficially celebrated by enthusiasts!",
            "Burping on Mars would sound different due to thin atmosphere!",
            "Burping can be a learned skill for ventriloquists!",
            "The echo of a burp in a cave can last several seconds!",
            "Burping in different languages has onomatopoeic words!",
            "Burping in a vacuum would be silent but deadly!",
            "Burping can be contagious in social settings, like yawning!",
            "A burp-powered engine could theoretically run on cow emissions!",
            "Burping while talking can change your voice pitch temporarily!",
            "Chewing gum makes you swallow more air and burp more frequently!",
            "Drinking through straws increases air intake and burping!",
            "Pregnant women burp more due to hormonal changes!",
            "Cold drinks cause more burping than warm ones!",
            "Lying down after eating reduces burping!",
            "Burping helps prevent acid reflux in many people!",
            "Different foods create different burp sounds and smells!",
            "Burping frequency decreases as you age!",
            "Dogs and cats can burp too, but rarely do!",
            "Eating beans increases burping due to complex sugars!",
            "Some medications can increase or decrease burping!",
            "Burping releases about 0.5 liters of gas on average!",
            "Carbonated drinks make you burp more!",
            "Burping after drinking milk is more common due to lactose!"
        ]
        
        # Select a random fact
        random_fact = random.choice(burp_facts)
        
        # Create embed
        embed = discord.Embed(
            title="Burp Fact",
            description=random_fact,
            color=0x00ff6b
        )        
        await interaction.response.send_message(embed=embed)
        logger.info(f"Burp fact command used by {interaction.user.name}")
        
    except Exception as e:
        logger.error(f"Error in burpfact command: {e}")
        try:
            await interaction.response.send_message("❌ Oops! My burp facts got stuck! Try again later.", ephemeral=True)
        except:
            pass

@bot.tree.command(name='help', description='Show all available commands and bot info')
async def help_command(interaction: discord.Interaction):
    """Help command showing all available bot commands"""
    try:
        embed = discord.Embed(
            title="Burp Bot Help",
            description="Welcome to the ultimate burp bot! Here are all available commands:",
            color=0x00ff6b
        )
        
        # Bot commands section
        embed.add_field(
            name="Commands",
            value="`/burp` - Post a random burp sound from our collection\n"
                  "`/burpfact` - Get a random interesting burp fact\n"
                  "`/stats` - Interactive statistics dashboard for all games\n"
                  "`/help` - Show this help message",
            inline=False
        )
        # Community links
        embed.add_field(
            name="Community Links",
            value="• [Official Website](https://www.burpcoin.site/)\n"
                  "• [Gas Streaks Game](https://www.burpcoin.site/gas-streaks)\n"
                  "• [Twitter/X](https://x.com/burpcoinada)",
            inline=False
        )
                
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"Help command used by {interaction.user.name}")
        
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        try:
            await interaction.response.send_message("❌ Help got stuck! Try again later.", ephemeral=True)
        except:
            pass

async def pool_autocomplete(interaction: discord.Interaction, current: str) -> list[discord.app_commands.Choice[str]]:
    """Autocomplete function for pool parameter"""
    try:
        if not burp_bot.db_pool:
            return []
        
        async with burp_bot.db_pool.acquire() as conn:
            pools = await conn.fetch(
                """SELECT pool_id, pool_name, prize_token_symbol 
                   FROM gas_admin_settings 
                   WHERE is_active = true 
                   ORDER BY pool_order"""
            )
            
            choices = []
            for pool in pools:
                # Add choices for both token symbol and pool_id
                token_symbol = pool['prize_token_symbol']
                pool_name = pool['pool_name']
                
                # Filter based on current input
                if current.lower() in token_symbol.lower() or current.lower() in pool_name.lower():
                    choices.append(discord.app_commands.Choice(
                        name=f"{token_symbol} - {pool_name}",
                        value=token_symbol.lower()
                    ))
            
            return choices[:25]  # Discord limits to 25 choices
    except Exception as e:
        logger.error(f"Error in pool autocomplete: {e}")
        return []

class StatsView(discord.ui.View):
    """Interactive stats view with buttons"""
    def __init__(self, user_id: int):
        super().__init__(timeout=180)  # 3 minute timeout
        self.user_id = user_id
    
    @discord.ui.button(label='Overall Stats', style=discord.ButtonStyle.primary, emoji='📊')
    async def overall_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your stats menu!", ephemeral=True)
            return
        
        await interaction.response.defer()
        stats = await burp_bot.fetch_overall_stats()
        
        if not stats:
            await interaction.followup.send("❌ Could not fetch overall stats", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Overall Platform Statistics",
            description="Combined statistics across all games",
            color=0x5865F2
        )
        
        # Add thumbnail
        try:
            target_user = interaction.client.get_user(1419117925465460878)
            if target_user:
                embed.set_thumbnail(url=target_user.display_avatar.url)
        except:
            pass
        
        embed.add_field(
            name="Total Users",
            value=f"```{stats['total_users']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Plays",
            value=f"```{stats['total_games']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Winnings",
            value=f"```{stats['total_winnings']:,} BURP```",
            inline=True
        )
        
        embed.add_field(
            name="Gas Streaks",
            value=f"```Players: {stats['gas_users']:,}\nGames: {stats['gas_games']:,}\nWinnings: {stats['gas_winnings']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Gas Mixer",
            value=f"```Players: {stats['slots_users']:,}\nSpins: {stats['slots_games']:,}\nWinnings: {stats['slots_winnings']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Payments",
            value=f"```{stats['total_payments']:,} BURP```",
            inline=True
        )
        
        await interaction.edit_original_response(embed=embed, view=self)
    
    @discord.ui.button(label='Gas Streaks', style=discord.ButtonStyle.success, emoji='⚡')
    async def gas_streaks_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your stats menu!", ephemeral=True)
            return
        
        await interaction.response.defer()
        stats = await burp_bot.fetch_gas_streaks_stats()
        
        if not stats:
            await interaction.followup.send("❌ Could not fetch Gas Streaks stats", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Gas Streaks Statistics",
            description="Complete Gas Streaks game statistics",
            color=0x57F287
        )
        
        # Add thumbnail
        try:
            target_user = interaction.client.get_user(1419117925465460878)
            if target_user:
                embed.set_thumbnail(url=target_user.display_avatar.url)
        except:
            pass
        
        embed.add_field(
            name="Total Players",
            value=f"```{stats['total_players']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Streaks",
            value=f"```{stats['total_streaks']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Winners",
            value=f"```{stats['total_winners']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Tokens Won",
            value=f"```{stats['total_tokens_won']:,}```",
            inline=True
        )

        # Biggest win
        if stats['biggest_win']:
            win = stats['biggest_win']
            addr = win['wallet_address']
            truncated = f"{addr[:8]}...{addr[-6:]}" if len(addr) > 20 else addr
            embed.add_field(
                name="Biggest Win",
                value=f"```{int(win['prize_amount']):,} {win['prize_token_symbol']}\n{truncated}```",
                inline=True
            )
        
        # Recent winner
        if stats['recent_winner']:
            win = stats['recent_winner']
            addr = win['wallet_address']
            truncated = f"{addr[:8]}...{addr[-6:]}" if len(addr) > 20 else addr
            embed.add_field(
                name="Recent Winner",
                value=f"```{int(win['prize_amount']):,} {win['prize_token_symbol']}\n{truncated}\n{stats['last_winner_time']}```",
                inline=False
            )
        
        # Add pool selection view with pools
        view = GasStreaksPoolView(self.user_id, stats['active_pools'])
        await interaction.edit_original_response(embed=embed, view=view)
    
    @discord.ui.button(label='Gas Mixer', style=discord.ButtonStyle.danger, emoji='🧪')
    async def burp_slots_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your stats menu!", ephemeral=True)
            return
        
        await interaction.response.defer()
        stats = await burp_bot.fetch_burp_slots_stats()
        
        if not stats:
            await interaction.followup.send("❌ Could not fetch Gas Mixer stats", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Gas Mixer Statistics",
            description="Complete Gas Mixer game statistics",
            color=0xED4245
        )
        
        # Add thumbnail
        try:
            target_user = interaction.client.get_user(1419117925465460878)
            if target_user:
                embed.set_thumbnail(url=target_user.display_avatar.url)
        except:
            pass
        
        embed.add_field(
            name="Total Players",
            value=f"```{stats['total_players']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Spins",
            value=f"```{stats['total_spins']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Jackpots",
            value=f"```{stats['total_jackpots']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Wagered",
            value=f"```{stats['total_wagered']:,} BURP```",
            inline=True
        )
        
        embed.add_field(
            name="Total Won",
            value=f"```{stats['total_won']:,} BURP```",
            inline=True
        )
        
        # Calculate RTP
        rtp = (stats['total_won'] / stats['total_wagered'] * 100) if stats['total_wagered'] > 0 else 0
        embed.add_field(
            name="RTP",
            value=f"```{rtp:.2f}%```",
            inline=True
        )
        
        # Biggest jackpot
        if stats['biggest_jackpot']:
            jp = stats['biggest_jackpot']
            addr = jp['wallet_address']
            truncated = f"{addr[:8]}...{addr[-6:]}" if len(addr) > 20 else addr
            embed.add_field(
                name="Biggest Jackpot",
                value=f"```{int(jp['payout']):,} BURP\n{jp['multiplier']}x Multiplier\n{truncated}```",
                inline=True
            )
        
        # Biggest win
        if stats['biggest_win']:
            win = stats['biggest_win']
            addr = win['wallet_address']
            truncated = f"{addr[:8]}...{addr[-6:]}" if len(addr) > 20 else addr
            multiplier = win['payout'] / win['bet_amount'] if win['bet_amount'] > 0 else 0
            embed.add_field(
                name="Biggest Win",
                value=f"```{int(win['payout']):,} BURP\n{multiplier:.1f}x Multiplier\n{truncated}```",
                inline=True
            )
        
        # Recent big win
        if stats['recent_big_win']:
            win = stats['recent_big_win']
            addr = win['wallet_address']
            truncated = f"{addr[:8]}...{addr[-6:]}" if len(addr) > 20 else addr
            embed.add_field(
                name="Recent Big Win (24h)",
                value=f"```{int(win['payout']):,} BURP\n{truncated}```",
                inline=True
            )
        
        await interaction.edit_original_response(embed=embed, view=self)

class GasStreaksPoolView(discord.ui.View):
    """View for selecting specific Gas Streaks pools"""
    def __init__(self, user_id: int, pools=None):
        super().__init__(timeout=180)
        self.user_id = user_id
        
        # Add pool options if provided
        if pools:
            for child in self.children:
                if isinstance(child, discord.ui.Select):
                    child.options = [
                        discord.SelectOption(
                            label=f"{p['prize_token_symbol']} - {p['pool_name']}",
                            value=p['pool_id'],
                            emoji="⚡"
                        )
                        for p in pools
                    ]
    
    @discord.ui.button(label='Back to Main', style=discord.ButtonStyle.secondary, emoji='◀️')
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your stats menu!", ephemeral=True)
            return
        
        # Return to main stats view
        view = StatsView(self.user_id)
        embed = discord.Embed(
            title="Burp Statistics Dashboard",
            description="Select a category to view detailed statistics",
            color=0x00ff6b
        )
        
        embed.add_field(
            name="Overall Stats",
            value="View combined statistics across all games",
            inline=False
        )
        
        embed.add_field(
            name="Gas Streaks",
            value="Detailed Gas Streaks game statistics and pool information",
            inline=False
        )
        
        embed.add_field(
            name="Gas Mixer",
            value="Complete Gas Mixer statistics, jackpots, and big wins",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=view)
    
    @discord.ui.select(
        placeholder="Select a pool to view detailed stats",
        min_values=1,
        max_values=1,
        custom_id="pool_select",
        options=[discord.SelectOption(label="Loading pools...", value="loading")]
    )
    async def pool_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your stats menu!", ephemeral=True)
            return
        
        await interaction.response.defer()
        pool_id = select.values[0]
        
        stats = await burp_bot.fetch_gas_streaks_stats(pool_id)
        
        if not stats:
            await interaction.followup.send("❌ Could not fetch pool stats", ephemeral=True)
            return
        
        # Find pool info
        pool_info = next((p for p in stats['active_pools'] if p['pool_id'] == pool_id), None)
        if not pool_info:
            await interaction.followup.send("❌ Pool not found", ephemeral=True)
            return
        
        token = pool_info['prize_token_symbol']
        
        embed = discord.Embed(
            title=f"{token} Pool Statistics",
            description=f"Detailed statistics for {pool_info['pool_name']}",
            color=0x57F287
        )
        
        # Add thumbnail
        try:
            target_user = interaction.client.get_user(1419117925465460878)
            if target_user:
                embed.set_thumbnail(url=target_user.display_avatar.url)
        except:
            pass
        
        embed.add_field(
            name="Current Prize Pool",
            value=f"```{int(pool_info['total_amount'] or 0):,} {token}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Streaks",
            value=f"```{stats['total_streaks']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Winners",
            value=f"```{stats['total_winners']:,}```",
            inline=True
        )
        
        embed.add_field(
            name="Total Won",
            value=f"```{stats['total_tokens_won']:,} {token}```",
            inline=True
        )
        
        # Win rate
        win_rate = (stats['total_winners'] / stats['total_streaks'] * 100) if stats['total_streaks'] > 0 else 0
        embed.add_field(
            name="Win Rate",
            value=f"```{win_rate:.2f}%```",
            inline=True
        )
        
        # Biggest win for this pool
        if stats['biggest_win']:
            win = stats['biggest_win']
            addr = win['wallet_address']
            truncated = f"{addr[:8]}...{addr[-6:]}" if len(addr) > 20 else addr
            embed.add_field(
                name="Biggest Win",
                value=f"```{int(win['prize_amount']):,} {token}\n{truncated}```",
                inline=True
            )
        
        # Recent winner for this pool
        if stats['recent_winner']:
            win = stats['recent_winner']
            addr = win['wallet_address']
            truncated = f"{addr[:8]}...{addr[-6:]}" if len(addr) > 20 else addr
            embed.add_field(
                name="Recent Winner",
                value=f"```{int(win['prize_amount']):,} {token}\n{truncated}\n{stats['last_winner_time']}```",
                inline=False
            )
        
        await interaction.edit_original_response(embed=embed, view=self)
    
    async def on_timeout(self):
        # Disable all items when view times out
        for item in self.children:
            item.disabled = True

@bot.tree.command(name='stats', description='View comprehensive Burp platform statistics')
async def stats_command(interaction: discord.Interaction):
    """Show interactive stats dashboard"""
    try:
        # Check cooldown (10 seconds)
        can_use, time_left = check_cooldown(interaction.user.id, stats_cooldowns, 10)
        if not can_use:
            embed = discord.Embed(
                title="⏰ Cooldown Active",
                description=f"Please wait {time_left:.1f} more seconds before using `/stats` again!",
                color=0xff9900
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create main stats view
        view = StatsView(interaction.user.id)
        
        embed = discord.Embed(
            title="Burp Statistics Dashboard",
            description="Select a category to view detailed statistics",
            color=0x00ff6b
        )
        
        # Add thumbnail
        try:
            target_user = bot.get_user(1419117925465460878)
            if target_user:
                embed.set_thumbnail(url=target_user.display_avatar.url)
        except:
            pass
        
        embed.add_field(
            name="Overall Stats",
            value="View combined statistics across all games",
            inline=False
        )
        
        embed.add_field(
            name="Gas Streaks",
            value="Detailed Gas Streaks game statistics and pool information",
            inline=False
        )
        
        embed.add_field(
            name="Gas Mixer",
            value="Complete Gas Mixer statistics, jackpots, and big wins",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        logger.info(f"Stats command used by {interaction.user.name}")
        
    except Exception as e:
        logger.error(f"Error in stats command: {e}")
        try:
            await interaction.response.send_message("❌ Error retrieving statistics. Please try again later.", ephemeral=True)
        except:
            pass

# Old verification command removed - now using button system

@bot.event
async def on_message_delete(message):
    """Log deleted messages"""
    if message.author.bot:
        return
    
    try:
        embed = discord.Embed(
            title="🗑️ Message Deleted",
            color=0xff6b6b,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Author", value=f"{message.author.mention} ({message.author})", inline=False)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        
        # Add message content if available
        if message.content:
            content = message.content[:1024]
            embed.add_field(name="Content", value=content, inline=False)
        
        # Add attachments info if any
        if message.attachments:
            attachments_info = "\n".join([f"[{att.filename}]({att.url})" for att in message.attachments])
            embed.add_field(name="Attachments", value=attachments_info[:1024], inline=False)
        
        
        await burp_bot.send_log(embed)
    except Exception as e:
        logger.error(f"Error logging message delete: {e}")

@bot.event
async def on_message_edit(before, after):
    """Log edited messages"""
    if before.author.bot or before.content == after.content:
        return
    
    try:
        embed = discord.Embed(
            title="✏️ Message Edited",
            color=0xffa500,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Author", value=f"{before.author.mention} ({before.author})", inline=False)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Message Link", value=f"[Jump to Message]({after.jump_url})", inline=True)
        
        # Before content
        if before.content:
            embed.add_field(name="Before", value=before.content[:1024], inline=False)
        
        # After content
        if after.content:
            embed.add_field(name="After", value=after.content[:1024], inline=False)
        
        
        await burp_bot.send_log(embed)
    except Exception as e:
        logger.error(f"Error logging message edit: {e}")

@bot.event
async def on_member_update(before, after):
    """Log member updates (nickname changes, role changes)"""
    try:
        # Check for nickname change
        if before.nick != after.nick:
            embed = discord.Embed(
                title="📝 Nickname Changed",
                color=0x3498db,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
            embed.add_field(name="Before", value=before.nick or "*None*", inline=True)
            embed.add_field(name="After", value=after.nick or "*None*", inline=True)
            embed.set_thumbnail(url=after.display_avatar.url)
            
            await burp_bot.send_log(embed)
        
        # Check for role changes
        if before.roles != after.roles:
            added_roles = [role for role in after.roles if role not in before.roles]
            removed_roles = [role for role in before.roles if role not in after.roles]
            
            if added_roles or removed_roles:
                embed = discord.Embed(
                    title="🎭 Roles Updated",
                    color=0x9b59b6,
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Member", value=f"{after.mention} ({after})", inline=False)
                
                if added_roles:
                    embed.add_field(name="Added Roles", value=", ".join([role.mention for role in added_roles]), inline=False)
                
                if removed_roles:
                    embed.add_field(name="Removed Roles", value=", ".join([role.mention for role in removed_roles]), inline=False)
                
                embed.set_thumbnail(url=after.display_avatar.url)
                
                await burp_bot.send_log(embed)
    except Exception as e:
        logger.error(f"Error logging member update: {e}")

@bot.event
async def on_member_ban(guild, user):
    """Log member bans"""
    try:
        # Try to get ban reason from audit log
        ban_reason = "No reason provided"
        banned_by = "Unknown"
        
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    ban_reason = entry.reason or "No reason provided"
                    banned_by = entry.user
                    break
        except:
            pass
        
        embed = discord.Embed(
            title="🔨 Member Banned",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
        embed.add_field(name="Banned By", value=str(banned_by), inline=True)
        embed.add_field(name="Reason", value=ban_reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        await burp_bot.send_log(embed)
    except Exception as e:
        logger.error(f"Error logging member ban: {e}")

@bot.event
async def on_member_unban(guild, user):
    """Log member unbans"""
    try:
        # Try to get unban info from audit log
        unbanned_by = "Unknown"
        
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
                if entry.target.id == user.id:
                    unbanned_by = entry.user
                    break
        except:
            pass
        
        embed = discord.Embed(
            title="🔓 Member Unbanned",
            color=0x2ecc71,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
        embed.add_field(name="Unbanned By", value=str(unbanned_by), inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        await burp_bot.send_log(embed)
    except Exception as e:
        logger.error(f"Error logging member unban: {e}")

@bot.event
async def on_member_remove(member):
    """Log member leaves/kicks"""
    try:
        # Check if it was a kick by looking at audit logs
        was_kicked = False
        kicked_by = None
        kick_reason = None
        
        try:
            async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                if entry.target.id == member.id:
                    # Check if kick happened within last 5 seconds
                    if (datetime.utcnow() - entry.created_at).total_seconds() < 5:
                        was_kicked = True
                        kicked_by = entry.user
                        kick_reason = entry.reason or "No reason provided"
                        break
        except:
            pass
        
        if was_kicked:
            embed = discord.Embed(
                title="👢 Member Kicked",
                color=0xe67e22,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{member.mention} ({member})", inline=False)
            embed.add_field(name="Kicked By", value=str(kicked_by), inline=True)
            embed.add_field(name="Reason", value=kick_reason, inline=False)
        else:
            embed = discord.Embed(
                title="👋 Member Left",
                color=0x95a5a6,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{member.mention} ({member})", inline=False)
            embed.add_field(name="Joined At", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S UTC") if member.joined_at else "Unknown", inline=True)
        
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await burp_bot.send_log(embed)
    except Exception as e:
        logger.error(f"Error logging member remove: {e}")

@bot.event
async def on_member_join(member):
    """Welcome new members and log joins"""
    try:
        # Send welcome message
        channel = bot.get_channel(WELCOME_CHANNEL)
        if channel:
            embed = discord.Embed(
                title="Welcome!",
                description=f"Hey mmhmmphff {member.mention}!",
                color=0x00ff00
            )
            embed.set_image(url=member.display_avatar.url)
            await channel.send(embed=embed)
            logger.info(f"Sent welcome message for {member.name}")
        
        # Log to logs channel
        embed = discord.Embed(
            title="📥 Member Joined",
            color=0x2ecc71,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=f"{member.mention} ({member})", inline=False)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=True)
        
        # Calculate account age
        account_age = datetime.utcnow() - member.created_at
        embed.add_field(name="Account Age", value=f"{account_age.days} days", inline=True)
        
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await burp_bot.send_log(embed)
        
    except Exception as e:
        logger.error(f"Error in member join: {e}")

@bot.event
async def on_message(message):
    """Handle auto-moderation and other messages"""
    if message.author.bot:
        return
    
    # Skip moderation for the designated admin user
    if message.author.id == ADMIN_USER_ID:
        await bot.process_commands(message)
        return
    
    # Check for spam (if enabled)
    if spam_detection_enabled:
        is_spam, spam_type = burp_bot.check_spam(message.author.id, message.content)
        if is_spam:
            await burp_bot.handle_spam(message, spam_type)
            return  # Don't process further if message was spam
    
    # Check for Discord invite links (auto-moderation)
    if auto_mod_enabled and burp_bot.contains_discord_invite(message.content):
        await burp_bot.handle_discord_invite(message)
        return  # Don't process further if message was moderated
    
    # Process other commands
    await bot.process_commands(message)

# Command error handling now handled within individual slash commands

async def send_links_embed():
    """Send links embed to links channel on startup"""
    try:
        channel = bot.get_channel(LINKS_CHANNEL)
        if not channel:
            logger.error(f"Could not find links channel {LINKS_CHANNEL}")
            return
        
        # Clear previous messages (optional)
        async for message in channel.history(limit=10):
            if message.author == bot.user:
                await message.delete()
        
        embed = discord.Embed(
            title="Burp Community Links",
            description="Official Website\nhttps://www.burpcoin.site/\n\nGas Streaks Game\nhttps://www.burpcoin.site/gas-streaks\n\nTwitter/X\nhttps://x.com/burpcoinada",
            color=0x00ff00,
        )
        
        # Get the specified user's avatar for thumbnail
        try:
            target_user = bot.get_user(1419117925465460878)
            if target_user:
                thumbnail_url = target_user.display_avatar.url
            else:
                thumbnail_url = "https://www.burpcoin.site/favicon.ico"
        except:
            thumbnail_url = "https://www.burpcoin.site/favicon.ico"
        
        embed.set_thumbnail(url=thumbnail_url)
        
        await channel.send(embed=embed)
        logger.info("Sent links embed to links channel")
        
    except Exception as e:
        logger.error(f"Error sending links embed: {e}")

class VerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view
    
    @discord.ui.button(label='Start Captcha', style=discord.ButtonStyle.green, emoji='🔐', custom_id='verification_start_captcha')
    async def start_captcha(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user already has the role
        burper_role = discord.utils.get(interaction.guild.roles, name=BURPER_ROLE_NAME)
        if burper_role and burper_role in interaction.user.roles:
            await interaction.response.send_message("✅ You're already verified!", ephemeral=True)
            return
        
        # Generate random 4-digit code
        captcha_code = ''.join(random.choices(string.digits, k=4))
        verification_challenges[interaction.user.id] = captcha_code
        
        # Create captcha embed
        embed = discord.Embed(
            title="🔐 Captcha Verification",
            description=f"Enter this code using the buttons below:",
            color=0x00ff00
        )
        
        embed.add_field(
            name="Your Code",
            value=f"```{captcha_code}```",
            inline=False
        )
        
        embed.add_field(
            name="Instructions",
            value="Click the number buttons below to enter your code",
            inline=False
        )
        
        # Send ephemeral message with keypad
        view = KeypadView(captcha_code, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
        # Remove challenge after 5 minutes
        await asyncio.sleep(300)
        if interaction.user.id in verification_challenges:
            del verification_challenges[interaction.user.id]

class KeypadView(discord.ui.View):
    def __init__(self, correct_code: str, user_id: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.correct_code = correct_code
        self.user_id = user_id
        self.entered_code = ""
    
    async def update_display(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔐 Captcha Verification",
            description=f"Enter this code using the buttons below:",
            color=0x00ff00
        )
        
        embed.add_field(
            name="Your Code",
            value=f"```{self.correct_code}```",
            inline=False
        )
        
        embed.add_field(
            name="Entered",
            value=f"```{self.entered_code + '_' * (4 - len(self.entered_code))}```",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def check_code(self, interaction: discord.Interaction):
        if self.entered_code == self.correct_code:
            # Grant role
            burper_role = discord.utils.get(interaction.guild.roles, name=BURPER_ROLE_NAME)
            if burper_role:
                try:
                    await interaction.user.add_roles(burper_role)
                    
                    success_embed = discord.Embed(
                        title="✅ Verification Successful!",
                        description=f"Welcome to the Burp community! You now have the {burper_role.mention} role.",
                        color=0x00ff00
                    )
                    
                    await interaction.response.edit_message(embed=success_embed, view=None)
                    
                    # Clean up
                    if self.user_id in verification_challenges:
                        del verification_challenges[self.user_id]
                    
                    logger.info(f"Verified user {interaction.user.name} via captcha")
                    
                except Exception as e:
                    logger.error(f"Error granting role: {e}")
                    error_embed = discord.Embed(
                        title="❌ Error",
                        description="Error granting role. Please contact an admin.",
                        color=0xff0000
                    )
                    await interaction.response.edit_message(embed=error_embed, view=None)
            else:
                error_embed = discord.Embed(
                    title="❌ Error",
                    description="Burper role not found. Please contact an admin.",
                    color=0xff0000
                )
                await interaction.response.edit_message(embed=error_embed, view=None)
        else:
            # Wrong code
            error_embed = discord.Embed(
                title="❌ Incorrect Code",
                description="The code you entered is incorrect. Please try again.",
                color=0xff0000
            )
            
            # Reset for retry
            self.entered_code = ""
            await interaction.response.edit_message(embed=error_embed, view=self)
    
    # Number buttons (0-9)
    @discord.ui.button(label='1', style=discord.ButtonStyle.secondary, row=0)
    async def button_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.entered_code) < 4:
            self.entered_code += '1'
            if len(self.entered_code) == 4:
                await self.check_code(interaction)
            else:
                await self.update_display(interaction)
    
    @discord.ui.button(label='2', style=discord.ButtonStyle.secondary, row=0)
    async def button_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.entered_code) < 4:
            self.entered_code += '2'
            if len(self.entered_code) == 4:
                await self.check_code(interaction)
            else:
                await self.update_display(interaction)
    
    @discord.ui.button(label='3', style=discord.ButtonStyle.secondary, row=0)
    async def button_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.entered_code) < 4:
            self.entered_code += '3'
            if len(self.entered_code) == 4:
                await self.check_code(interaction)
            else:
                await self.update_display(interaction)
    
    @discord.ui.button(label='4', style=discord.ButtonStyle.secondary, row=1)
    async def button_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.entered_code) < 4:
            self.entered_code += '4'
            if len(self.entered_code) == 4:
                await self.check_code(interaction)
            else:
                await self.update_display(interaction)
    
    @discord.ui.button(label='5', style=discord.ButtonStyle.secondary, row=1)
    async def button_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.entered_code) < 4:
            self.entered_code += '5'
            if len(self.entered_code) == 4:
                await self.check_code(interaction)
            else:
                await self.update_display(interaction)
    
    @discord.ui.button(label='6', style=discord.ButtonStyle.secondary, row=1)
    async def button_6(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.entered_code) < 4:
            self.entered_code += '6'
            if len(self.entered_code) == 4:
                await self.check_code(interaction)
            else:
                await self.update_display(interaction)
    
    @discord.ui.button(label='7', style=discord.ButtonStyle.secondary, row=2)
    async def button_7(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.entered_code) < 4:
            self.entered_code += '7'
            if len(self.entered_code) == 4:
                await self.check_code(interaction)
            else:
                await self.update_display(interaction)
    
    @discord.ui.button(label='8', style=discord.ButtonStyle.secondary, row=2)
    async def button_8(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.entered_code) < 4:
            self.entered_code += '8'
            if len(self.entered_code) == 4:
                await self.check_code(interaction)
            else:
                await self.update_display(interaction)
    
    @discord.ui.button(label='9', style=discord.ButtonStyle.secondary, row=2)
    async def button_9(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.entered_code) < 4:
            self.entered_code += '9'
            if len(self.entered_code) == 4:
                await self.check_code(interaction)
            else:
                await self.update_display(interaction)
    
    @discord.ui.button(label='Clear', style=discord.ButtonStyle.danger, row=3)
    async def button_clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.entered_code = ""
        await self.update_display(interaction)
    
    @discord.ui.button(label='0', style=discord.ButtonStyle.secondary, row=3)
    async def button_0(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.entered_code) < 4:
            self.entered_code += '0'
            if len(self.entered_code) == 4:
                await self.check_code(interaction)
            else:
                await self.update_display(interaction)

async def send_verification_embed():
    """Send verification instructions to verification channel on startup"""
    try:
        channel = bot.get_channel(VERIFICATION_CHANNEL)
        if not channel:
            logger.error(f"Could not find verification channel {VERIFICATION_CHANNEL}")
            return
        
        # Clear previous messages (optional)
        async for message in channel.history(limit=10):
            if message.author == bot.user:
                await message.delete()
        
        embed = discord.Embed(
            title="Verification Required",
            description="Get your Burper role to access the full server!",
            color=0x00ff00,
        )
        
        embed.add_field(
            name="What You Get",
            value="• Access to all channels\n• Burper role\n• Community privileges",
            inline=False
        )
        
        # Get the specified user's avatar for thumbnail
        try:
            target_user = bot.get_user(1419117925465460878)
            if target_user:
                thumbnail_url = target_user.display_avatar.url
            else:
                thumbnail_url = "https://www.burpcoin.site/favicon.ico"
        except:
            thumbnail_url = "https://www.burpcoin.site/favicon.ico"
        
        embed.set_thumbnail(url=thumbnail_url)
        
        # Send with verification button
        view = VerificationView()
        await channel.send(embed=embed, view=view)
        logger.info("Sent verification embed with button to verification channel")
        
    except Exception as e:
        logger.error(f"Error sending verification embed: {e}")

# API endpoints for external integration removed - use webhooks instead

@bot.tree.command(name='automod', description='Control auto-moderation (Admin only)')
async def automod_command(interaction: discord.Interaction, action: str = None):
    """Admin command to control auto-moderation"""
    # Check if user is admin
    if interaction.user.id != ADMIN_USER_ID:
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    global auto_mod_enabled
    
    if action is None:
        # Show current status
        status = "🟢 Enabled" if auto_mod_enabled else "🔴 Disabled"
        embed = discord.Embed(
            title="🤖 Auto-Moderation Status",
            description=f"Discord invite link moderation is currently **{status}**",
            color=0x00ff00 if auto_mod_enabled else 0xff0000
        )
        
        embed.add_field(
            name="📋 Commands",
            value="• `/automod on` - Enable auto-moderation\n• `/automod off` - Disable auto-moderation\n• `/automod status` - Check current status",
            inline=False
        )
        
        embed.add_field(
            name="🔍 What it does",
            value="Automatically deletes Discord invite links posted by non-administrators",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    elif action.lower() in ['on', 'enable', 'true']:
        auto_mod_enabled = True
        embed = discord.Embed(
            title="✅ Auto-Moderation Enabled",
            description="Discord invite link moderation is now **enabled**",
            color=0x00ff00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"Auto-moderation enabled by {interaction.user.name}")
        
    elif action.lower() in ['off', 'disable', 'false']:
        auto_mod_enabled = False
        embed = discord.Embed(
            title="🔴 Auto-Moderation Disabled",
            description="Discord invite link moderation is now **disabled**",
            color=0xff0000
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"Auto-moderation disabled by {interaction.user.name}")
        
    elif action.lower() in ['status', 'check']:
        status = "🟢 Enabled" if auto_mod_enabled else "🔴 Disabled"
        await interaction.response.send_message(f"Auto-moderation is currently **{status}**", ephemeral=True)
        
    else:
        await interaction.response.send_message("❌ Invalid option. Use `on`, `off`, or `status`", ephemeral=True)

@bot.tree.command(name='spam', description='Control spam detection (Admin only)')
async def spam_command(interaction: discord.Interaction, action: str = None):
    """Admin command to control spam detection"""
    # Check if user is admin
    if interaction.user.id != ADMIN_USER_ID:
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    global spam_detection_enabled
    
    if action is None:
        # Show current status
        status = "🟢 Enabled" if spam_detection_enabled else "🔴 Disabled"
        embed = discord.Embed(
            title="🚨 Spam Detection Status",
            description=f"Spam detection is currently **{status}**",
            color=0x00ff00 if spam_detection_enabled else 0xff0000
        )
        
        embed.add_field(
            name="📋 Commands",
            value="• `/spam on` - Enable spam detection\n• `/spam off` - Disable spam detection\n• `/spam status` - Check current status",
            inline=False
        )
        
        embed.add_field(
            name="🔍 What it detects",
            value=f"• **Rapid Messages**: {SPAM_MESSAGE_THRESHOLD} messages in {SPAM_TIME_WINDOW} seconds\n• **Duplicate Messages**: Same message repeated {SPAM_DUPLICATE_THRESHOLD} times",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    elif action.lower() in ['on', 'enable', 'true']:
        spam_detection_enabled = True
        embed = discord.Embed(
            title="✅ Spam Detection Enabled",
            description="Spam detection is now **enabled**",
            color=0x00ff00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"Spam detection enabled by {interaction.user.name}")
        
    elif action.lower() in ['off', 'disable', 'false']:
        spam_detection_enabled = False
        embed = discord.Embed(
            title="🔴 Spam Detection Disabled",
            description="Spam detection is now **disabled**",
            color=0xff0000
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"Spam detection disabled by {interaction.user.name}")
        
    elif action.lower() in ['status', 'check']:
        status = "🟢 Enabled" if spam_detection_enabled else "🔴 Disabled"
        await interaction.response.send_message(f"Spam detection is currently **{status}**", ephemeral=True)
        
    else:
        await interaction.response.send_message("❌ Invalid option. Use `on`, `off`, or `status`", ephemeral=True)

# HTTP webhook endpoints (for integration with your gas streaks app)
from flask import Flask, request, jsonify
import threading

app = Flask(__name__)

@app.route('/webhook/winner', methods=['POST'])
def webhook_winner():
    """Webhook endpoint for winner announcements"""
    try:
        data = request.json
        
        # Schedule the announcement
        asyncio.run_coroutine_threadsafe(
            burp_bot.send_winner_announcement(data),
            bot.loop
        )
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/new_pool', methods=['POST'])
def webhook_new_pool():
    """Webhook endpoint for new prize pool announcements"""
    try:
        data = request.json
        
        # Schedule the announcement
        asyncio.run_coroutine_threadsafe(
            burp_bot.send_new_prize_pool_announcement(data),
            bot.loop
        )
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

def run_flask():
    """Run Flask app in a separate thread"""
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

if __name__ == '__main__':
    # Start Flask server in a separate thread for webhooks
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start Discord bot
    bot.run(os.environ.get('DISCORD_BOT_TOKEN'))
