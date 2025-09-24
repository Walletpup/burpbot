import discord
from discord.ext import commands
import os
import random
import string
import asyncio
import logging
from datetime import datetime
import requests
from typing import Optional
import re
import asyncpg
import psycopg2
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Channel IDs
BURP_WINNERS_CHANNEL = 1420198836768346244
NEW_PRIZE_POOLS_CHANNEL = 1420198889918566541
VERIFICATION_CHANNEL = 1419189311139614841
WELCOME_CHANNEL = 1419154118085181523
LINKS_CHANNEL = 1419154016448938004

# Role configuration
BURPER_ROLE_NAME = "Burper"

# Admin user ID - only this user can use admin commands
ADMIN_USER_ID = 1419117925465460878

# Store verification challenges
verification_challenges = {}

# Auto-moderation settings
auto_mod_enabled = True

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
        self.monitoring_task = None
        self.pool_monitoring_task = None
    
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
        
        # Initialize the last checked winner ID
        await self.init_last_winner_id()
        
        # Start the monitoring tasks
        self.monitoring_task = asyncio.create_task(self.monitor_winners())
        self.pool_monitoring_task = asyncio.create_task(self.monitor_new_games())
        logger.info("Started database monitoring for new winners and games")
    
    async def init_last_winner_id(self):
        """Initialize the last checked winner ID to avoid duplicate notifications"""
        try:
            async with self.db_pool.acquire() as conn:
                # Get the most recent winner ID to start monitoring from
                result = await conn.fetchrow(
                    """SELECT id FROM games 
                       WHERE status = 'completed' AND winner_address IS NOT NULL 
                       ORDER BY created_at DESC 
                       LIMIT 1"""
                )
                if result:
                    self.last_checked_winner_id = result['id']
                    logger.info(f"Initialized monitoring from winner ID: {self.last_checked_winner_id}")
        except Exception as e:
            logger.error(f"Error initializing last winner ID: {e}")
    
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
                            SELECT id, winner_address, prize_amount, created_at, game_id
                            FROM games 
                            WHERE status = 'completed' 
                            AND winner_address IS NOT NULL 
                            AND id > $1
                            ORDER BY created_at ASC
                        """
                        new_winners = await conn.fetch(query, self.last_checked_winner_id)
                    else:
                        # First time check - get the most recent winner
                        query = """
                            SELECT id, winner_address, prize_amount, created_at, game_id
                            FROM games 
                            WHERE status = 'completed' 
                            AND winner_address IS NOT NULL 
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
            # Convert database row to winner data format
            winner_data = {
                'winner_address': winner_row['winner_address'],
                'prize_amount': str(winner_row['prize_amount']),
                'game_id': winner_row['game_id'],
                'streak_length': 'N/A'  # You may need to adjust this based on your schema
            }
            
            logger.info(f"New winner detected: {winner_data['winner_address']} won {winner_data['prize_amount']} ADA")
            
            # Send winner announcement
            await self.send_winner_announcement(winner_data)
            
        except Exception as e:
            logger.error(f"Error processing new winner: {e}")
    
    async def monitor_new_games(self):
        """Background task to monitor for new games/prize pools"""
        while True:
            try:
                if not self.db_pool:
                    await asyncio.sleep(60)  # Wait 1 minute if no database
                    continue
                
                async with self.db_pool.acquire() as conn:
                    # Check for new games since last check
                    if self.last_checked_game_id:
                        query = """
                            SELECT id, prize_pool, created_at, game_id
                            FROM games 
                            WHERE status = 'active' 
                            AND id > $1
                            ORDER BY created_at ASC
                        """
                        new_games = await conn.fetch(query, self.last_checked_game_id)
                    else:
                        # Initialize - get the most recent game ID
                        result = await conn.fetchrow(
                            """SELECT id FROM games 
                               ORDER BY created_at DESC 
                               LIMIT 1"""
                        )
                        if result:
                            self.last_checked_game_id = result['id']
                        new_games = []
                    
                    # Process new games
                    for game in new_games:
                        await self.process_new_game(game)
                        self.last_checked_game_id = game['id']
                
                # Check every 45 seconds for new games
                await asyncio.sleep(45)
                
            except Exception as e:
                logger.error(f"Error in game monitoring: {e}")
                await asyncio.sleep(60)  # Wait longer on error
    
    async def process_new_game(self, game_row):
        """Process a new game and send prize pool notification"""
        try:
            # Convert database row to pool data format
            pool_data = {
                'total_prize': str(game_row['prize_pool']),
                'game_id': game_row['game_id']
            }
            
            logger.info(f"New game detected: {pool_data['game_id']} with {pool_data['total_prize']} ADA prize pool")
            
            # Send prize pool announcement
            await self.send_new_prize_pool_announcement(pool_data)
            
        except Exception as e:
            logger.error(f"Error processing new game: {e}")
    
    async def fetch_gas_streaks_stats(self):
        """Fetch real-time stats from burpcoin database"""
        try:
            if not self.db_pool:
                logger.warning("Database not connected, using fallback stats")
                return None
            
            async with self.db_pool.acquire() as conn:
                # Query your burpcoin database for gas streaks stats
                # Adjust these queries based on your actual database schema
                
                # Get active games count
                active_games = await conn.fetchval(
                    "SELECT COUNT(*) FROM games WHERE status = 'active'"
                )
                
                # Get total players
                total_players = await conn.fetchval(
                    "SELECT COUNT(DISTINCT player_address) FROM game_entries"
                )
                
                # Get completed games
                games_completed = await conn.fetchval(
                    "SELECT COUNT(*) FROM games WHERE status = 'completed'"
                )
                
                # Get total ADA won
                total_ada_won = await conn.fetchval(
                    "SELECT COALESCE(SUM(prize_amount), 0) FROM games WHERE status = 'completed'"
                )
                
                # Get active prize pools
                active_pools = await conn.fetch(
                    "SELECT prize_pool FROM games WHERE status = 'active'"
                )
                
                # Get recent winner info
                recent_winner = await conn.fetchrow(
                    """SELECT winner_address, created_at, game_id 
                       FROM games 
                       WHERE status = 'completed' AND winner_address IS NOT NULL
                       ORDER BY created_at DESC 
                       LIMIT 1"""
                )
                
                # Get recent game info
                recent_game = await conn.fetchrow(
                    """SELECT created_at, game_id 
                       FROM games 
                       ORDER BY created_at DESC 
                       LIMIT 1"""
                )
                
                # Calculate time differences
                last_winner_time = "N/A"
                last_game_time = "N/A"
                
                if recent_winner:
                    time_diff = datetime.utcnow() - recent_winner['created_at']
                    hours = int(time_diff.total_seconds() // 3600)
                    last_winner_time = f"{hours} hours ago" if hours > 0 else "Less than 1 hour ago"
                
                if recent_game:
                    time_diff = datetime.utcnow() - recent_game['created_at']
                    minutes = int(time_diff.total_seconds() // 60)
                    last_game_time = f"{minutes} minutes ago" if minutes > 0 else "Just now"
                
                # Format the response
                return {
                    "gas_streaks": {
                        "active_games": active_games or 0,
                        "total_players": total_players or 0,
                        "games_completed": games_completed or 0,
                        "total_ada_won": f"{total_ada_won or 0:,.0f}"
                    },
                    "prize_pools": {
                        "pools": [float(pool['prize_pool']) for pool in active_pools] if active_pools else [],
                        "total_active": f"{sum(float(pool['prize_pool']) for pool in active_pools) if active_pools else 0:,.0f}"
                    },
                    "recent_activity": {
                        "last_winner": last_winner_time,
                        "last_game": last_game_time,
                        "last_winner_address": recent_winner['winner_address'][:12] + "..." if recent_winner else "N/A"
                    }
                }
                
        except Exception as e:
            logger.error(f"Error fetching stats from database: {e}")
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
    
    async def handle_discord_invite(self, message):
        """Handle Discord invite link detection and moderation"""
        try:
            # Delete the message
            await message.delete()
            
            # Create warning embed
            embed = discord.Embed(
                title="🚫 Discord Invite Detected",
                description=f"{message.author.mention}, Discord invite links are not allowed in this server!",
                color=0xff0000,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="⚠️ Warning",
                value="Please avoid posting Discord invite links. Repeated violations may result in further action.",
                inline=False
            )
            
            embed.add_field(
                name="📝 Original Message",
                value=f"```{message.content[:100]}{'...' if len(message.content) > 100 else ''}```",
                inline=False
            )
            
            embed.set_footer(text="Auto-Moderation System")
            
            # Send warning message that deletes after 10 seconds
            warning_msg = await message.channel.send(embed=embed, delete_after=10)
            
            # Log the moderation action
            logger.info(f"Deleted Discord invite from {message.author.name} ({message.author.id}) in #{message.channel.name}")
            
            # Optional: Send to mod log channel (you can add a mod log channel ID if needed)
            # mod_log_channel = self.bot.get_channel(MOD_LOG_CHANNEL_ID)
            # if mod_log_channel:
            #     await mod_log_channel.send(embed=embed)
            
        except discord.errors.NotFound:
            # Message was already deleted
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
            
            embed = discord.Embed(
                title="🎉 GAS STREAKS WINNER! 🎉",
                description=f"Congratulations to our latest winner!",
                color=0x00ff00,
                timestamp=datetime.utcnow()
            )
            
            # Add winner information
            embed.add_field(
                name="🏆 Winner",
                value=f"**{winner_data.get('winner_address', 'Unknown')}**",
                inline=False
            )
            
            embed.add_field(
                name="💰 Prize Won",
                value=f"**{winner_data.get('prize_amount', 'N/A')} ADA**",
                inline=True
            )
            
            embed.add_field(
                name="🎯 Streak Length",
                value=f"**{winner_data.get('streak_length', 'N/A')}**",
                inline=True
            )
            
            embed.add_field(
                name="🎲 Game ID",
                value=f"`{winner_data.get('game_id', 'N/A')}`",
                inline=True
            )
            
            embed.set_footer(text="Burp Gas Streaks", icon_url="https://www.burpcoin.site/favicon.ico")
            embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1234567890123456789.png")  # You can replace with actual burp emoji
            
            await channel.send(embed=embed)
            logger.info(f"Sent winner announcement for game {winner_data.get('game_id')}")
            
        except Exception as e:
            logger.error(f"Error sending winner announcement: {e}")
    
    async def send_new_prize_pool_announcement(self, pool_data):
        """Send new prize pool announcement"""
        try:
            channel = self.bot.get_channel(NEW_PRIZE_POOLS_CHANNEL)
            if not channel:
                logger.error(f"Could not find new prize pools channel {NEW_PRIZE_POOLS_CHANNEL}")
                return
            
            embed = discord.Embed(
                title="🆕 NEW PRIZE POOL CREATED!",
                description="A fresh prize pool is ready for Gas Streaks!",
                color=0x0099ff,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="💎 Prize Pool",
                value=f"**{pool_data.get('total_prize', 'N/A')} ADA**",
                inline=True
            )
            
            embed.add_field(
                name="🎮 Game ID",
                value=f"`{pool_data.get('game_id', 'N/A')}`",
                inline=True
            )
            
            embed.add_field(
                name="🚀 Status",
                value="**ACTIVE**",
                inline=True
            )
            
            embed.add_field(
                name="🎯 How to Play",
                value="Send **1.5 ADA + 1 BURP** to participate!\nGet **1 ADA refunded** automatically!",
                inline=False
            )
            
            embed.set_footer(text="Good luck, Burpers!", icon_url="https://www.burpcoin.site/favicon.ico")
            
            await channel.send(embed=embed)
            logger.info(f"Sent new prize pool announcement for game {pool_data.get('game_id')}")
            
        except Exception as e:
            logger.error(f"Error sending prize pool announcement: {e}")

# Initialize bot helper
burp_bot = BurpBot(bot)

# Custom check for admin commands
def is_admin_user():
    """Check if the user is the designated admin"""
    def predicate(ctx):
        return ctx.author.id == ADMIN_USER_ID
    return commands.check(predicate)

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
    
    # Set bot status
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="The Burp Community"
        )
    )

@bot.event
async def on_member_join(member):
    """Welcome new members"""
    try:
        channel = bot.get_channel(WELCOME_CHANNEL)
        if not channel:
            logger.error(f"Could not find welcome channel {WELCOME_CHANNEL}")
            return
        
        embed = discord.Embed(
            title=f"Welcome to Burp Community! 🎉",
            description=f"Hey {member.mention}! Welcome to the **Burp** community!",
            color=0xff6b35,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(
            name="🎮 Get Started",
            value="• Check out our Gas Streaks game\n• Verify yourself to get the @Burper role\n• Join the fun and win ADA!",
            inline=False
        )
        
        embed.add_field(
            name="🔗 Useful Links",
            value="• Website: https://www.burpcoin.site/\n• Gas Streaks: https://www.burpcoin.site/gas-streaks\n• Twitter: https://x.com/burpcoinada",
            inline=False
        )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{len(member.guild.members)}", icon_url=member.guild.icon.url if member.guild.icon else None)
        
        await channel.send(embed=embed)
        logger.info(f"Sent welcome message for {member.name}")
        
    except Exception as e:
        logger.error(f"Error sending welcome message: {e}")

@bot.hybrid_command(name='stats')
async def stats_command(ctx):
    """Show Gas Streaks and Burp statistics - available to everyone"""
    try:
        # Send a "loading" message first
        loading_msg = await ctx.send("Fetching latest statistics...")
        
        # Try to fetch real stats from database
        stats_data = await burp_bot.fetch_gas_streaks_stats()
        
        # If database fails, use fallback stats
        if not stats_data:
            stats_data = burp_bot.get_fallback_stats(ctx.guild)
        else:
            # Add Discord community data to database stats
            burper_role = discord.utils.get(ctx.guild.roles, name=BURPER_ROLE_NAME)
            verified_count = len([m for m in ctx.guild.members if burper_role and burper_role in m.roles]) if burper_role else 0
            online_count = len([m for m in ctx.guild.members if m.status != discord.Status.offline])
            
            stats_data["community"] = {
                "discord_members": len(ctx.guild.members),
                "verified_burpers": verified_count,
                "online_now": online_count,
                "bot_status": "Online ✅"
            }
        
        embed = discord.Embed(
            title="Burp Gas Streaks Statistics",
            description="Current statistics for the Burp community and Gas Streaks game",
            color=0x00ff6b,
            timestamp=datetime.utcnow()
        )
        
        # Gas Streaks Stats
        gas_stats = stats_data.get("gas_streaks", {})
        embed.add_field(
            name="Gas Streaks Game",
            value="```" +
                  f"Active Games: {gas_stats.get('active_games', 'N/A')}\n" +
                  f"Total Players: {gas_stats.get('total_players', 'N/A')}\n" +
                  f"Games Completed: {gas_stats.get('games_completed', 'N/A')}\n" +
                  f"Total ADA Won: {gas_stats.get('total_ada_won', 'N/A')}" +
                  "```",
            inline=True
        )
        
        # Prize Pool Stats
        pool_stats = stats_data.get("prize_pools", {})
        pools = pool_stats.get("pools", [])
        if pools:
            pool_text = "\n".join([f"Pool #{i+1}: {pool} ADA" for i, pool in enumerate(pools[:3])])
        else:
            pool_text = "No active pools"
        
        embed.add_field(
            name="Current Prize Pools",
            value="```" +
                  pool_text + "\n" +
                  f"Total Active: {pool_stats.get('total_active', 'N/A')} ADA" +
                  "```",
            inline=True
        )
        
        # Community Stats
        community_stats = stats_data.get("community", {})
        embed.add_field(
            name="Community Stats",
            value="```" +
                  f"Discord Members: {community_stats.get('discord_members', len(ctx.guild.members))}\n" +
                  f"Verified Burpers: {community_stats.get('verified_burpers', 'N/A')}\n" +
                  f"Online Now: {community_stats.get('online_now', 'N/A')}\n" +
                  f"Bot Status: {community_stats.get('bot_status', 'Online')}" +
                  "```",
            inline=False
        )
        
        # Recent Activity
        activity_stats = stats_data.get("recent_activity", {})
        embed.add_field(
            name="Recent Activity",
            value="```" +
                  f"Last Winner: {activity_stats.get('last_winner', 'N/A')}\n" +
                  f"Last Game: {activity_stats.get('last_game', 'N/A')}\n" +
                  f"Winner Address: {activity_stats.get('last_winner_address', 'N/A')}" +
                  "```",
            inline=True
        )
        
        # Game Instructions
        embed.add_field(
            name="How to Play",
            value="Send **1.5 ADA + 1 BURP** to participate!\nGet **1 ADA refunded** automatically!",
            inline=True
        )
        
        # Links
        embed.add_field(
            name="Quick Links",
            value="[Website](https://www.burpcoin.site/) • [Play Gas Streaks](https://www.burpcoin.site/gas-streaks) • [Twitter](https://x.com/burpcoinada)",
            inline=False
        )
        
        # Add data source indicator
        data_source = "Live Data" if stats_data != burp_bot.get_fallback_stats(ctx.guild) else "Cached Data"
        embed.set_footer(
            text=f"{data_source} • Use !verify to get @Burper role",
            icon_url="https://www.burpcoin.site/favicon.ico"
        )
        embed.set_thumbnail(url="https://www.burpcoin.site/favicon.ico")
        
        # Edit the loading message with the stats
        await loading_msg.edit(content=None, embed=embed)
        logger.info(f"Stats command used by {ctx.author.name}")
        
    except Exception as e:
        logger.error(f"Error in stats command: {e}")
        try:
            await loading_msg.edit(content="❌ Error retrieving statistics. Please try again later.")
        except:
            await ctx.send("❌ Error retrieving statistics. Please try again later.", delete_after=5)

@bot.command(name='verify')
async def verify_command(ctx):
    """Start verification process"""
    if ctx.channel.id != VERIFICATION_CHANNEL:
        await ctx.send("❌ Please use this command in the verification channel!", delete_after=5)
        return
    
    # Check if user already has the role
    burper_role = discord.utils.get(ctx.guild.roles, name=BURPER_ROLE_NAME)
    if burper_role and burper_role in ctx.author.roles:
        await ctx.send("✅ You're already verified!", delete_after=5)
        return
    
    # Generate random verification code
    verification_code = ''.join(random.choices(string.digits, k=6))
    verification_challenges[ctx.author.id] = verification_code
    
    embed = discord.Embed(
        title="🔐 Verification Challenge",
        description=f"{ctx.author.mention}, please type the following number to get verified:",
        color=0x00ff00
    )
    
    embed.add_field(
        name="📱 Verification Code",
        value=f"```{verification_code}```",
        inline=False
    )
    
    embed.add_field(
        name="⏰ Instructions",
        value="Type the exact number above to receive your @Burper role!",
        inline=False
    )
    
    embed.set_footer(text="This code expires in 5 minutes")
    
    await ctx.send(embed=embed)
    
    # Remove challenge after 5 minutes
    await asyncio.sleep(300)
    if ctx.author.id in verification_challenges:
        del verification_challenges[ctx.author.id]

@bot.event
async def on_message(message):
    """Handle verification responses and other messages"""
    if message.author.bot:
        return
    
    # Check for Discord invite links (auto-moderation)
    if auto_mod_enabled and burp_bot.contains_discord_invite(message.content):
        # Skip moderation for the designated admin user
        if message.author.id != ADMIN_USER_ID:
            await burp_bot.handle_discord_invite(message)
            return  # Don't process further if message was moderated
    
    # Handle verification in verification channel
    if message.channel.id == VERIFICATION_CHANNEL and message.author.id in verification_challenges:
        expected_code = verification_challenges[message.author.id]
        
        if message.content.strip() == expected_code:
            # Grant Burper role
            burper_role = discord.utils.get(message.guild.roles, name=BURPER_ROLE_NAME)
            
            if burper_role:
                try:
                    await message.author.add_roles(burper_role)
                    
                    embed = discord.Embed(
                        title="✅ Verification Successful!",
                        description=f"Welcome to the community, {message.author.mention}!",
                        color=0x00ff00
                    )
                    
                    embed.add_field(
                        name="🎉 Role Granted",
                        value=f"You now have the **@{BURPER_ROLE_NAME}** role!",
                        inline=False
                    )
                    
                    embed.add_field(
                        name="🚀 What's Next?",
                        value="• Explore our channels\n• Try Gas Streaks\n• Join the community discussions!",
                        inline=False
                    )
                    
                    await message.channel.send(embed=embed)
                    
                    # Remove from challenges
                    del verification_challenges[message.author.id]
                    
                    logger.info(f"Verified user {message.author.name}")
                    
                except Exception as e:
                    logger.error(f"Error granting role: {e}")
                    await message.channel.send("❌ Error granting role. Please contact an admin.")
            else:
                await message.channel.send("❌ Burper role not found. Please contact an admin.")
        else:
            await message.channel.send("❌ Incorrect code. Please try `!verify` again.", delete_after=5)
    
    # Process other commands
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CheckFailure):
        # This happens when someone tries to use an admin command without permission
        embed = discord.Embed(
            title="🚫 Access Denied",
            description="You don't have permission to use this command.",
            color=0xff0000
        )
        embed.add_field(
            name="ℹ️ Info",
            value="This command is restricted to the server administrator only.",
            inline=False
        )
        await ctx.send(embed=embed, delete_after=10)
        logger.warning(f"User {ctx.author.name} ({ctx.author.id}) tried to use admin command: {ctx.command}")
    elif isinstance(error, commands.CommandNotFound):
        # Ignore unknown commands
        pass
    else:
        # Log other errors
        logger.error(f"Command error: {error}")
        await ctx.send("❌ An error occurred while processing the command.", delete_after=5)

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
            description="Important links for our community",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        
        for name, url in BURP_LINKS.items():
            embed.add_field(
                name=name,
                value=f"[Click Here]({url})",
                inline=True
            )
        
        embed.set_footer(text="Stay connected with Burp!", icon_url="https://www.burpcoin.site/favicon.ico")
        embed.set_thumbnail(url="https://www.burpcoin.site/favicon.ico")
        
        await channel.send(embed=embed)
        logger.info("Sent links embed to links channel")
        
    except Exception as e:
        logger.error(f"Error sending links embed: {e}")

# API endpoints for external integration
@bot.command(name='announce_winner', hidden=True)
@is_admin_user()
async def announce_winner_command(ctx, *, winner_info):
    """Admin command to announce winner (for testing)"""
    try:
        # Parse winner info (you can customize this format)
        parts = winner_info.split('|')
        winner_data = {
            'winner_address': parts[0] if len(parts) > 0 else 'Test Winner',
            'prize_amount': parts[1] if len(parts) > 1 else '100',
            'streak_length': parts[2] if len(parts) > 2 else '5',
            'game_id': parts[3] if len(parts) > 3 else 'test-game-123'
        }
        
        await burp_bot.send_winner_announcement(winner_data)
        await ctx.send("✅ Winner announcement sent!")
        
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command(name='announce_pool', hidden=True)
@is_admin_user()
async def announce_pool_command(ctx, *, pool_info):
    """Admin command to announce new prize pool (for testing)"""
    try:
        parts = pool_info.split('|')
        pool_data = {
            'total_prize': parts[0] if len(parts) > 0 else '500',
            'game_id': parts[1] if len(parts) > 1 else 'new-game-456'
        }
        
        await burp_bot.send_new_prize_pool_announcement(pool_data)
        await ctx.send("✅ Prize pool announcement sent!")
        
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

@bot.command(name='automod', hidden=True)
@is_admin_user()
async def automod_command(ctx, action=None):
    """Admin command to control auto-moderation"""
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
            value="• `!automod on` - Enable auto-moderation\n• `!automod off` - Disable auto-moderation\n• `!automod status` - Check current status",
            inline=False
        )
        
        embed.add_field(
            name="🔍 What it does",
            value="Automatically deletes Discord invite links posted by non-administrators",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    elif action.lower() in ['on', 'enable', 'true']:
        auto_mod_enabled = True
        embed = discord.Embed(
            title="✅ Auto-Moderation Enabled",
            description="Discord invite link moderation is now **enabled**",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
        logger.info(f"Auto-moderation enabled by {ctx.author.name}")
        
    elif action.lower() in ['off', 'disable', 'false']:
        auto_mod_enabled = False
        embed = discord.Embed(
            title="🔴 Auto-Moderation Disabled",
            description="Discord invite link moderation is now **disabled**",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        logger.info(f"Auto-moderation disabled by {ctx.author.name}")
        
    elif action.lower() in ['status', 'check']:
        status = "🟢 Enabled" if auto_mod_enabled else "🔴 Disabled"
        await ctx.send(f"Auto-moderation is currently **{status}**")
        
    else:
        await ctx.send("❌ Invalid option. Use `on`, `off`, or `status`")

@bot.command(name='testinvite', hidden=True)
@is_admin_user()
async def test_invite_command(ctx):
    """Admin command to test invite link detection"""
    test_messages = [
        "Check out this server: discord.gg/test123",
        "Join us at https://discord.com/invite/abc123",
        "Come to our Discord: discordapp.com/invite/xyz789",
        "Visit dsc.gg/shortlink",
        "This is a normal message without invites"
    ]
    
    embed = discord.Embed(
        title="🧪 Invite Detection Test",
        description="Testing Discord invite link detection patterns:",
        color=0x0099ff
    )
    
    for i, test_msg in enumerate(test_messages, 1):
        detected = burp_bot.contains_discord_invite(test_msg)
        status = "🚫 Would be deleted" if detected else "✅ Would be allowed"
        embed.add_field(
            name=f"Test {i}",
            value=f"```{test_msg}```\n{status}",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='checkwinners', hidden=True)
@is_admin_user()
async def check_winners_command(ctx):
    """Admin command to manually check for new winners"""
    try:
        if not burp_bot.db_pool:
            await ctx.send("❌ Database not connected")
            return
        
        loading_msg = await ctx.send("🔍 Checking database for new winners...")
        
        async with burp_bot.db_pool.acquire() as conn:
            # Get recent winners
            recent_winners = await conn.fetch(
                """SELECT id, winner_address, prize_amount, created_at, game_id
                   FROM games 
                   WHERE status = 'completed' AND winner_address IS NOT NULL 
                   ORDER BY created_at DESC 
                   LIMIT 5"""
            )
            
            if not recent_winners:
                await loading_msg.edit(content="ℹ️ No winners found in database")
                return
            
            embed = discord.Embed(
                title="Recent Winners in Database",
                description="Last 5 winners found:",
                color=0x00ff00
            )
            
            for i, winner in enumerate(recent_winners, 1):
                time_ago = datetime.utcnow() - winner['created_at']
                hours_ago = int(time_ago.total_seconds() // 3600)
                
                embed.add_field(
                    name=f"Winner #{i}",
                    value=f"Address: {winner['winner_address'][:12]}...\n"
                          f"Prize: {winner['prize_amount']} ADA\n"
                          f"Game: {winner['game_id']}\n"
                          f"Time: {hours_ago}h ago",
                    inline=True
                )
            
            embed.add_field(
                name="Monitoring Status",
                value=f"Last checked ID: {burp_bot.last_checked_winner_id}\n"
                      f"Monitoring: {'✅ Active' if burp_bot.monitoring_task else '❌ Inactive'}",
                inline=False
            )
            
            await loading_msg.edit(content=None, embed=embed)
            
    except Exception as e:
        await ctx.send(f"❌ Error checking winners: {e}")
        logger.error(f"Error in check_winners_command: {e}")

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
