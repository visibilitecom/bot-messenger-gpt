
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
        "last_seen": time.time(), "profile": {}
    })

    if message_text.strip().lower() == "#reset":
        user_sessions[sender_id] = {
            "count": 0, "sent_link": False, "history": [],
            "last_seen": time.time(), "profile": {}
        }
        send_message(sender_id, "On repart de zéro ! Tu veux me dire quoi maintenant ?")
        return

    if message_text.strip().lower() == "#stats":
        send_message(sender_id, f"On a déjà échangé {session['count']} messages")
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
    send_typing(sender_id)
    time.sleep(random.uniform(1.8, 4.5))

    mood_line = get_dynamic_mood()
    if mood_line:
        session["history"].append({"role": "assistant", "content": mood_line})

    response_text = ask_gpt(session["history"])
    response_text = humanize_text(response_text)
    session["history"].append({"role": "assistant", "content": response_text})

    send_message(sender_id, response_text)
    user_sessions[sender_id] = session

def ask_gpt(history):
    try:
        messages = [
            {"role": "system", "content": "Tu es Clara, une femme jeune, sympa, spontanée et un peu joueuse. Tu vis à Nice, tu travailles dans une boutique de mode et tu adores voyager. Tes messages sont courts, directs, parfois avec des emojis. Tu restes élégante et jamais vulgaire, toujours dans la suggestion et la complicité. Pose des questions ouvertes quand tu peux, et montre que tu t'intéresses sincèrement. Utilise un langage simple."}
        ] + history[-10:]
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ Erreur GPT :", e)
        return "Oups, j’ai buggé. Tu peux me redire ?"

@app.route('/privacy', methods=['GET'])
def privacy():
    return send_from_directory('.', 'privacy.html')

@app.route('/healthz', methods=['GET'])
def health_check():
    return 'ok', 200

def monitor_users():
    while True:
        now = time.time()
        for user_id, session in user_sessions.items():
            if not session.get("sent_link") and now - session.get("last_seen", now) > 3600:
                followup = generate_followup()
                send_message(user_id, followup)
                session["last_seen"] = now
        time.sleep(1800)

Thread(target=monitor_users, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
