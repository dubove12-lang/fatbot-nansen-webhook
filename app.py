import os
import json
import hmac
import hashlib
from urllib.parse import urlparse, parse_qs

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ← nastav tieto v Render / Environment Variables
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")  # reálny Discord webhook (kam chceme poslať finálnu správu)
NANSEN_SECRET = os.environ.get("NANSEN_SECRET")      # voliteľné, na overenie podpisu od Nansenu

# Helper: pokúsi sa extrahovať token address a chain z rôznych URL formátov
def convert_to_fatbot(url: str) -> str:
    if not url or not isinstance(url, str):
        return url

    # fallback = originál, ak sa nič nenájde
    fatbot_url = url

    try:
        # 1) query param style: ?tokenAddress=...&chain=...
        if "tokenAddress=" in url:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            token_address = qs.get("tokenAddress", [""])[0]
            chain = qs.get("chain", ["solana"])[0].upper()
            if token_address:
                fatbot_url = f"https://fatbot.fatty.io/manual-trading/{chain}/{token_address}"
                return fatbot_url

        # 2) path style: /token/<address> or /token/<address>/
        if "/token/" in url:
            token_address = url.split("/token/")[1].split("?")[0].split("/")[0]
            if token_address:
                # assume solana unless chain present
                chain = "SOLANA"
                fatbot_url = f"https://fatbot.fatty.io/manual-trading/{chain}/{token_address}"
                return fatbot_url

        # 3) sometimes Nansen uses /address/<address> or other variants
        # try to find 44+ char base58 Solana-looking or 40-64 hex-looking fragment
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        for part in reversed(path_parts):
            # quick heuristic: solana CA (~44 chars base58) or ethereum hex (0x...)
            if len(part) >= 40:
                token_address = part
                chain = "SOLANA"
                fatbot_url = f"https://fatbot.fatty.io/manual-trading/{chain}/{token_address}"
                return fatbot_url

    except Exception:
        # v prípade chyby necháme originálnu URL (fail-safe)
        return url

    return fatbot_url


# Hlavný handler — zachytí volania v oboch tvaroch (lokálny aj "discord.com" prefix)
@app.route('/api/webhooks/<webhook_id>/<webhook_token>', methods=['POST'])
@app.route('/discord.com/api/webhooks/<webhook_id>/<webhook_token>', methods=['POST'])
def webhook_proxy(webhook_id, webhook_token):
    try:
        # načítaj JSON payload (force=True aby sme nezlyhali na type)
        data = request.get_json(force=True, silent=True)
        if data is None:
            # ak nie je JSON, vrátime 400 (ale Nansen/Discord očakáva 204/200 pri úspechu)
            return jsonify({"error": "no json"}), 400

        # DEBUG: logni celý payload (pomôže pri ladení)
        print("=== NANSEN PAYLOAD ===")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print("=======================")

        # Overenie podpisu (voliteľné) — Nansen môže posielať header X-Nansen-Signature
        signature_header = request.headers.get("X-Nansen-Signature") or request.headers.get("X-Signature")
        if NANSEN_SECRET and signature_header:
            # header môže mať tvar 'sha256=...' alebo len hex
            sig = signature_header.split("=", 1)[-1] if "=" in signature_header else signature_header
            computed = hmac.new(NANSEN_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(computed, sig):
                print("Invalid signature: received", sig, "computed", computed)
                return jsonify({"error": "invalid signature"}), 401

        # Kód očakáva pole 'alerts' (ak ho niektoré typy alertov nemajú, spravíme fallback)
        alerts = data.get("alerts", None)

        # Ak nie je alerts, niektoré Nansen payloads majú iné polia - skúsme nájsť token linky hoci kde
        if not alerts:
            # pokúsime sa normalizovať: ak data obsahuje políčko 'items' alebo 'results', skúsiť ich
            if "items" in data and isinstance(data["items"], list):
                alerts = data["items"]
            elif "results" in data and isinstance(data["results"], list):
                alerts = data["results"]
            else:
                # ak nevidíme žiadne zoznamy, pošleme originálny payload ďalej bez úprav
                alerts = []

        # Pre každý alert: nájdi URL polia a pokús sa ho prebudovať na FatBot URL
        # Podporujeme rôzne tvary: alert["url"], alert["link"], alert["tokenUrl"], alert["dashboardUrl"], atď.
        for a in alerts:
            if not isinstance(a, dict):
                continue

            # najpravdepodobnejšie polia kde môže byť link
            candidate_keys = ["url", "link", "tokenUrl", "dashboardUrl", "dashboard_url", "token_url", "explorer", "href"]
            for key in candidate_keys:
                if key in a and isinstance(a[key], str) and a[key]:
                    new = convert_to_fatbot(a[key])
                    # ak sa prepísalo (nová adresa sa líši), ulož ju
                    if new and new != a[key]:
                        a[key] = new
                    # tiež nastav unify field 'url' pre neskoršie použitie
                    a["url"] = a.get("url", new)
                    break
            else:
                # žiadny candidate key neobsahoval URL — skús nájsť v celom dict-e stringy pripomínajúce token address
                for v in a.values():
                    if isinstance(v, str) and ("tokenAddress=" in v or "/token/" in v or "app.nansen.ai/token" in v):
                        new = convert_to_fatbot(v)
                        if new != v:
                            a["url"] = new
                            break

        # Teraz zložíme embed / payload, ktorý pošleme do skutočného Discordu.
        # Tu môžeme buď poslať celý JSON "data" ďalej, alebo vytvoriť embed podobný Nansen.
        # Vytvoríme embed text (riadky) tak, aby vizuálne vyzeral pekne.
        title = data.get("title") or data.get("heading") or "Nansen Smart Alert"
        description_lines = []

        for a in alerts:
            if not isinstance(a, dict):
                continue
            symbol = a.get("symbol") or a.get("name") or a.get("token") or "Unknown"
            url_for_link = a.get("url") or a.get("link") or ""
            inflow = a.get("inflow")
            receivers = a.get("receivers")
            vol = a.get("volume") or a.get("vol") or a.get("volume_24h") or "?"
            mc = a.get("market_cap") or a.get("mc") or a.get("marketCap") or "?"
            age = a.get("age") or a.get("age_text") or a.get("ageStr") or "?"

            # format inflow nicely if number
            inflow_str = f"${inflow:,.2f}" if isinstance(inflow, (int, float)) else (str(inflow) if inflow else "?")

            line = f"**[{symbol}]({url_for_link})**\n💸 Inflow: {inflow_str} | 🧠 {receivers or '?'} wallets\n📊 Vol: {vol} | MC: {mc} | ⏳ Age: {age}"
            description_lines.append(line)

        # fallback ak nie sú položky
        if not description_lines and isinstance(data.get("content"), str):
            description_lines = [data["content"]]

        embed = {
            "title": title,
            "description": "\n\n".join(description_lines) if description_lines else "",
            "color": 5814783
        }

        discord_payload = {"embeds": [embed]}

        # Pošleme výsledok do skutočného Discord webhooku (ten máš v ENV)
        if not DISCORD_WEBHOOK:
            print("DISCORD_WEBHOOK not set — skipping sending to Discord")
        else:
            headers = {"Content-Type": "application/json"}
            try:
                r = requests.post(DISCORD_WEBHOOK, headers=headers, data=json.dumps(discord_payload))
                print("Sent to final Discord webhook:", r.status_code, r.text[:200])
            except Exception as e:
                print("Error sending to Discord:", e)

        # Nansen/Discord expects a 204 No Content for successful webhook calls
        return ("", 204)

    except Exception as exc:
        print("Exception in webhook_proxy:", str(exc))
        # v prípade chyby vrátime 500
        return jsonify({"error": str(exc)}), 500


@app.route('/')
def index():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    # debug run for local testing; on Render, Gunicorn spúšťa app
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
