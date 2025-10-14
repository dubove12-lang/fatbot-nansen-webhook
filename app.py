from flask import Flask, request, jsonify
import os, hmac, hashlib, requests, json
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
NANSEN_SECRET = os.environ.get("NANSEN_SECRET")

# ✅ Podpora pre obe formy webhookov (klasický aj Discord.com)
@app.route('/api/webhooks/<webhook_id>/<webhook_token>', methods=['POST'])
@app.route('/discord.com/api/webhooks/<webhook_id>/<webhook_token>', methods=['POST'])
def handle_webhook(webhook_id, webhook_token):
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "No data received"}), 400

        # 🔒 Overenie podpisu (ak Nansen používa X-Nansen-Signature)
        signature = request.headers.get("X-Nansen-Signature")
        if NANSEN_SECRET and signature:
            computed = hmac.new(NANSEN_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(computed, signature):
                return jsonify({"error": "Invalid signature"}), 401

        # 🔹 Ak chýba pole alerts, nič nerobíme
        if "alerts" not in data:
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

            # 🔁 Prepíš URL z Nansenu na FatBot link
            fatbot_url = url  # fallback

            if "tokenAddress=" in url:
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                token_address = qs.get("tokenAddress", [""])[0]
                chain = qs.get("chain", ["solana"])[0].upper()
                fatbot_url = f"https://fatbot.fatty.io/manual-trading/{chain}/{token_address}"

            elif "/token/" in url:
                token_address = url.split("/token/")[1].split("?")[0]
                fatbot_url = f"https://fatbot.fatty.io/manual-trading/SOLANA/{token_address}"

            # 🧩 Embed text
            description += (
                f"**[{symbol}]({fatbot_url})**\n"
                f"💸 Inflow: `${inflow:,.2f}` | 🧠 {receivers} wallets\n"
                f"📊 Vol: {vol} | MC: {mc} | ⏳ Age: {age}\n\n"
            )

        # 📩 Poslanie embed správy do reálneho Discord kanála
        payload = {
            "embeds": [{
                "title": title,
                "description": description.strip(),
                "color": 5814783
            }]
        }

        headers = {"Content-Type": "application/json"}
        r = requests.post(DISCORD_WEBHOOK, headers=headers, data=json.dumps(payload))

        print(f"Sent to Discord ({r.status_code})")
        return "", 204  # Nansen očakáva 204 ako OK odpoveď

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/')
def index():
    return jsonify({"status": "ok"}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)


