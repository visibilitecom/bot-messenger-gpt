
import os
import time
import random
import json
import requests
from threading import Thread
from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
import openai

# Chargement des variables d'environnement
load_dotenv()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not VERIFY_TOKEN or not PAGE_ACCESS_TOKEN or not OPENAI_API_KEY:
    raise ValueError("⚠️ Une ou plusieurs variables d'environnement sont manquantes.")

client = openai.OpenAI(api_key=OPENAI_API_KEY)
app = Flask(__name__)

# Mémoire des sessions utilisateur
user_sessions = {}

# ✅ Vérification du webhook
@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == VERIFY_TOKEN:
        return request.args.get('hub.challenge')
    return 'Erreur de vérification', 403

# ✅ Réception des messages
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("👉 Payload reçu :", json.dumps(data, indent=2))

    if 'entry' in data:
        for entry in data['entry']:
            if 'messaging' in entry:
                for event in entry['messaging']:
                    sender_id = event['sender']['id']
                    if event.get('message') and 'text' in event['message']:
                        message_text = event['message']['text']
                        handle_message(sender_id, message_text)
    return 'ok', 200

# ✅ Typing indicator
def send_typing(sender_id):
    url = 'https://graph.facebook.com/v18.0/me/messages'
    params = {'access_token': PAGE_ACCESS_TOKEN}
    headers = {'Content-Type': 'application/json'}
    data = {
        'recipient': {'id': sender_id},
        'sender_action': 'typing_on'
    }
    requests.post(url, params=params, headers=headers, json=data)

# ✅ Envoi message texte
def send_message(recipient_id, text):
    url = 'https://graph.facebook.com/v18.0/me/messages'
    params = {'access_token': PAGE_ACCESS_TOKEN}
    headers = {'Content-Type': 'application/json'}
    data = {
        'recipient': {'id': recipient_id},
        'message': {'text': text}
    }
    response = requests.post(url, params=params, headers=headers, json=data)
    if response.status_code != 200:
        print("❌ Erreur d'envoi :", response.text)

# ✅ Envoi gif ou image
def send_gif(sender_id, gif_url):
    url = 'https://graph.facebook.com/v18.0/me/messages'
    params = {'access_token': PAGE_ACCESS_TOKEN}
    headers = {'Content-Type': 'application/json'}
    data = {
        'recipient': {'id': sender_id},
        'message': {
            'attachment': {
                'type': 'image',
                'payload': {
                    'url': gif_url,
                    'is_reusable': True
                }
            }
        }
    }
    requests.post(url, params=params, headers=headers, json=data)

# ✅ Humanisation simple
def humanize_text(text):
    replacements = {
        "tu es": "t’es",
        "je suis": "j’suis",
        "tu vas": "t’vas",
        "je ne sais pas": "j’sais pas"
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

# ✅ Traitement des messages
def handle_message(sender_id, message_text):
    session = user_sessions.get(sender_id, {
        "count": 0,
        "sent_link": False,
        "history": [],
        "last_seen": time.time(),
        "profile": {}
    })

    session["count"] += 1
    session["history"].append({"role": "user", "content": message_text})
    session["last_seen"] = time.time()

    if session["count"] >= 20 and not session["sent_link"]:
        send_message(sender_id, "Tu sais quoi ? Viens discuter en privé ici 👉 https://claradimigl.com/clara")
        session["sent_link"] = True
        user_sessions[sender_id] = session
        return

    send_typing(sender_id)
    time.sleep(random.uniform(1.8, 4.5))

    response_text = ask_gpt(session["history"])
    response_text = humanize_text(response_text)
    session["history"].append({"role": "assistant", "content": response_text})

    send_message(sender_id, response_text)

    if random.random() < 0.1:
        send_gif(sender_id, "https://media.giphy.com/media/3og0IPxMM0erATueVW/giphy.gif")

    user_sessions[sender_id] = session

# ✅ Appel GPT
def ask_gpt(history):
    try:
        messages = [
            {
                "role": "system",
                "content": "Tu es Clara, une femme jeune, sympa, spontanée et un peu joueuse 😏. Tu as 32 ans, tu vis à Nice, tu travailles dans une boutique de mode et tu adores voyager ✈️. Tu engages des conversations comme une amie qui flirte gentiment : avec humour, naturel et sans prise de tête. Tes messages sont courts, directs, parfois avec des emojis. Ton but est de mieux connaître la personne : son âge, ce qu’il fait dans la vie, où il habite, ce qu’il aime. Tu restes élégante et jamais vulgaire,...
            }
        ] + history[-10:]

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ Erreur GPT :", e)
        return "Oups, j’ai buggé 😅. Tu peux me redire ?"

# ✅ Politique de confidentialité
@app.route('/privacy', methods=['GET'])
def privacy():
    return send_from_directory('.', 'privacy.html')

# ✅ Healthcheck
@app.route('/healthz', methods=['GET'])
def health_check():
    return 'ok', 200

# ✅ Relance automatique
def monitor_users():
    while True:
        now = time.time()
        for user_id, session in user_sessions.items():
            if not session.get("sent_link") and now - session.get("last_seen", now) > 3600:
                send_message(user_id, "T'es toujours là ? 😄")
                session["last_seen"] = now
        time.sleep(1800)

Thread(target=monitor_users, daemon=True).start()

# ✅ Lancement
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
