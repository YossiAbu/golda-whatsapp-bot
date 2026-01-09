# main.py
import os
import logging
from datetime import datetime
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import requests

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI()

# ============================================================================
# CONFIGURATION
# ============================================================================

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

# ============================================================================
# WEBHOOK ENDPOINTS
# ============================================================================

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
async def handle_webhook(request: Request):
    """Handle incoming messages from WhatsApp"""
    data = await request.json()
    logger.info(f"Received webhook data: {data}")
    
    try:
        value = data["entry"][0]["changes"][0]["value"]
        
        if "messages" not in value:
            return {"status": "ok"}
        
        message = value["messages"][0]
        sender = message["from"]
        message_type = message.get("type")
        
        # Handle interactive messages (buttons and lists)
        if message_type == "interactive":
            interactive = message["interactive"]
            
            # Handle button reply (start button)
            if interactive["type"] == "button_reply":
                button_id = interactive["button_reply"]["id"]
                logger.info(f"Button response from {sender}: {button_id}")
                
                if button_id == "start":
                    start_conversation(sender)
            
            # Handle list reply (event type selection)
            elif interactive["type"] == "list_reply":
                selected_id = interactive["list_reply"]["id"]
                selected_title = interactive["list_reply"]["title"]
                logger.info(f"List response from {sender}: {selected_id} - {selected_title}")
                handle_event_type_selection(sender, selected_title)
        
        # Handle text messages
        elif message_type == "text":
            text = message["text"]["body"].strip()
            logger.info(f"Text message from {sender}: {text}")
            handle_text_message(sender, text)
        
    except (KeyError, IndexError) as e:
        logger.error(f"Error parsing message: {e}")
        logger.error(f"Data structure: {data}")
    
    return {"status": "ok"}


@app.get("/")
def home():
    """Health check endpoint"""
    return {"status": "Golda Ice Cream Bot is running! 🍦"}

# ============================================================================
# CONVERSATION HANDLERS
# ============================================================================

def start_conversation(sender: str):
    """Start a new conversation with date request"""
    conversations[sender] = {"step": 1}
    message = (
        "מתי מתקיים האירוע?\n"
        "אנא הכנס תאריך בפורמט: DD/MM/YYYY\n"
        "(לדוגמה: 31/12/2026)\n\n"
        "רוצה להתחיל מחדש? כתוב 'ביטול'"
    )
    send_message(sender, message)


def handle_text_message(sender: str, text: str):
    """Handle text message from customer"""
    logger.info(f"Handling message for {sender}, step: {conversations.get(sender, {}).get('step', 'new')}")
    
    # Check for cancel command
    if text.lower() in ["ביטול", "בטל", "התחיל מחדש", "מחדש", "חדש"]:
        cancel_conversation(sender)
        return
    
    # If this is a new conversation, send welcome
    if sender not in conversations:
        send_welcome_message(sender)
        return
    
    state = conversations[sender]
    step = state["step"]
    
    # Step 1: Get event date
    if step == 1:
        handle_date_input(sender, text, state)
    
    # Step 2: Get event type (text fallback)
    elif step == 2:
        handle_event_type_text(sender, text, state)
    
    # Step 3: Get event location
    elif step == 3:
        handle_location_input(sender, text, state)
    
    # Step 4: Get number of guests
    elif step == 4:
        handle_guests_input(sender, text, state)


def cancel_conversation(sender: str):
    """Cancel current conversation and restart"""
    if sender in conversations:
        del conversations[sender]
    
    send_message(sender, "✅ השיחה בוטלה")
    send_welcome_message(sender)


def handle_date_input(sender: str, text: str, state: dict):
    """Handle date input from customer"""
    if not is_valid_date(text):
        send_message(sender, """❌ תאריך לא תקין.

אנא הכנס תאריך בפורמט: DD/MM/YYYY
(לדוגמה: 31/12/2026)

💡 רוצה להתחיל מחדש? כתוב 'ביטול'""")
        return
    
    state["date"] = text
    state["step"] = 2
    send_event_type_list(sender)


def handle_event_type_selection(sender: str, selected_title: str):
    """Handle event type selection from interactive list"""
    if sender not in conversations:
        return
    
    state = conversations[sender]
    
    if state.get("step") == 2:
        state["event_type"] = selected_title
        state["step"] = 3
        send_message(sender, """מצוין! 📍

איפה מתקיים האירוע?
(עיר או כתובת מדויקת)

💡 רוצה להתחיל מחדש? כתוב 'ביטול'""")


def handle_event_type_text(sender: str, text: str, state: dict):
    """Handle event type as text (fallback)"""
    state["event_type"] = text
    state["step"] = 3
    send_message(sender, """מצוין! 📍

איפה מתקיים האירוע?
(עיר או כתובת מדויקת)

💡 רוצה להתחיל מחדש? כתוב 'ביטול'""")


def handle_location_input(sender: str, text: str, state: dict):
    """Handle location input from customer"""
    state["location"] = text
    state["step"] = 4
    send_message(sender, """נהדר! 👥

כמה אנשים צפויים?
(אנא הכנס מספר)

💡 רוצה להתחיל מחדש? כתוב 'ביטול'""")


def handle_guests_input(sender: str, text: str, state: dict):
    """Handle number of guests input from customer"""
    if not is_valid_number(text):
        send_message(sender, """❌ קלט לא תקין.

אנא הכנס מספר של כמות אנשים
(לדוגמה: 150)

💡 רוצה להתחיל מחדש? כתוב 'ביטול'""")
        return
    
    state["guests"] = text
    
    # Send confirmation to customer
    send_customer_confirmation(sender, state)
    
    # Send details to admin
    send_admin_notification(sender, state)
    
    # Reset conversation
    del conversations[sender]

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

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

# ============================================================================
# MESSAGING FUNCTIONS
# ============================================================================

def send_message(to: str, text: str):
    """Send text message via WhatsApp API"""
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


def send_welcome_message(sender: str):
    """Send welcome message with image and start button"""
    media_id = upload_image()
    
    if media_id:
        send_welcome_image(sender, media_id)
    
    send_start_button(sender)


def send_welcome_image(sender: str, media_id: str):
    """Send welcome image with caption"""
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "image",
        "image": {
            "id": media_id,
            "caption": """שלום! 🍦

ברוכים הבאים לגולדה - עגלת הגלידה שמגיעה אליכם!

אנחנו מביאים את חוויית הגלידה הטובה ביותר ישירות לאירוע שלכם."""
        }
    }
    
    response = requests.post(url, headers=headers, json=data)
    logger.info(f"Image send response: {response.status_code} - {response.text}")


def send_start_button(sender: str):
    """Send message with start button"""
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
            "type": "button",
            "body": {
                "text": """עם עגלת גלידה מקצועית ומגוון טעמים, נהפוך כל אירוע לבלתי נשכח! 🎉

בואו נתחיל - נשמח לשמוע על האירוע שלכם:"""
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "start",
                            "title": "התחל 🚀"
                        }
                    }
                ]
            }
        }
    }
    
    response = requests.post(url, headers=headers, json=data)
    logger.info(f"Start button send response: {response.status_code} - {response.text}")


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
                "text": """מעולה! איזה סוג אירוע?

💡 רוצה להתחיל מחדש? כתוב 'ביטול'"""
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
    logger.info(f"Event type list response: {response.status_code} - {response.text}")
    
    if response.status_code != 200:
        logger.error(f"Failed to send list: {response.text}")


def send_customer_confirmation(sender: str, state: dict):
    """Send confirmation message to customer with summary"""
    message = f"""תודה רבה! 🎉

קיבלנו את הפרטים שלך:

📅 תאריך: {state['date']}
🎉 סוג: {state['event_type']}
📍 מיקום: {state['location']}
👥 אנשים: {state['guests']}

נציג יצור איתך קשר בהקדם עם הצעת מחיר.

מצפים לראותכם! 🍦✨"""
    
    send_message(sender, message)


def send_admin_notification(sender: str, state: dict):
    """Send lead details to admin"""
    message = f"""🍦 ליד חדש מגולדה!

📅 תאריך: {state['date']}
🎉 סוג: {state['event_type']}
📍 מיקום: {state['location']}
👥 אנשים: {state['guests']}
📞 טלפון: +{sender}"""
    
    send_message(ADMIN_PHONE, message)

# ============================================================================
# MEDIA UPLOAD
# ============================================================================

def upload_image():
    """Upload logo.jpg and return media_id"""
    try:
        if not os.path.exists("logo.jpg"):
            logger.error("logo.jpg not found")
            return None
        
        url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/media"
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}"
        }
        
        with open("logo.jpg", "rb") as image_file:
            files = {
                "file": ("logo.jpg", image_file, "image/jpeg")
            }
            data = {
                "messaging_product": "whatsapp"
            }
            response = requests.post(url, headers=headers, files=files, data=data)
        
        if response.status_code == 200:
            media_id = response.json().get("id")
            logger.info(f"Image uploaded successfully, media_id: {media_id}")
            return media_id
        else:
            logger.error(f"Failed to upload image: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error uploading image: {e}")
        return None