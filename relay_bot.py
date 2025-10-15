# -*- coding: utf-8 -*-

# -- Sheet --

import os
import discord
import requests
from discord.ext import commands

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
RENDER_WEBHOOK = "https://fatbot-nansen-webhook.onrender.com/nansen"

# ID kanála, kde Nansen posiela alerty
NANSEN_CHANNEL_ID = 123456789012345678  # <- tu vlož ID kanála

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_message(message):
    # ignoruj správy od seba
    if message.author == bot.user:
        return

    # sleduj len Nansen kanál
    if message.channel.id != NANSEN_CHANNEL_ID:
        return

    # vytiahni obsah správy (text + embed)
    content = message.content
    embeds = [embed.to_dict() for embed in message.embeds]

    payload = {"content": content, "embeds": embeds}

    # odošli na Render webhook
    try:
        resp = requests.post(RENDER_WEBHOOK, json=payload)
        print(f"➡️ Sent to Render: {resp.status_code}")
    except Exception as e:
        print(f"❌ Error sending to Render: {e}")

bot.run(TOKEN)

