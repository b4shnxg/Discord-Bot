Discord Moderation & Utilities Bot 

A modern Discord bot focused on moderation, tickets, giveaways, anti-link, AFK, levels, embeds, and server utilities.  
Built with discord.py 2.x and asyncio.

------------------------------------------------------------
✨ FEATURES
------------------------------------------------------------
- Help UI with category selector.
- Moderation: purge, nuke, ban, kick, unban, lock/unlock, slowmode, warns.
- Tickets with claim/close buttons (auto-category detection).
- Giveaways with join button, end, reroll, and auto-updater.
- Anti-link filter with whitelist and status.
- AFK system with auto-clear and mention notices.
- Leveling (per-message XP) + rank + top + admin levelset / levelreset.
- User & server info: avatars, banners, role info, server info, icons.
- Embed Builder interactive UI to craft/sent embeds to channels.
- Utilities: say, ping (latency), uptime, botinfo (memory, uptime).

Persistent data files are stored locally:
- levels.json, warns.json, antilink.json.

------------------------------------------------------------
🧰 REQUIREMENTS
------------------------------------------------------------
- Python 3.10+ (recommended 3.11+)
- Discord bot with Privileged Gateway Intents enabled:
  - SERVER MEMBERS INTENT
  - MESSAGE CONTENT INTENT

Install dependencies:
    pip install -r requirements.txt

requirements.txt:
    discord.py>=2.3.2,<3.0.0
    python-dotenv>=1.0.1
    aiohttp>=3.9.1
    psutil>=5.9.8

------------------------------------------------------------
🔐 ENVIRONMENT VARIABLES (.env)
------------------------------------------------------------
Create a .env file in the project root:

    DISCORD_TOKEN=your_bot_token_here
    BOT_PREFIX=!
    THUMB_URL=https://example.com/thumb.png
    BANNER_URL=https://example.com/banner.png

The code uses python-dotenv to load variables automatically.

------------------------------------------------------------
▶️ RUNNING THE BOT
------------------------------------------------------------
1. Enable Intents in the Discord Developer Portal.
2. Invite the bot to your server with adequate permissions.
3. Run:
    python bot.py

Expected console output:
    Bot connected as <botname#1234>

------------------------------------------------------------
🧩 PERMISSIONS & INTENTS CHECKLIST
------------------------------------------------------------
- Bot role above roles you want to moderate.
- Channel permissions: View, Send, Manage Messages, Manage Channels.
- Developer Portal: SERVER MEMBERS INTENT and MESSAGE CONTENT INTENT ON.

------------------------------------------------------------
📁 DATA FILES
------------------------------------------------------------
- levels.json — message counts and levels
- warns.json — warnings
- antilink.json — anti-link settings

------------------------------------------------------------
🧪 COMMAND REFERENCE (summary)
------------------------------------------------------------
Help: !help  
Moderation: !purge, !nuke, !ban, !kick, !unban, !warn, !warnings, !warnremove, !lock, !unlock, !slowmode  
Tickets: !ticket  
Giveaways: !gwstart, !gwend, !gwreroll  
Anti-link: !antilink on/off/status/whitelist  
AFK: !afk  
Levels: !rank, !top, !levelset, !levelreset  
User info: !userinfo, !avatar, !banner, !roleinfo, !serverinfo, !servericon  
Utilities: !say, !ping, !uptime, !botinfo, !embedbuilder

------------------------------------------------------------
🧭 NOTES
------------------------------------------------------------
Keep .env secret and add to .gitignore.
Ensure JSON files are writable in the working directory.
Confirm all required permissions for full functionality.

------------------------------------------------------------
📜 LICENSE
------------------------------------------------------------
Created by Slasher B4sh, NXG Team
