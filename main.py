# main.py
import os
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import requests
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI()

# Configuration
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ADMIN_PHONE = os.getenv("ADMIN_PHONE")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_secret_token")

# Store conversation state in memory
conversations = {}

# Map event type IDs to display names
EVENT_TYPES = {
    "wedding": "💍 חתונה",
    "bar_bat_mitzvah": "🕍 בר/בת מצווה",
    "birthday": "🎂 יום הולדת",
    "brit_milah": "👶 ברית מילה",
    "engagement": "💕 אירוסין",
    "company_event": "🏢 אירוע חברה",
    "graduation_party": "🎓 מסיבת סיום",
    "bachelor_party": "🎉 מסיבת רווקים/רווקות",
    "festival": "🎪 פסטיבל/יריד",
    "other": "❓ אחר"
}

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
    logger.info(f"Received webhook data: {data}")
    
    try:
        value = data["entry"][0]["changes"][0]["value"]
        
        # Check if it's an interactive message (list response)
        if "messages" in value and value["messages"][0].get("type") == "interactive":
            message = value["messages"][0]
            sender = message["from"]
            
            # Get the selected option ID
            interactive = message["interactive"]
            if interactive["type"] == "list_reply":
                selected_id = interactive["list_reply"]["id"]
                selected_title = interactive["list_reply"]["title"]
                
                logger.info(f"Interactive response from {sender}: {selected_id} - {selected_title}")
                handle_interactive_response(sender, selected_id, selected_title)
        
        # Regular text message
        elif "messages" in value and value["messages"][0].get("type") == "text":
            message = value["messages"][0]
            sender = message["from"]
            text = message["text"]["body"].strip()
            
            logger.info(f"Text message from {sender}: {text}")
            handle_conversation(sender, text)
        
    except (KeyError, IndexError) as e:
        logger.error(f"Error parsing message: {e}")
        logger.error(f"Data structure: {data}")
    
    return {"status": "ok"}

def is_valid_date(date_str: str) -> bool:
    """Check if date is in DD/MM/YYYY format and valid"""
    try:
        datetime.strptime(date_str, "%d/%m/%Y")
        return True
    except ValueError:
        return False

def is_valid_number(num_str: str) -> bool:
    """Check if string is a valid positive number"""
    try:
        num = int(num_str)
        return num > 0
    except ValueError:
        return False

def send_event_type_list(sender: str):
    """Send interactive list for event type selection"""
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": "מעולה! איזה סוג אירוע?"
            },
            "action": {
                "button": "בחר סוג אירוע",
                "sections": [
                    {
                        "title": "סוג אירוע",
                        "rows": [
                            {"id": "wedding", "title": "💍 חתונה"},
                            {"id": "bar_bat_mitzvah", "title": "🕍 בר/בת מצווה"},
                            {"id": "birthday", "title": "🎂 יום הולדת"},
                            {"id": "brit_milah", "title": "👶 ברית מילה"},
                            {"id": "engagement", "title": "💕 אירוסין"},
                            {"id": "company_event", "title": "🏢 אירוע חברה"},
                            {"id": "graduation_party", "title": "🎓 מסיבת סיום"},
                            {"id": "bachelor_party", "title": "🎉 מסיבת רווקים/רווקות"},
                            {"id": "festival", "title": "🎪 פסטיבל/יריד"},
                            {"id": "other", "title": "❓ אחר"}
                        ]
                    }
                ]
            }
        }
    }
    
    response = requests.post(url, headers=headers, json=data)
    logger.info(f"WhatsApp API response: {response.status_code} - {response.text}")
    
    if response.status_code != 200:
        logger.error(f"Failed to send list: {response.text}")

def handle_interactive_response(sender: str, selected_id: str, selected_title: str):
    """Handle response from interactive list"""
    
    if sender not in conversations:
        return
    
    state = conversations[sender]
    
    # User selected event type
    if state.get("step") == 2:
        state["event_type"] = selected_title
        state["step"] = 3
        send_message(sender, "מצוין! 📍\nאיפה מתקיים האירוע?\n(עיר או כתובת מדויקת)")

def handle_conversation(sender: str, text: str):
    """Handle conversation flow with customer"""
    logger.info(f"Handling conversation for {sender}, step: {conversations.get(sender, {}).get('step', 'new')}")
    
    # If this is a new conversation
    if sender not in conversations:
        conversations[sender] = {"step": 1}
        send_message(sender, "שלום! 🍦\nמתי מתקיים האירוע?\nאנא הכנס תאריך בפורמט:\nDD/MM/YYYY\n(לדוגמה: 31/12/2026)")
        return
    
    state = conversations[sender]
    step = state["step"]
    
    # Step 1: Get event date
    if step == 1:
        # Validate date format
        if not is_valid_date(text):
            send_message(sender, "❌ תאריך לא תקין.\nאנא הכנס תאריך בפורמט:\nDD/MM/YYYY\n(לדוגמה: 31/12/2026)")
            return
        
        state["date"] = text
        state["step"] = 2
        # Send interactive list
        send_event_type_list(sender)
    
    # Step 2: Should be handled by interactive response, but handle text fallback
    elif step == 2:
        state["event_type"] = text
        state["step"] = 3
        send_message(sender, "מצוין! \nאיפה מתקיים האירוע?\n(עיר או כתובת מדויקת)")
    
    # Step 3: Get event location
    elif step == 3:
        state["location"] = text
        state["step"] = 4
        send_message(sender, "נהדר! כמה אנשים צפויים?\n(אנא הכנס מספר)")
    
    # Step 4: Get number of guests
    elif step == 4:
        # Validate number
        if not is_valid_number(text):
            send_message(sender, "❌ קלט לא תקין.\nאנא הכנס מספר של כמות אנשים\n(לדוגמה: 150)")
            return
        
        state["guests"] = text
        
        # Send details to admin
        summary = (
            f"🍦 ליד חדש מגולדה!\n\n"
            f"📅 תאריך: {state['date']}\n"
            f"🎉 סוג: {state['event_type']}\n"
            f"📍 מיקום: {state['location']}\n"
            f"👥 אנשים: {state['guests']}\n"
            f"📞 טלפון: +{sender}"
        )
        send_message(ADMIN_PHONE, summary)
        
        # Thank the customer
        send_message(sender, "תודה רבה! 🎉\bנציג יחזור אליך בהקדם עם הצעת מחיר.")
        
        # Reset conversation
        del conversations[sender]

def send_message(to: str, text: str):
    """Send message via WhatsApp API"""
    logger.info(f"Sending message to {to}: {text}")
    
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
    
    response = requests.post(url, headers=headers, json=data)
    logger.info(f"WhatsApp API response: {response.status_code} - {response.text}")
    
    if response.status_code != 200:
        logger.error(f"Failed to send message: {response.text}")

@app.get("/")
def home():
    return {"status": "Golda Ice Cream Bot is running! 🍦"}