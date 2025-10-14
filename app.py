# -*- coding: utf-8 -*-

# -- Sheet --

# app.py
import os
import re
import hmac
import hashlib
import json
import logging
from time import time
from flask import Flask, request, jsonify, abort
import requests
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Basic logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Rate limiter (config from env)
limiter = Limiter(app, key_func=get_remote_address, default_limits=[os.environ.get("RATE_LIMIT", "60/minute")])

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")  # put in Render env
NANSEN_SECRET = os.environ.get("NANSEN_SECRET", "").encode()  # shared secret for HMAC
MAX_BODY = int(os.environ.get("MAX_BODY", 100_000))  # bytes
ALLOWED_CHAINS = {c.strip().lower() for c in os.environ.get("ALLOWED_CHAINS", "solana,ethereum").split(",")}

# regex for token-god-mode links with tokenAddress and chain
pattern = re.compile(
    r"https:\/\/app\.nansen\.ai\/token-god-mode\?tokenAddress=([A-Za-z0-9]{8,128})&chain=([a-zA-Z0-9_-]+)",
    flags=re.IGNORECASE
)

def verify_hmac(header_sig: str, body: bytes) -> bool:
    """Verify HMAC SHA256 signature from Nansen"""
    if not NANSEN_SECRET:
        logging.warning("No NANSEN_SECRET set — rejecting request")
        return False
    if not header_sig:
        return False
    # header_sig can be hex or prefixed like "sha256=..."
    if header_sig.startswith("sha256="):
        header_sig = header_sig.split("=", 1)[1]
    mac = hmac.new(NANSEN_SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, header_sig)

def sanitize_text(text: str) -> str:
    if not text:
        return text
    # prevent mass mentions
    text = text.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
    # trim length to safe size (Discord embed limits apply)
    if len(text) > 4000:
        text = text[:3997] + "..."
    return text

def replace_nansen_links(text: str) -> str:
    def repl(m):
        token = m.group(1)
        chain = m.group(2).lower()
        if chain not in ALLOWED_CHAINS:
            logging.info("Chain not allowed: %s", chain)
            return m.group(0)  # leave original or drop
        token = token[:120]
        return f"https://fatbot.fatty.io/manual-trading/{chain.upper()}/{token}"
    return re.sub(pattern, repl, text)

@app.route("/", methods=["GET"])
def home():
    return "FatBot relay running"

@app.route("/nansen", methods=["POST"])
@limiter.limit(os.environ.get("ENDPOINT_RATE_LIMIT", "20/minute"))
def handle_nansen():
    # size check
    try:
        length = int(request.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            logging.warning("Payload too large: %s", length)
            return ("Payload too large", 413)
    except ValueError:
        pass

    body = request.get_data()
    sig_header = request.headers.get("X-Nansen-Signature") or request.headers.get("X-Signature") or ""

    # verify HMAC; if missing/invalid -> reject
    if not verify_hmac(sig_header, body):
        logging.warning("Invalid HMAC from %s", request.remote_addr)
        return ("Unauthorized", 401)

    # parse JSON safely
    try:
        data = request.get_json(force=True)
    except Exception as e:
        logging.exception("Invalid JSON")
        return ("Bad Request", 400)

    content = data.get("content", "")
    embeds = data.get("embeds", [])

    # replace links in content and embeds; sanitize
    content = sanitize_text(replace_nansen_links(content))

    # fix embeds fields (title, description, url, fields -> value)
    safe_embeds = []
    for embed in embeds:
        new = {}
        for k, v in embed.items():
            if isinstance(v, str):
                v2 = sanitize_text(replace_nansen_links(v))
                new[k] = v2
            elif isinstance(v, list):
                # for fields array
                new_list = []
                for item in v:
                    if isinstance(item, dict):
                        item_copy = {}
                        for ik, iv in item.items():
                            if isinstance(iv, str):
                                item_copy[ik] = sanitize_text(replace_nansen_links(iv))
                            else:
                                item_copy[ik] = iv
                        new_list.append(item_copy)
                    else:
                        new_list.append(item)
                new[k] = new_list
            else:
                new[k] = v
        safe_embeds.append(new)

    payload = {"content": content, "embeds": safe_embeds}

    # send to discord with timeout, handle rate limit via simple backoff
    try:
        resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=5)
        if resp.status_code // 100 != 2:
            logging.warning("Discord webhook returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logging.exception("Failed to post to Discord")
        return ("Upstream error", 502)

    return jsonify({"status": "ok"})

