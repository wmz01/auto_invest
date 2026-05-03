import os
import requests
import json
from dotenv import load_dotenv
from datetime import datetime

# Load env variables here so the notifier always has access to the URL
load_dotenv()

def send_discord_alert(data):
    """
    Pushes an alert to Discord.
    Accepts either a raw string or a full dictionary payload.
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK")
    if not webhook_url:
        print("[WARNING] No Discord webhook URL found. Skipping alert.")
        return

    # 1. Standardize the payload
    if isinstance(data, str):
        payload = {
            "content": "@everyone",
            "username": "Trading Alert Bot",
            "embeds": [
                {
                    "description": data,
                    "color": 8359053,  # Dark grey border
                    "footer": {
                        "text": f"Executive Summary • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                }
            ]
        }
    elif isinstance(data, dict):
        # If it's already a dictionary (like your success_msg payload), use it as is
        payload = data
    else:
        print("[ERROR] Unsupported data type sent to send_discord_alert")
        return

    # 2. Send the request
    try:
        # 'json=' handles the headers and encoding automatically
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        print("[INFO] Message sent successfully")
    except Exception as e:
        print(f"[ERROR] Failed to send Discord alert: {e}")