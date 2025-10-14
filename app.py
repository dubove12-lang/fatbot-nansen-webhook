import os
import hmac
import hashlib
from flask import Flask, request, jsonify
import requests
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

# 🔧 Konfigurácia – všetko si ťahá z Render Environment Variables
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
NANSEN_SECRET = os.environ.get("NANSEN_SECRET")

@app.route('/nansen', methods=['POST'])
def nansen_webhook():
    # ✅ 1. Overenie HMAC podpisu
    signature = request.headers.get("X-Nansen-Signature")
    body = request.data
    expected_sig = "sha256=" + hmac.new(
        NANSEN_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        return jsonify({"error": "invalid signature"}), 401

    data = request.get_json()
    if not data or "alerts" not in data:
        return jsonify({"error": "invalid payload"}), 400

    title = data.get("title", "Nansen Smart Alert")
    alerts = data["alerts"]

    # ✅ 2. Prepis linkov Nansen → FatBot (zachová token CA)
    for alert in alerts:
        try:
            url = alert["url"]
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            token_address = params.get("tokenAddress", [""])[0]
            chain = params.get("chain", ["solana"])[0].upper()
            # Prepis URL na FatBot formát
            alert["url"] = f"https://fatbot.fatty.io/manual-trading/{chain}/{token_address}"
        except Exception:
            continue

    # ✅ 3. Vytvorenie Discord EMBED – ako originálny Nansen formát
    embed = {
        "title": title,
        "color": 0x5865F2,  # Nansen štýl (Discord modrá)
        "fields": [],
        "footer": {
            "text": "FatBot Smart Alerts ⚡ powered by Nansen.ai"
        }
    }

    # ✅ 4. Vloženie jednotlivých tokenov
    for alert in alerts:
        field = {
            "name": f"{alert['symbol']}",
            "value": (
                f"🧠 **Inflow:** ${alert['inflow']:,} | **Receivers:** {alert['receivers']} (24h)\n"
                f"💰 **Vol:** {alert['volume']} | **MC:** {alert['market_cap']} | **Age:** {alert['age']}\n"
                f"[🔗 View on FatBot]({alert['url']})"
            ),
            "inline": False
        }
        embed["fields"].append(field)

    # ✅ 5. (Voliteľne) Pridanie odkazov dole ako Nansen
    embed["description"] = "[Solana](https://fatbot.fatty.io) | [View Dashboard](https://fatbot.fatty.io/dashboard) | [Edit alert](https://fatbot.fatty.io/alerts)"

    # ✅ 6. Odoslanie na Discord webhook
    payload = {"embeds": [embed]}
    resp = requests.post(DISCORD_WEBHOOK, json=payload)

    if resp.status_code >= 400:
        return jsonify({"error": "discord failed", "details": resp.text}), 500

    return jsonify({"status": "ok"}), 200


@app.route('/')
def home():
    return "FatBot relay running", 200


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
