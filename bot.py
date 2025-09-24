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
    "🌐 Official Website": "https://www.burpcoin.site/",
    "🎮 Gas Streaks Game": "https://www.burpcoin.site/gas-streaks",
    "🐦 Twitter/X": "https://x.com/burpcoinada"
}

class BurpBot:
    def __init__(self, bot):
        self.bot = bot
    
    async def fetch_gas_streaks_stats(self):
        """Fetch real-time stats from Gas Streaks API"""
        try:
            # You can replace this URL with your actual Gas Streaks API endpoint
            api_url = os.environ.get('GAS_STREAKS_API_URL', 'https://your-gas-streaks-api.com/api/stats')
            
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Failed to fetch stats from API: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching stats from API: {e}")
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
                "bot_status": "Online ✅"
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
    
    # Send links embed to links channel
    await send_links_embed()
    
    # Set bot status
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Gas Streaks Winners 🎉"
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

@bot.command(name='stats')
async def stats_command(ctx):
    """Show Gas Streaks and Burp statistics - available to everyone"""
    try:
        # Send a "loading" message first
        loading_msg = await ctx.send("📊 Fetching latest statistics...")
        
        # Try to fetch real stats from API
        stats_data = await burp_bot.fetch_gas_streaks_stats()
        
        # If API fails, use fallback stats
        if not stats_data:
            stats_data = burp_bot.get_fallback_stats(ctx.guild)
        
        embed = discord.Embed(
            title="📊 Burp Gas Streaks Statistics",
            description="Current statistics for the Burp community and Gas Streaks game",
            color=0x00ff6b,
            timestamp=datetime.utcnow()
        )
        
        # Gas Streaks Stats
        gas_stats = stats_data.get("gas_streaks", {})
        embed.add_field(
            name="🎮 Gas Streaks Game",
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
            name="💰 Current Prize Pools",
            value="```" +
                  pool_text + "\n" +
                  f"Total Active: {pool_stats.get('total_active', 'N/A')} ADA" +
                  "```",
            inline=True
        )
        
        # Community Stats
        community_stats = stats_data.get("community", {})
        embed.add_field(
            name="👥 Community Stats",
            value="```" +
                  f"Discord Members: {community_stats.get('discord_members', len(ctx.guild.members))}\n" +
                  f"Verified Burpers: {community_stats.get('verified_burpers', 'N/A')}\n" +
                  f"Online Now: {community_stats.get('online_now', 'N/A')}\n" +
                  f"Bot Status: {community_stats.get('bot_status', 'Online ✅')}" +
                  "```",
            inline=False
        )
        
        # Recent Activity
        activity_stats = stats_data.get("recent_activity", {})
        embed.add_field(
            name="🔥 Recent Activity",
            value="```" +
                  f"Last Winner: {activity_stats.get('last_winner', 'N/A')}\n" +
                  f"Last Game: {activity_stats.get('last_game', 'N/A')}\n" +
                  f"New Members: {activity_stats.get('new_members_today', 'N/A')} today\n" +
                  f"Messages: {activity_stats.get('messages_today', 'N/A')} today" +
                  "```",
            inline=True
        )
        
        # Game Instructions
        embed.add_field(
            name="🎯 How to Play",
            value="Send **1.5 ADA + 1 BURP** to participate!\nGet **1 ADA refunded** automatically!",
            inline=True
        )
        
        # Links
        embed.add_field(
            name="🔗 Quick Links",
            value="[🌐 Website](https://www.burpcoin.site/) • [🎮 Play Gas Streaks](https://www.burpcoin.site/gas-streaks) • [🐦 Twitter](https://x.com/burpcoinada)",
            inline=False
        )
        
        # Add data source indicator
        data_source = "🟢 Live Data" if stats_data != burp_bot.get_fallback_stats(ctx.guild) else "🟡 Cached Data"
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
            title="🔗 Burp Community Links",
            description="Here are all the important links for our community!",
            color=0xff6b35,
            timestamp=datetime.utcnow()
        )
        
        for name, url in BURP_LINKS.items():
            embed.add_field(
                name=name,
                value=f"[Click Here]({url})",
                inline=True
            )
        
        embed.add_field(
            name="💡 About Burp",
            value="Burp is a community-driven project on Cardano featuring Gas Streaks - an exciting game where you can win ADA!",
            inline=False
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
