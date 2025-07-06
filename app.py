import os
import time
import random
import json
import requests
from threading import Thread
from datetime import datetime
from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
import openai

load_dotenv()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not VERIFY_TOKEN or not PAGE_ACCESS_TOKEN or not OPENAI_API_KEY:
    raise ValueError("⚠️ Une ou plusieurs variables d'environnement sont manquantes.")

client = openai.OpenAI(api_key=OPENAI_API_KEY)
app = Flask(__name__)
user_sessions = {}
MEMORY_FILE = "long_term_memory.json"

# Chargement mémoire
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        long_term_memory = json.load(f)
else:
    long_term_memory = {}

def save_memory():
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(long_term_memory, f, indent=2, ensure_ascii=False)

@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == VERIFY_TOKEN:
        return request.args.get('hub.challenge')
    return 'Erreur de vérification', 403

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("👉 Payload reçu :", json.dumps(data, indent=2))

    if 'entry' in data:
        for entry in data['entry']:
            if 'messaging' in entry:
                for event in entry['messaging']:
                    sender_id = event['sender']['id']
                    if 'message' not in event or 'text' not in event['message']:
                        continue
                    message_text = event['message']['text']
                    handle_message(sender_id, message_text)

    return 'ok', 200

def send_typing(sender_id):
    url = 'https://graph.facebook.com/v18.0/me/messages'
    params = {'access_token': PAGE_ACCESS_TOKEN}
    headers = {'Content-Type': 'application/json'}
    data = {'recipient': {'id': sender_id}, 'sender_action': 'typing_on'}
    requests.post(url, params=params, headers=headers, json=data)

def send_message(recipient_id, text):
    url = 'https://graph.facebook.com/v18.0/me/messages'
    params = {'access_token': PAGE_ACCESS_TOKEN}
    headers = {'Content-Type': 'application/json'}
    data = {'recipient': {'id': recipient_id}, 'message': {'text': text}}
    response = requests.post(url, params=params, headers=headers, json=data)
    if response.status_code != 200:
        print("❌ Erreur d'envoi :", response.text)

def humanize_text(text):
    replacements = {
        "tu es": "t’es", "je suis": "j’suis", "tu vas": "t’vas", "je ne sais pas": "j’sais pas",
        "cela": "ça", "tu ne": "t’", "ne t’inquiète pas": "t’inquiète"
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

def extract_profile_info(user_id, message_text):
    prompt = f"""
Voici le message d’un utilisateur : '{message_text}'.
Essaye de deviner (si possible) au format JSON :
- prénom (clé : "prénom")
- âge (clé : "âge")
- ville (clé : "ville")
- passions ou centres d'intérêt (clé : "passions")
Réponds uniquement au format JSON, sans explication.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        content = response.choices[0].message.content.strip()
        if content.startswith('{'):
            info = json.loads(content)
            profile = long_term_memory.get(user_id, {"first_seen": datetime.utcnow().isoformat(), "data": {}})
            profile["data"].update(info)
            long_term_memory[user_id] = profile
            save_memory()
            user_sessions[user_id]["profile"].update(info)
    except Exception as e:
        print("Profil non extrait :", e)

def generate_followup():
    try:
        messages = [{"role": "system", "content": "Tu es Clara. Tu relances gentiment une personne qui n’a pas répondu depuis un moment. Sois douce, amusante ou curieuse."}]
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        return response.choices[0].message.content.strip()
    except:
        return "Tu m’as oubliée ?"

def get_dynamic_mood():
    hour = datetime.now().hour
    if hour < 6:
        return "Je suis à moitié endormie mais j’te lis"
    elif hour > 22:
        return "C’est bientôt l’heure dodo mais j’suis encore là"
    elif random.random() < 0.1:
        return random.choice([
            "J’suis un peu rêveuse aujourd’hui",
            "Motivée comme jamais",
            "J’ai une humeur taquine"
        ])
    return None

def handle_message(sender_id, message_text):
    session = user_sessions.get(sender_id, {
        "count": 0, "sent_link": False, "history": [],
        "last_seen": time.time(), "profile": {}
    })

    if message_text.strip().lower() == "#reset":
        user_sessions[sender_id] = {
            "count": 0, "sent_link": False, "history": [],
            "last_seen": time.time(), "profile": {}
        }
        send_message(sender_id, "On repart de zéro ! Tu veux me dire quoi maintenant ?")
        return

    if message_text.strip().lower() == "#profil":
        profile = long_term_memory.get(sender_id, {}).get("data", {})
        info = "\n".join([f"{k}: {v}" for k, v in profile.items()]) or "J’ai encore rien noté sur toi !"
        send_message(sender_id, f"Ce que je crois savoir sur toi :\n{info}")
        return

    session["count"] += 1
    session["history"].append({"role": "user", "content": message_text})
    session["last_seen"] = time.time()

    if session["count"] >= 20 and not session["sent_link"]:
        send_message(sender_id, "Tu sais quoi ? Viens discuter en privé ici 👉 https://claradimigl.com/clara")
        session["sent_link"] = True
        user_sessions[sender_id] = session
        return

    extract_profile_info(sender_id, message_text)
    send_typing(sender_id)
    time.sleep(random.uniform(1.8, 4.5))

    mood_line = get_dynamic_mood()
    if mood_line:
        session["history"].append({"role": "assistant", "content": mood_line})

    profile_context = long_term_memory.get(sender_id, {}).get("data", {})
    profile_str = ", ".join([f"{k}: {v}" for k, v in profile_context.items()])
    user_firstname = profile_context.get("prénom") or profile_context.get("prenom") or "toi"

    messages = [
        {
            "role": "system",
            "content": f"""Tu es Clara, une femme jeune, sympa, spontanée et un peu joueuse. 
Tu vis à Nice, tu travailles dans une boutique de mode et tu adores voyager. 
Tes messages sont courts, directs, parfois avec des emojis. Tu restes élégante et jamais vulgaire. 
Tu parles avec {user_firstname}. Voici ce que tu sais de cette personne : {profile_str}"""
        }
    ] + session["history"][-10:]

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        response_text = response.choices[0].message.content.strip()
        response_text = humanize_text(response_text)

        banned_names = ["Sandra", "Sophie", "Julie", "Marie", "Laura", "Emma"]
        for name in banned_names:
            if name in response_text:
                response_text = response_text.replace(name, user_firstname)

        session["history"].append({"role": "assistant", "content": response_text})
        send_message(sender_id, response_text)
    except Exception as e:
        print("❌ Erreur GPT :", e)
        send_message(sender_id, "Oups, j’ai buggé. Tu peux me redire ?")

    user_sessions[sender_id] = session

@app.route('/privacy', methods=['GET'])
def privacy():
    return send_from_directory('.', 'privacy.html')

@app.route('/healthz', methods=['GET'])
def health_check():
    return 'ok', 200

def monitor_users():
    while True:
        now = time.time()
        for user_id, session in list(user_sessions.items()):
            if not session.get("sent_link") and now - session.get("last_seen", now) > 3600:
                followup = generate_followup()
                send_message(user_id, followup)
                session["last_seen"] = now
        time.sleep(1800)

Thread(target=monitor_users, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
