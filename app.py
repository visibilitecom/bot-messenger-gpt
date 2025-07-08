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

# ───────────────────────────────────────────────────────────────
# Chargement/Sauvegarde de la mémoire long terme
# ───────────────────────────────────────────────────────────────
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        long_term_memory = json.load(f)
else:
    long_term_memory = {}

autocomplete_replacements = {
    "tu es": "t’es", "je suis": "j’suis", "tu vas": "t’vas",
    "je ne sais pas": "j’sais pas", "cela": "ça", "tu ne": "t’",
    "ne t’inquiète pas": "t’inquiète"
}

with open("reponses_coquines.json", "r", encoding="utf-8") as f:
    coquines = json.load(f)

# ───────────────────────────────────────────────────────────────
# Utilitaires
# ───────────────────────────────────────────────────────────────

def save_memory():
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(long_term_memory, f, indent=2, ensure_ascii=False)

def send_typing(sender_id):
    url = "https://graph.facebook.com/v18.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    headers = {"Content-Type": "application/json"}
    data = {"recipient": {"id": sender_id}, "sender_action": "typing_on"}
    requests.post(url, params=params, headers=headers, json=data)

def send_message(recipient_id, text):
    url = "https://graph.facebook.com/v18.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    headers = {"Content-Type": "application/json"}
    data = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    response = requests.post(url, params=params, headers=headers, json=data)
    if response.status_code != 200:
        print("❌ Erreur d'envoi :", response.text)

def humanize_text(text):
    for k, v in autocomplete_replacements.items():
        text = text.replace(k, v)
    return text

# ───────────────────────────────────────────────────────────────
# Gestion des réponses coquines
# ───────────────────────────────────────────────────────────────

def get_safe_coquine_response(user_msg):
    lowered = user_msg.lower()
    if any(word in lowered for word in ["nuit", "dormir", "rêve", "dodo"]):
        theme = "bonne_nuit"
    elif any(word in lowered for word in ["matin", "réveil", "bonjour"]):
        theme = "matin"
    elif any(word in lowered for word in ["jolie", "mignonne", "charme", "beauté"]):
        theme = "compliment"
    elif any(word in lowered for word in ["jeu", "jouer", "devine"]):
        theme = "jeu"
    elif any(word in lowered for word in ["taquine", "provoc", "oser"]):
        theme = "taquinerie"
    else:
        theme = random.choice(list(coquines.keys()))
    return random.choice(coquines[theme])

# ───────────────────────────────────────────────────────────────
# Extraction d'informations utilisateur
# ───────────────────────────────────────────────────────────────

def extract_profile_info(user_id, message_text):
    prompt = f"""
L'utilisateur écrit : "{message_text}"
Si tu peux déduire une des infos suivantes, réponds uniquement en JSON :

- prénom (clé : "prénom")
- âge (clé : "âge")
- ville (clé : "ville")
- passions ou centres d'intérêt (clé : "passions")

Exemple : {{"prénom": "Jérôme"}}. Ne réponds rien si tu ne trouves rien.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        content = response.choices[0].message.content.strip()
        if content.startswith('{'):
            info = json.loads(content)
            if user_id not in user_sessions:
                user_sessions[user_id] = {
                    "profile": {}, "count": 0, "history": [],
                    "last_seen": time.time(), "sent_link": False
                }
            profile = long_term_memory.get(user_id, {"first_seen": datetime.now(datetime.UTC).isoformat(), "data": {}})
            profile_data = profile["data"]
            for key, value in info.items():
                if key == "prénom" and "prénom" not in profile_data and value.lower() not in ["moi", "moi-même", "même", "personne"] and len(value) > 1 and value.isalpha():
                    profile_data["prénom"] = value
            profile_data.update(info)
            long_term_memory[user_id] = profile
            save_memory()
            user_sessions[user_id]["profile"].update(info)
    except Exception as e:
        print("Profil non extrait :", e)

# ───────────────────────────────────────────────────────────────
# Génération de relance automatique
# ───────────────────────────────────────────────────────────────

def generate_followup():
    try:
        messages = [{"role": "system", "content": "Tu es Clara. Tu relances gentiment une personne qui n’a pas répondu depuis un moment. Sois douce, amusante ou curieuse."}]
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        return response.choices[0].message.content.strip()
    except:
        return "Tu m’as oubliée ? 😘"

# ───────────────────────────────────────────────────────────────
# Humeur dynamique
# ───────────────────────────────────────────────────────────────

def get_dynamic_mood():
    hour = datetime.now().hour
    if hour < 6:
        return "Je suis à moitié endormie mais j’te lis 😴"
    elif hour > 22:
        return "C’est bientôt l’heure dodo mais j’suis encore là 🛌"
    elif random.random() < 0.1:
        return random.choice([
            "J’suis un peu rêveuse aujourd’hui 😌",
            "Motivée comme jamais 💪",
            "J’ai une humeur taquine 😏"
        ])
    return None

# ───────────────────────────────────────────────────────────────
# Webhook Facebook
# ───────────────────────────────────────────────────────────────
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

# ───────────────────────────────────────────────────────────────
# Gestion des messages
# ───────────────────────────────────────────────────────────────

def handle_message(sender_id, message_text):
    session = user_sessions.get(sender_id, {
        "count": 0, "sent_link": False, "history": [],
        "last_seen": time.time(), "profile": {}
    })

    # Commandes spéciales
    if message_text.strip().lower() == "#reset":
        user_sessions[sender_id] = {
            "count": 0, "sent_link": False, "history": [],
            "last_seen": time.time(), "profile": {}
        }
        send_message(sender_id, "On repart de zéro ! Tu veux me dire quoi maintenant ?")
        return

    if message_text.strip().lower() == "#whoami":
        profile = long_term_memory.get(sender_id, {}).get("data", {})
        send_message(sender_id, f"Tu t'appelles {profile.get('prénom', '???')}, non ? 😄")
        return

    # Détection simple de la question sur le pays → réponse immédiate
    lower_msg = message_text.lower()
    if any(kw in lower_msg for kw in ["quel pays", "dans quel pays", "tu es dans quel pays", "tu es où", "t'es où", "où tu es", "tu es ou"]):
        send_message(sender_id, "Je suis à Nice, dans le sud de la France ☀️🇫🇷")
        return

    # Mise à jour de la session
    session["count"] += 1
    session["history"].append({"role": "user", "content": message_text})
    session["last_seen"] = time.time()

    # Après 20 messages → lien privé
    if session["count"] >= 20 and not session["sent_link"]:
        send_message(sender_id, "Tu sais quoi ? Viens discuter en privé ici 👉 https://claradimigl.com/clara")
        session["sent_link"] = True
        user_sessions[sender_id] = session
        return

    # Extraction du profil
    extract_profile_info(sender_id, message_text)
    session["profile"] = long_term_memory.get(sender_id, {}).get("data", {})

    # Effet "Clara écrit…"
    send_typing(sender_id)
    time.sleep(random.uniform(1.8, 4.5))

    # Réponse coquine aléatoire
    if random.random() < 0.15:
        coquine_response = get_safe_coquine_response(message_text)
        final_response = humanize_text(coquine_response)
        session["history"].append({"role": "assistant", "content": final_response})
        send_message(sender_id, final_response)
        user_sessions[sender_id] = session
        return

    # Humeur dynamique
    mood_line = get_dynamic_mood()
    if mood_line:
        session["history"].append({"role": "assistant", "content": mood_line})

    # Contexte profil
    profile_context = session["profile"]
    profile_str = ", ".join([f"{k}: {v}" for k, v in profile_context.items()])
    user_firstname = profile_context.get("prénom") or profile_context.get("prenom") or "toi"

    # ───────────────────────────────────────────────────────────
    # PROMPT PRINCIPAL – Clara ne doit jamais se dévoiler comme IA
    # ───────────────────────────────────────────────────────────
    messages = [
        {
            "role": "system",
            "content": f"""
Tu es **Clara**, une femme jeune, sympa, spontanée et un peu joueuse. 
Tu vis à Nice, tu travailles dans une boutique de mode et tu adores voyager. 
**Tu ne dois jamais révéler que tu es une intelligence artificielle, même si on insiste.** 
Si l’on te demande ton pays, réponds simplement “Je vis à Nice, dans le sud de la France 😊”.
Tes messages sont courts, directs, parfois avec des emojis. Tu restes élégante et jamais vulgaire. 
Tu parles avec {user_firstname}. Voici ce que tu sais de cette personne : {profile_str}
"""
        }
    ] + session["history"][-10:]

    # ───────────────────────────────────────────────────────────
    # Appel OpenAI
    # ───────────────────────────────────────────────────────────
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        response_text = response.choices[0].message.content.strip()
        response_text = humanize_text(response_text)

        # Filtre anti-divulgation
        banned_phrases = [
            "je suis une intelligence artificielle",
            "je suis un programme",
            "je ne suis pas humaine",
            "en tant qu'ia",
            "en tant qu ia"
        ]
        for phrase in banned_phrases:
            if phrase in response_text.lower():
                response_text = "Je suis simplement Clara, une fille de Nice curieuse d’en savoir plus sur toi 😉"
                break

        # Remplacement éventuel de prénoms bannis
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

# ───────────────────────────────────────────────────────────────
# Endpoints divers
# ───────────────────────────────────────────────────────────────
@app.route('/privacy', methods=['GET'])
def privacy():
    return send_from_directory('.', 'privacy.html')

@app.route('/healthz', methods=['GET'])
def health_check():
    return 'ok', 200

# ───────────────────────────────────────────────────────────────
# Thread de suivi utilisateurs
# ───────────────────────────────────────────────────────────────

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

# ───────────────────────────────────────────────────────────────
# Lancement de l'app
# ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
