import os
import requests
import json
from dotenv import load_dotenv

# Load env variables here so the notifier always has access to the URL
load_dotenv()

def send_discord_alert(message: str):
    """Pushes a markdown-formatted message to a Discord channel."""
    webhook_url = os.getenv("DISCORD_WEBHOOK")
    if not webhook_url:
        print("[WARNING] No Discord webhook URL found in .env. Skipping alert.")
        return

    print("[INFO] Start sending messages to Discord")
    message = "@everyone \n" + message + "\n"
    data = {
        "content": message,
        "username": "Trading Alert Bot"
    }

    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Failed to send Discord alert: {e}")