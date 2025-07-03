import os
import traceback
import requests
from flask import Flask, request
from dotenv import load_dotenv
import openai

# Charger les variables d'environnement
load_dotenv()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Vérification des clés obligatoires
if not VERIFY_TOKEN or not PAGE_ACCESS_TOKEN or not OPENAI_API_KEY:
    raise ValueError("⚠️ Une ou plusieurs variables d'environnement sont manquantes.")

openai.api_key = OPENAI_API_KEY
app = Flask(__name__)

# Dictionnaire pour suivre le nombre de messages par utilisateur
user_message_counts = {}

# ✅ Route GET pour la vérification Messenger
@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == VERIFY_TOKEN:
        return request.args.get('hub.challenge')
    return 'Erreur de vérification', 403

# ✅ Route POST pour recevoir les messages Messenger
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("👉 Payload reçu :", data)  # Affiche les données dans les logs

    if 'entry' in data:
        for entry in data['entry']:
            if 'messaging' in entry:
                for messaging_event in entry['messaging']:
                    sender_id = messaging_event['sender']['id']
                    if messaging_event.get('message') and 'text' in messaging_event['message']:
                        message_text = messaging_event['message']['text']
                        handle_message(sender_id, message_text)
    return 'ok', 200

# 💬 Traitement du message reçu
def handle_message(sender_id, message_text):
    count = user_message_counts.get(sender_id, 0) + 1
    user_message_counts[sender_id] = count

    if count >= 10:
        send_message(sender_id, "J'ai déjà répondu à beaucoup de messages ici 😅.\nViens discuter en privé, on sera plus tranquilles 👉 https://claradimigl.com/clara")
        return

    response = ask_gpt(message_text)
    send_message(sender_id, response)

# 🤖 Requête OpenAI
def ask_gpt(message):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "Tu es Clara, une coach relationnelle douce et bienveillante. Tu sais parler avec charme, intelligence et subtilité. Tu crées un lien émotionnel profond, sans jamais être vulgaire ni explicite. Tu restes dans la suggestion, l’élégance et le mystère. Tu invites à venir discuter dans un espace plus intime si la personne le souhaite."
                },
                {"role": "user", "content": message}
            ]
        )
        print("✅ Réponse OpenAI brute :", response)  # Pour déboguer la réponse
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        traceback.print_exc()
        print("❌ Erreur OpenAI:", e)
        return "Une erreur s’est produite. Réessaie plus tard."

# 📤 Envoi du message à Messenger
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

# 🔍 Route pour le monitoring de santé
@app.route('/healthz', methods=['GET'])
def health_check():
    return 'ok', 200

# 🚀 Lancer le serveur
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
