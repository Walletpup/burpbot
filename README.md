# Burp Discord Bot 🤖

A comprehensive Discord bot for the Burp community featuring Gas Streaks winner announcements, verification system, welcome messages, and more!

## Features

- 🎉 **Gas Streaks Winner Announcements** - Automatically posts winners to the burp-winners channel
- 🆕 **New Prize Pool Notifications** - Announces new prize pools when they're created
- 🔐 **Verification System** - Random number challenge to grant @Burper role
- 👋 **Welcome Messages** - Beautiful embeds with user avatars for new members
- 🔗 **Links Channel** - Auto-posts community links on bot startup
- 🚫 **Auto-Moderation** - Automatically deletes Discord invite links (excludes admin user: 1419117925465460878)
- 📡 **Webhook Integration** - HTTP endpoints for external app integration

## Channel Configuration

The bot is configured for these specific channels:

- **Burp Winners**: `1420198836768346244`
- **New Prize Pools**: `1420198889918566541`
- **Verification**: `1419189311139614841`
- **Welcome**: `1419154118085181523`
- **Links**: `1419154016448938004`

## Setup Instructions

### 1. Discord Bot Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to "Bot" section and create a bot
4. Copy the bot token (you'll need this for `DISCORD_BOT_TOKEN`)
5. Under "Privileged Gateway Intents", enable:
   - Message Content Intent
   - Server Members Intent
   - Presence Intent

### 2. Bot Permissions

Invite the bot to your server with these permissions:
- Send Messages
- Embed Links
- Read Message History
- Manage Roles
- Use Slash Commands
- View Channels

**Invite URL Template:**
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_BOT_CLIENT_ID&permissions=268437504&scope=bot
```

### 3. Heroku Deployment

1. Create a new Heroku app
2. Connect your GitHub repository or use Heroku CLI
3. Set the following environment variables in Heroku Config Vars:

## Environment Variables

Set these in your Heroku Config Vars:

| Variable Name | Description | Required |
|---------------|-------------|----------|
| `DISCORD_BOT_TOKEN` | Your Discord bot token | ✅ Yes |
| `DISCORD_WEBHOOK_URL` | Your Heroku app URL (for webhooks) | ⚠️ Optional* |
| `GAS_STREAKS_API_URL` | Your Gas Streaks API endpoint for stats | ⚠️ Optional** |

*Optional but recommended for Gas Streaks integration  
**Optional - if not provided, bot will use fallback stats

### Example Config Vars Setup:

```bash
# In Heroku Config Vars:
DISCORD_BOT_TOKEN=your_discord_bot_token_here
DISCORD_WEBHOOK_URL=https://your-bot-app.herokuapp.com
```

### 4. Role Setup

Make sure your Discord server has a role named **"Burper"** that will be assigned during verification.

1. Go to Server Settings → Roles
2. Create a role named exactly "Burper"
3. Set appropriate permissions for this role
4. Make sure the bot's role is higher than the "Burper" role in the hierarchy

## Commands

### User Commands

- `!stats` - Show Gas Streaks and Burp community statistics (available to everyone)
- `!verify` - Start the verification process (only works in verification channel)

### Admin Commands (Restricted to specific admin user: 1419117925465460878)

- `!announce_winner <winner_address>|<prize_amount>|<streak_length>|<game_id>` - Test winner announcement
- `!announce_pool <total_prize>|<game_id>` - Test prize pool announcement
- `!automod [on/off/status]` - Control auto-moderation of Discord invite links
- `!testinvite` - Test the invite link detection system

### Example Admin Commands:

```
!announce_winner addr1test123|150|7|game-abc-123
!announce_pool 500|new-game-456
!automod on
!automod status
!testinvite
```

## Gas Streaks Integration

To integrate with your Gas Streaks app, use the webhook endpoints:

### Winner Announcement
```http
POST /webhook/winner
Content-Type: application/json

{
  "winner_address": "addr1...",
  "prize_amount": "150",
  "streak_length": "7",
  "game_id": "game-abc-123"
}
```

### New Prize Pool Announcement
```http
POST /webhook/new_pool
Content-Type: application/json

{
  "total_prize": "500",
  "game_id": "new-game-456"
}
```

### Integration Example

Add this to your Gas Streaks backend:

```python
import requests

def announce_winner_to_discord(winner_data):
    webhook_url = "https://your-bot-app.herokuapp.com/webhook/winner"
    
    payload = {
        "winner_address": winner_data["address"],
        "prize_amount": str(winner_data["prize"]),
        "streak_length": str(winner_data["streak"]),
        "game_id": winner_data["game_id"]
    }
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        if response.status_code == 200:
            print("Winner announced to Discord!")
    except Exception as e:
        print(f"Error announcing to Discord: {e}")
```

## Stats API Integration

The `!stats` command can fetch real-time data from your Gas Streaks API. Create an endpoint that returns JSON in this format:

### Stats API Endpoint

**GET** `/api/stats`

**Response Format:**
```json
{
  "gas_streaks": {
    "active_games": 3,
    "total_players": 1247,
    "games_completed": 89,
    "total_ada_won": "12,450"
  },
  "prize_pools": {
    "pools": [450, 320, 180],
    "total_active": "950"
  },
  "community": {
    "discord_members": 1500,
    "verified_burpers": 892,
    "online_now": 234,
    "bot_status": "Online ✅"
  },
  "recent_activity": {
    "last_winner": "2 hours ago",
    "last_game": "45 minutes ago", 
    "new_members_today": 12,
    "messages_today": 234
  }
}
```

Set the `GAS_STREAKS_API_URL` environment variable to your stats endpoint. If not provided, the bot will use fallback stats with Discord-only data.

## File Structure

```
discord-bot/
├── bot.py                    # Main bot file
├── webhook_integration.py    # Integration helper
├── requirements.txt          # Python dependencies
├── Procfile                 # Heroku process file
├── runtime.txt              # Python version
└── README.md                # This file
```

## Deployment Steps

1. **Prepare files**: All files are ready in the `discord-bot` folder
2. **Create Heroku app**: `heroku create your-bot-name`
3. **Set environment variables**: Add `DISCORD_BOT_TOKEN` in Heroku Config Vars
4. **Deploy**: Push to Heroku or connect GitHub repository
5. **Scale worker**: `heroku ps:scale worker=1`

## Troubleshooting

### Bot not responding
- Check if `DISCORD_BOT_TOKEN` is set correctly
- Verify bot permissions in Discord server
- Check Heroku logs: `heroku logs --tail`

### Verification not working
- Ensure "Burper" role exists and bot can manage it
- Check bot role hierarchy (bot role must be higher than "Burper")
- Verify the verification channel ID is correct

### Webhooks not working
- Ensure `DISCORD_WEBHOOK_URL` is set to your Heroku app URL
- Check that your Gas Streaks app can reach the webhook endpoints
- Verify the JSON payload format matches the expected structure

## Support

If you encounter any issues:

1. Check Heroku logs for error messages
2. Verify all environment variables are set correctly
3. Ensure Discord permissions are properly configured
4. Test with admin commands first before integrating webhooks

## Security Notes

- Never commit your Discord bot token to version control
- Use Heroku Config Vars for all sensitive information
- The webhook endpoints are public - consider adding authentication if needed
- Regularly rotate your Discord bot token for security

---

**Happy Burping! 🎉**
