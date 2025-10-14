from flask import Flask, request, jsonify
import os, hmac, hashlib, requests, json
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
NANSEN_SECRET = os.environ.get("NANSEN_SECRET")

@app.route('/api/webhooks/<webhook_id>/<webhook_token>', methods=['POST'])
@app.route('/discord.com/api/webhooks/<webhook_id>/<webhook_token>', methods=['POST'])
def handle_webhook(webhook_id, webhook_token):

def discord_compatible_webhook(webhook_id, webhook_token):
    try:
        data = request.get_json()

        # 🔒 Overenie podpisu (ak Nansen posiela)
        signature = request.headers.get("X-Nansen-Signature")
        if NANSEN_SECRET and signature:
            computed = hmac.new(NANSEN_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(computed, signature):
                return jsonify({"error": "Invalid signature"}), 401

        # 🧠 Základná validácia
        if not data or "alerts" not in data:
            return jsonify({"status": "ignored"}), 200

        title = data.get("title", "Smart Alert")
        alerts = data["alerts"]

        description = ""
        for a in alerts:
            symbol = a.get("symbol", "Unknown")
            inflow = a.get("inflow", 0)
            receivers = a.get("receivers", 0)
            vol = a.get("volume", "?")
            mc = a.get("market_cap", "?")
            age = a.get("age", "?")
            url = a.get("url", "")

            # 🔁 Prepis URL z Nansenu na FatBot
            fatbot_url = ""
            if "tokenAddress" in url:
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                token_address = qs.get("tokenAddress", [""])[0]
                chain = qs.get("chain", ["SOLANA"])[0].upper()
                fatbot_url = f"https://fatbot.fatty.io/manual-trading/{chain}/{token_address}"

            description += f"**[{symbol}]({fatbot_url})**\n💸 Inflow: `${inflow:,.2f}` | 🧠 {receivers} receivers (24h)\n📊 Vol: {vol} | MC: {mc} | ⏳ Age: {age}\n\n"

        # 📩 Poslanie do reálneho Discord kanála
        payload = {
            "embeds": [{
                "title": title,
                "description": description,
                "color": 5814783
            }]
        }

        headers = {"Content-Type": "application/json"}
        requests.post(DISCORD_WEBHOOK, headers=headers, data=json.dumps(payload))

        # ✅ Vraciame Discord-like odpoveď, aby bol Nansen spokojný
        return "", 204

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/')
def index():
    return jsonify({"status": "ok"}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
