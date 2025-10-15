# -*- coding: utf-8 -*-

import os
import discord
import requests
from discord.ext import commands

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
RENDER_WEBHOOK = "https://fatbot-nansen-webhook.onrender.com/nansen"
NANSEN_CHANNEL_ID = int(os.environ.get("NANSEN_CHANNEL_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"🎯 Watching channel ID: {NANSEN_CHANNEL_ID}")

@bot.event
async def on_message(message):
    # ignoruj správy od seba
    if message.author == bot.user:
        return

    print(f"📩 Received message in channel {message.channel.id} from {message.author}: {message.content}")

    # sleduj len Nansen kanál
    if message.channel.id != NANSEN_CHANNEL_ID:
        print("⏭️ Skipping - not the Nansen channel.")
        return

    content = message.content
    embeds = [embed.to_dict() for embed in message.embeds]
    payload = {"content": content, "embeds": embeds}

    try:
        resp = requests.post(RENDER_WEBHOOK, json=payload, timeout=5)
        print(f"➡️ Sent to Render: {resp.status_code}")
    except Exception as e:
        print(f"❌ Error sending to Render: {e}")

bot.run(TOKEN)

