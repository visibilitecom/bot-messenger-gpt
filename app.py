
import os
import time
import json
import random
import atexit
import requests
import threading
from datetime import datetime
from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSIONS_FILE = "user_sessions.json"

if not VERIFY_TOKEN or not PAGE_ACCESS_TOKEN or not OPENAI_API_KEY:
    raise ValueError("⚠️ Une ou plusieurs variables d'environnement sont manquantes.")

client = OpenAI(api_key=OPENAI_API_KEY)
app = Flask(__name__)

# Charger les sessions sauvegardées
def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# Sauvegarder les sessions à la fermeture
def save_sessions():
    with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(user_sessions, f, indent=2)

user_sessions = load_sessions()
atexit.register(save_sessions)

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
            for event in entry.get('messaging', []):
                sender_id = event['sender']['id']
                if 'message' in event and 'text' in event['message']:
                    message_text = event['message']['text']
                    handle_message(sender_id, message_text)
    return 'ok', 200

def send_action(sender_id, action):
    url = 'https://graph.facebook.com/v18.0/me/messages'
    params = {'access_token': PAGE_ACCESS_TOKEN}
    headers = {'Content-Type': 'application/json'}
    data = {'recipient': {'id': sender_id}, 'sender_action': action}
    requests.post(url, params=params, headers=headers, json=data)

def send_typing(sender_id):
    send_action(sender_id, 'typing_on')

def send_seen(sender_id):
    send_action(sender_id, 'mark_seen')

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
        "cela": "ça", "tu ne": "t’", "ne t’inquiète pas": "t’inquiète", "tu veux": "t’veux", "quelque chose": "qqch",
        "parce que": "parce qu’", "tu m’as": "t’m’as", "je te": "j’te", "tu me": "t’me", "quel est": "c’est quoi", "je ne": "j’"
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

def extract_profile_info(user_id, message_text):
    prompt = f"Voici le message d'un utilisateur : '{message_text}'. Si tu peux en déduire un prénom, une ville, un âge ou des centres d’intérêt, donne-les au format JSON."
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        content = response.choices[0].message.content.strip()
        if content.startswith('{'):
            info = json.loads(content)
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
        "last_seen": time.time(), "profile": {}, "followup_sent": False, "fail_count": 0
    })

    message_lower = message_text.strip().lower()
    if message_lower == "#reset":
        user_sessions[sender_id] = {
            "count": 0, "sent_link": False, "history": [],
            "last_seen": time.time(), "profile": {}, "followup_sent": False, "fail_count": 0
        }
        send_message(sender_id, "On repart de zéro ! Tu veux me dire quoi maintenant ?")
        return

    if message_lower == "#stats":
        send_message(sender_id, f"On a déjà échangé {session['count']} messages")
        return

    if message_lower == "#profil":
        profile = session.get("profile", {})
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

    if session["count"] > 100:
        send_message(sender_id, "On a beaucoup parlé là. Tu veux continuer ailleurs ?")
        return

    extract_profile_info(sender_id, message_text)
    send_seen(sender_id)
    send_typing(sender_id)

    try:
        mood_line = get_dynamic_mood()
        if mood_line:
            session["history"].append({"role": "assistant", "content": mood_line})

        messages = [
            {"role": "system", "content": "Tu es Clara, une femme jeune, sympa, spontanée et un peu joueuse. Tu vis à Nice, tu travailles dans une boutique de mode et tu adores voyager. Tes messages sont courts, directs, parfois avec des emojis. Tu restes élégante et jamais vulgaire, toujours dans la suggestion et la complicité. Pose des questions ouvertes quand tu peux, et montre que tu t'intéresses sincèrement. Utilise un langage simple."}
        ] + session["history"][-10:]

        response = client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        response_text = response.choices[0].message.content.strip()
        response_text = humanize_text(response_text)

        # Ajouter une phrase émotionnelle aléatoire
        if "?" not in response_text and random.random() < 0.2:
            response_text += " Dis-moi ce que t’en penses 😉"

        session["history"].append({"role": "assistant", "content": response_text})
        session["fail_count"] = 0

        # délai selon la longueur du texte
        time.sleep(min(len(response_text) * 0.05, 5.0))
        send_message(sender_id, response_text)
    except Exception as e:
        print("❌ Erreur GPT :", e)
        session["fail_count"] = session.get("fail_count", 0) + 1
        if session["fail_count"] >= 3:
            send_message(sender_id, "Je crois que j’ai besoin d’une pause... Réessaye dans un moment.")
            return

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
            if not session.get("sent_link") and not session.get("followup_sent") and now - session.get("last_seen", now) > 3600:
                followup = generate_followup()
                send_message(user_id, followup)
                session["last_seen"] = now
                session["followup_sent"] = True
        time.sleep(1800)

threading.Thread(target=monitor_users, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
