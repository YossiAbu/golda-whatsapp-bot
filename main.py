# main.py
import os
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import requests

load_dotenv()

app = FastAPI()

# Configuration
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ADMIN_PHONE = os.getenv("ADMIN_PHONE")  # Noam's phone with country code (e.g., 972501234567)
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_secret_token")

# Store conversation state in memory
conversations = {}

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Webhook verification from Meta"""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)
    return {"error": "Invalid verification token"}

@app.post("/webhook")
async def receive_message(request: Request):
    """Receive messages from customers"""
    data = await request.json()
    
    try:
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        sender = message["from"]
        text = message["text"]["body"].strip()
        
        handle_conversation(sender, text)
        
    except (KeyError, IndexError):
        pass
    
    return {"status": "ok"}

def handle_conversation(sender: str, text: str):
    """Handle conversation flow with customer"""
    
    # If this is a new conversation
    if sender not in conversations:
        conversations[sender] = {"step": 1}
        send_message(sender, "שלום! 🍦\nמתי מתקיים האירוע? (לדוגמה: 15/03/2026)")
        return
    
    state = conversations[sender]
    step = state["step"]
    
    # Step 1: Get event date
    if step == 1:
        state["date"] = text
        state["step"] = 2
        send_message(sender, "מעולה! איזה סוג אירוע? (יום הולדת, חתונה, בר מצווה...)")
    
    # Step 2: Get event type
    elif step == 2:
        state["event_type"] = text
        state["step"] = 3
        send_message(sender, "נהדר! כמה אנשים צפויים?")
    
    # Step 3: Get number of guests and send to Noam
    elif step == 3:
        state["guests"] = text
        
        # Send details to Noam
        summary = (
            f"🍦 ליד חדש מגולדה!\n\n"
            f"📅 תאריך: {state['date']}\n"
            f"🎉 סוג: {state['event_type']}\n"
            f"👥 אנשים: {state['guests']}\n"
            f"📞 טלפון: +{sender}"
        )
        send_message(ADMIN_PHONE, summary)
        
        # Thank the customer
        send_message(sender, "תודה רבה! 🎉\nנועם יחזור אליך בהקדם עם הצעת מחיר.")
        
        # Reset conversation
        del conversations[sender]

def send_message(to: str, text: str):
    """Send message via WhatsApp API"""
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=data)

@app.get("/")
def home():
    return {"status": "Golda Ice Cream Bot is running! 🍦"}