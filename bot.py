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
        logger.info("Started database monitoring for new winners and prize pool changes")
    
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
                            SELECT id, wallet_address, prize_amount, created_at, transaction_hash, streak_number
                            FROM gas_streaks 
                            WHERE won = true 
                            AND id > $1
                            ORDER BY created_at ASC
                        """
                        new_winners = await conn.fetch(query, self.last_checked_winner_id)
                    else:
                        # First time check - get the most recent winner
                        query = """
                            SELECT id, wallet_address, prize_amount, created_at, transaction_hash, streak_number
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
            # Convert database row to winner data format
            winner_data = {
                'winner_address': winner_row['wallet_address'],
                'prize_amount': str(winner_row['prize_amount']),
                'game_id': winner_row['transaction_hash'][:16],  # Use first part of tx hash as game ID
                'streak_length': str(winner_row['streak_number'])
            }
            
            logger.info(f"New winner detected: {winner_data['winner_address']} won {winner_data['prize_amount']} ADA on streak {winner_data['streak_length']}")
            
            # Send winner announcement
            await self.send_winner_announcement(winner_data)
            
        except Exception as e:
            logger.error(f"Error processing new winner: {e}")
    
    async def check_and_announce_new_prize_pool(self):
        """Check current prize pool and announce if it's substantial"""
        try:
            if not self.db_pool:
                return
            
            async with self.db_pool.acquire() as conn:
                # Get current prize pool
                current_pool = await conn.fetchrow(
                    "SELECT total_amount FROM gas_streak_prize_pool ORDER BY id DESC LIMIT 1"
                )
                
                if current_pool and current_pool['total_amount'] > 100:  # Only announce if pool > 100 BURP
                    pool_data = {
                        'total_prize': str(int(float(current_pool['total_amount']))),
                        'game_id': f"pool-{int(datetime.utcnow().timestamp())}"
                    }
                    
                    logger.info(f"Announcing new prize pool: {pool_data['total_prize']} BURP")
                    await self.send_new_prize_pool_announcement(pool_data)
                    
        except Exception as e:
            logger.error(f"Error checking prize pool: {e}")
    
    async def monitor_new_games(self):
        """Background task to monitor for prize pool changes"""
        last_prize_amount = None
        
        while True:
            try:
                if not self.db_pool:
                    await asyncio.sleep(60)  # Wait 1 minute if no database
                    continue
                
                async with self.db_pool.acquire() as conn:
                    # Check current prize pool amount
                    current_pool = await conn.fetchrow(
                        "SELECT total_amount FROM gas_streak_prize_pool ORDER BY id DESC LIMIT 1"
                    )
                    
                    if current_pool and last_prize_amount is not None:
                        current_amount = int(float(current_pool['total_amount']))
                        
                        # If prize pool increased significantly (new contributions)
                        if current_amount > last_prize_amount + 50:  # 50+ BURP increase
                            pool_data = {
                                'total_prize': f"{current_amount:,}",
                                'game_id': f"game-{int(datetime.utcnow().timestamp())}"
                            }
                            
                            logger.info(f"Prize pool increased to {current_amount:,} BURP")
                            await self.send_new_prize_pool_announcement(pool_data)
                    
                    if current_pool:
                        last_prize_amount = int(float(current_pool['total_amount']))
                
                # Check every 2 minutes for prize pool changes
                await asyncio.sleep(120)
                
            except Exception as e:
                logger.error(f"Error in prize pool monitoring: {e}")
                await asyncio.sleep(60)  # Wait longer on error
    
    async def fetch_gas_streaks_stats(self):
        """Fetch real-time stats from burpcoin database"""
        try:
            if not self.db_pool:
                logger.warning("Database not connected, using fallback stats")
                return None
            
            async with self.db_pool.acquire() as conn:
                # Query your burpcoin database for gas streaks stats using correct schema
                
                # Get total players (unique wallet addresses)
                total_players = await conn.fetchval(
                    "SELECT COUNT(*) FROM gas_streak_users"
                )
                
                # Get total streaks sent
                total_streaks = await conn.fetchval(
                    "SELECT COUNT(*) FROM gas_streaks"
                )
                
                # Get total winners (streaks that won)
                total_winners = await conn.fetchval(
                    "SELECT COUNT(*) FROM gas_streaks WHERE won = true"
                )
                
                # Get total ADA won
                total_ada_won = await conn.fetchval(
                    "SELECT COALESCE(SUM(prize_amount), 0) FROM gas_streaks WHERE won = true"
                )
                
                # Get current prize pool
                prize_pool = await conn.fetchrow(
                    "SELECT total_amount FROM gas_streak_prize_pool ORDER BY id DESC LIMIT 1"
                )
                
                # Get total pool contributions (total payments made to pool)
                total_contributions = await conn.fetchval(
                    "SELECT COUNT(*) FROM gas_streaks"
                )
                
                # Get total BURP sent to pool (sum of all BURP contributions)
                total_burp_contributions = await conn.fetchval(
                    "SELECT COALESCE(SUM(burp_amount), 0) FROM gas_streaks"
                )
                
                # Get recent winner info
                recent_winner = await conn.fetchrow(
                    """SELECT wallet_address, prize_amount, created_at, transaction_hash
                       FROM gas_streaks 
                       WHERE won = true
                       ORDER BY created_at DESC 
                       LIMIT 1"""
                )
                
                # Get recent streak info
                recent_streak = await conn.fetchrow(
                    """SELECT created_at, transaction_hash, wallet_address
                       FROM gas_streaks 
                       ORDER BY created_at DESC 
                       LIMIT 1"""
                )
                
                # Calculate time differences
                last_winner_time = "N/A"
                last_game_time = "N/A"
                
                # Calculate time since last winner
                if recent_winner:
                    time_diff = datetime.utcnow() - recent_winner['created_at']
                    total_minutes = int(time_diff.total_seconds() // 60)
                    
                    if total_minutes < 1:
                        last_winner_time = "Just now"
                    elif total_minutes < 60:
                        last_winner_time = f"{total_minutes} minute{'s' if total_minutes != 1 else ''} ago"
                    else:
                        hours = total_minutes // 60
                        remaining_minutes = total_minutes % 60
                        if remaining_minutes == 0:
                            last_winner_time = f"{hours} hour{'s' if hours != 1 else ''} ago"
                        else:
                            last_winner_time = f"{hours}h {remaining_minutes}m ago"
                else:
                    last_winner_time = "N/A"
                
                # Calculate time since last game (streak)
                if recent_streak:
                    time_diff = datetime.utcnow() - recent_streak['created_at']
                    total_minutes = int(time_diff.total_seconds() // 60)
                    
                    if total_minutes < 1:
                        last_game_time = "Just now"
                    elif total_minutes < 60:
                        last_game_time = f"{total_minutes} minute{'s' if total_minutes != 1 else ''} ago"
                    else:
                        hours = total_minutes // 60
                        remaining_minutes = total_minutes % 60
                        if remaining_minutes == 0:
                            last_game_time = f"{hours} hour{'s' if hours != 1 else ''} ago"
                        else:
                            last_game_time = f"{hours}h {remaining_minutes}m ago"
                else:
                    last_game_time = "N/A"
                
                # Format the response
                return {
                    "gas_streaks": {
                        "active_games": 1 if prize_pool and prize_pool['total_amount'] > 0 else 0,
                        "total_players": total_players or 0,
                        "games_completed": total_streaks or 0,
                        "total_ada_won": f"{int(total_ada_won or 0):,}"
                    },
                    "prize_pools": {
                        "pools": [float(prize_pool['total_amount'])] if prize_pool else [],
                        "total_active": f"{int(float(prize_pool['total_amount'])) if prize_pool else 0:,}",
                        "total_contributions": f"{total_contributions or 0:,}",
                        "total_burp_contributions": f"{int(float(total_burp_contributions or 0)):,}"
                    },
                    "recent_activity": {
                        "last_winner": last_winner_time,
                        "last_game": last_game_time,
                        "last_amount_won": f"{int(float(recent_winner['prize_amount'])):,} BURP" if recent_winner else "N/A"
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
            
            # Send simple warning message that auto-deletes
            warning_msg = await message.channel.send(
                f"❌ {message.author.mention}, can't do that here! Discord invite links are not allowed.",
                delete_after=5
            )
            
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
                title="GAS STREAKS WINNER!",
                description="Congratulations to our latest winner!",
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
                value=f"```{prize_formatted} BURP```",
                inline=True
            )
            
            embed.add_field(
                name="Streak Length",
                value=f"```{winner_data.get('streak_length', 'N/A')}```",
                inline=True
            )
            
            await channel.send(embed=embed)
            logger.info(f"Sent winner announcement for {winner_address}")
            
            # After announcing winner, check if we should announce new prize pool
            await self.check_and_announce_new_prize_pool()
            
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
                title="NEW PRIZE POOL AVAILABLE!",
                description="A fresh prize pool is ready for Gas Streaks!",
                color=0x00ff00
            )
            
            # Format prize amount as whole number
            try:
                prize_amount = float(pool_data.get('total_prize', '0'))
                prize_formatted = f"{int(prize_amount):,}"
            except:
                prize_formatted = pool_data.get('total_prize', 'N/A')
            
            embed.add_field(
                name="Prize Pool",
                value=f"```{prize_formatted} BURP```",
                inline=True
            )
            
            await channel.send(embed=embed)
            logger.info(f"Sent new prize pool announcement: {prize_formatted} BURP")
            
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

@bot.event
async def on_member_join(member):
    """Welcome new members"""
    try:
        channel = bot.get_channel(WELCOME_CHANNEL)
        if not channel:
            logger.error(f"Could not find welcome channel {WELCOME_CHANNEL}")
            return
        
        embed = discord.Embed(
            title="Welcome!",
            description=f"Hey {member.mention}! Welcome to the **Burp** community!",
            color=0x00ff00
        )
        
        embed.add_field(
            name="Get Started",
            value="• Check out our Gas Streaks game\n• Verify yourself to get the @Burper role\n• Join the fun and win BURP!",
            inline=False
        )
        
        embed.add_field(
            name="Useful Links",
            value="• Website: https://www.burpcoin.site/\n• Gas Streaks: https://www.burpcoin.site/gas-streaks\n• Twitter: https://x.com/burpcoinada",
            inline=False
        )
        
        # Set the user's avatar as the main image
        embed.set_image(url=member.display_avatar.url)
        
        await channel.send(embed=embed)
        logger.info(f"Sent welcome message for {member.name}")
        
    except Exception as e:
        logger.error(f"Error sending welcome message: {e}")

@bot.command(name='purge')
@is_admin_user()
async def purge_command(ctx, amount: int = 10):
    """Admin command to delete messages in bulk"""
    try:
        # Validate amount
        if amount < 1:
            await ctx.send("❌ Amount must be at least 1", delete_after=5)
            return
        
        if amount > 100:
            await ctx.send("❌ Cannot delete more than 100 messages at once", delete_after=5)
            return
        
        # Delete the command message first
        try:
            await ctx.message.delete()
        except:
            pass
        
        # Purge messages
        deleted = await ctx.channel.purge(limit=amount)
        
        # Send confirmation message
        confirmation = await ctx.send(f"🧹 Cleaned {len(deleted)} messages")
        
        # Auto-delete confirmation after 3 seconds
        await asyncio.sleep(3)
        try:
            await confirmation.delete()
        except:
            pass
        
        logger.info(f"Admin {ctx.author.name} purged {len(deleted)} messages in #{ctx.channel.name}")
        
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to delete messages in this channel", delete_after=5)
    except discord.HTTPException as e:
        await ctx.send(f"❌ Error deleting messages: {str(e)}", delete_after=5)
    except Exception as e:
        logger.error(f"Error in purge command: {e}")
        await ctx.send("❌ An error occurred while purging messages", delete_after=5)

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
            color=0x00ff6b
        )
        
        # Gas Streaks Stats
        gas_stats = stats_data.get("gas_streaks", {})
        embed.add_field(
            name="Gas Streaks Game",
            value="```" +
                  f"Total Players: {gas_stats.get('total_players', 'N/A')}\n" +
                  f"Games Completed: {gas_stats.get('games_completed', 'N/A')}\n" +
                  f"Total BURP Won: {gas_stats.get('total_ada_won', 'N/A')}" +
                  "```",
            inline=True
        )
        
        # Pool Stats
        pool_stats = stats_data.get("prize_pools", {})
        embed.add_field(
            name="Pool Stats",
            value="```" +
                  f"Current Pool: {pool_stats.get('total_active', 'N/A')} BURP\n" +
                  f"Total Contributions: {pool_stats.get('total_contributions', 'N/A')}\n" +
                  f"Total BURP Contributions: {pool_stats.get('total_burp_contributions', 'N/A')} BURP" +
                  "```",
            inline=True
        )
        
        # Recent Activity
        activity_stats = stats_data.get("recent_activity", {})
        embed.add_field(
            name="Recent Activity",
            value="```" +
                  f"Last Winner: {activity_stats.get('last_winner', 'N/A')}\n" +
                  f"Last Game: {activity_stats.get('last_game', 'N/A')}\n" +
                  f"Amount Won: {activity_stats.get('last_amount_won', 'N/A')}" +
                  "```",
            inline=False
        )
        
        # Edit the loading message with the stats
        await loading_msg.edit(content=None, embed=embed)
        logger.info(f"Stats command used by {ctx.author.name}")
        
    except Exception as e:
        logger.error(f"Error in stats command: {e}")
        try:
            await loading_msg.edit(content="❌ Error retrieving statistics. Please try again later.")
        except:
            await ctx.send("❌ Error retrieving statistics. Please try again later.", delete_after=5)

# Old verification command removed - now using button system

@bot.event
async def on_message(message):
    """Handle auto-moderation and other messages"""
    if message.author.bot:
        return
    
    # Check for Discord invite links (auto-moderation)
    if auto_mod_enabled and burp_bot.contains_discord_invite(message.content):
        # Skip moderation for the designated admin user
        if message.author.id != ADMIN_USER_ID:
            await burp_bot.handle_discord_invite(message)
            return  # Don't process further if message was moderated
    
    # Verification is now handled by button interactions
    
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

@bot.command(name='dbschema', hidden=True)
@is_admin_user()
async def db_schema_command(ctx):
    """Admin command to check database schema"""
    try:
        if not burp_bot.db_pool:
            await ctx.send("❌ Database not connected")
            return
        
        loading_msg = await ctx.send("🔍 Checking database schema...")
        
        async with burp_bot.db_pool.acquire() as conn:
            # Get all tables
            tables = await conn.fetch(
                """SELECT table_name 
                   FROM information_schema.tables 
                   WHERE table_schema = 'public' 
                   ORDER BY table_name"""
            )
            
            if not tables:
                await loading_msg.edit(content="ℹ️ No tables found in database")
                return
            
            embed = discord.Embed(
                title="Database Schema",
                description="Available tables in your database:",
                color=0x0099ff
            )
            
            table_list = []
            for table in tables:
                table_name = table['table_name']
                table_list.append(f"• {table_name}")
                
                # Get column info for each table
                columns = await conn.fetch(
                    """SELECT column_name, data_type 
                       FROM information_schema.columns 
                       WHERE table_name = $1 
                       ORDER BY ordinal_position""",
                    table_name
                )
                
                column_info = []
                for col in columns[:5]:  # Show first 5 columns
                    column_info.append(f"{col['column_name']} ({col['data_type']})")
                
                if len(columns) > 5:
                    column_info.append(f"... and {len(columns) - 5} more")
                
                embed.add_field(
                    name=f"Table: {table_name}",
                    value="```" + "\n".join(column_info) + "```",
                    inline=False
                )
            
            await loading_msg.edit(content=None, embed=embed)
            
    except Exception as e:
        await ctx.send(f"❌ Error checking schema: {e}")
        logger.error(f"Error in db_schema_command: {e}")

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
            # First, let's see what tables exist
            tables = await conn.fetch(
                """SELECT table_name 
                   FROM information_schema.tables 
                   WHERE table_schema = 'public' 
                   AND table_name LIKE '%game%' OR table_name LIKE '%winner%' OR table_name LIKE '%streak%'
                   ORDER BY table_name"""
            )
            
            if not tables:
                await loading_msg.edit(content="❌ No game-related tables found. Use `!dbschema` to see all tables.")
                return
            
            embed = discord.Embed(
                title="Database Tables Found",
                description="Game-related tables in your database:",
                color=0x00ff00
            )
            
            for table in tables:
                table_name = table['table_name']
                
                # Try to get some sample data
                try:
                    sample_data = await conn.fetch(f"SELECT * FROM {table_name} LIMIT 3")
                    embed.add_field(
                        name=f"Table: {table_name}",
                        value=f"Rows found: {len(sample_data)}",
                        inline=True
                    )
                except Exception as e:
                    embed.add_field(
                        name=f"Table: {table_name}",
                        value=f"Error: {str(e)[:50]}...",
                        inline=True
                    )
            
            embed.add_field(
                name="Next Steps",
                value="Use `!dbschema` to see full database structure",
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
