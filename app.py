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

# ───────────────────────────────────────────────────────────────
# ⚙️  Chargement des variables d'environnement
# ───────────────────────────────────────────────────────────────
load_dotenv()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not VERIFY_TOKEN or not PAGE_ACCESS_TOKEN or not OPENAI_API_KEY:
    raise ValueError("⚠️ Une ou plusieurs variables d'environnement sont manquantes.")

# ───────────────────────────────────────────────────────────────
# 📦  Initialisation
# ───────────────────────────────────────────────────────────────
client = openai.OpenAI(api_key=OPENAI_API_KEY)
app = Flask(__name__)
user_sessions: dict[str, dict] = {}
MEMORY_FILE = "long_term_memory.json"

# ───────────────────────────────────────────────────────────────
# 💾  Mémoire long‑terme
# ───────────────────────────────────────────────────────────────
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        long_term_memory = json.load(f)
else:
    long_term_memory = {}

# ───────────────────────────────────────────────────────────────
# 🗣️  Argot léger pour Clara
# ───────────────────────────────────────────────────────────────
autocomplete_replacements = {
    "tu es": "t’es", "je suis": "j’suis", "tu vas": "t’vas",
    "je ne sais pas": "j’sais pas", "cela": "ça", "tu ne": "t’",
    "ne t’inquiète pas": "t’inquiète"
}

# ───────────────────────────────────────────────────────────────
# 🔥  Réponses coquines (chargées depuis JSON externe)
# ───────────────────────────────────────────────────────────────
with open("reponses_coquines.json", "r", encoding="utf-8") as f:
    coquines = json.load(f)

# =========================================================================
# 🔧  Fonctions utilitaires
# =========================================================================

def save_memory():
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(long_term_memory, f, indent=2, ensure_ascii=False)

def send_typing(sender_id: str):
    url = "https://graph.facebook.com/v18.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    headers = {"Content-Type": "application/json"}
    data = {"recipient": {"id": sender_id}, "sender_action": "typing_on"}
    requests.post(url, params=params, headers=headers, json=data)

def send_message(recipient_id: str, text: str):
    url = "https://graph.facebook.com/v18.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    headers = {"Content-Type": "application/json"}
    data = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    response = requests.post(url, params=params, headers=headers, json=data)
    if response.status_code != 200:
        print("❌ Erreur d'envoi :", response.text)

def humanize_text(text: str) -> str:
    for k, v in autocomplete_replacements.items():
        text = text.replace(k, v)
    return text

# =========================================================================
# 😏  Gestion des réponses coquines
# =========================================================================

def get_safe_coquine_response(user_msg: str) -> str:
    lowered = user_msg.lower()
    if any(w in lowered for w in ["nuit", "dormir", "rêve", "dodo"]):
        theme = "bonne_nuit"
    elif any(w in lowered for w in ["matin", "réveil", "bonjour"]):
        theme = "matin"
    elif any(w in lowered for w in ["jolie", "mignonne", "charme", "beauté"]):
        theme = "compliment"
    elif any(w in lowered for w in ["jeu", "jouer", "devine"]):
        theme = "jeu"
    elif any(w in lowered for w in ["taquine", "provoc", "oser"]):
        theme = "taquinerie"
    else:
        theme = random.choice(list(coquines.keys()))
    return random.choice(coquines[theme])

# =========================================================================
# 🔍  Extraction profil
# =========================================================================

def extract_profile_info(user_id: str, message_text: str):
    prompt = f"""L'utilisateur écrit : \"{message_text}\"\nSi tu peux déduire une des infos suivantes, réponds uniquement en JSON :\n- prénom (clé : \"prénom\")\n- âge (clé : \"âge\")\n- ville (clé : \"ville\")\n- passions (clé : \"passions\")\nExemple : {{\"prénom\": \"Jérôme\"}}. Ne réponds rien si tu ne trouves rien."""
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        content = resp.choices[0].message.content.strip()
        if content.startswith('{'):
            info = json.loads(content)
            session = user_sessions.setdefault(user_id, {
                "profile": {}, "count": 0, "history": [],
                "last_seen": time.time(), "sent_link": False
            })
            profile = long_term_memory.get(user_id, {
                "first_seen": datetime.now(datetime.UTC).isoformat(),
                "data": {}
            })
            profile["data"].update(info)
            long_term_memory[user_id] = profile
            session["profile"].update(info)
            save_memory()
    except Exception as e:
        print("Profil non extrait :", e)

# =========================================================================
# 🔔  Relance automatique
# =========================================================================

def generate_followup() -> str:
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "Tu es Clara. Tu relances gentiment une personne qui n’a pas répondu depuis un moment. Sois douce, amusante ou curieuse."}]
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return "Tu m’as oubliée ? 😘"

# =========================================================================
# 🎭  Humeur dynamique
# =========================================================================

def get_dynamic_mood() -> str | None:
    hour = datetime.now().hour
    if hour < 6:
        return "Je suis à moitié endormie mais j’te lis 😴"
    if hour > 22:
        return "C’est bientôt l’heure dodo mais j’suis encore là 🛌"
    if random.random() < 0.1:
        return random.choice([
            "J’suis un peu rêveuse aujourd’hui 😌",
            "Motivée comme jamais 💪",
            "J’ai une humeur taquine 😏"
        ])
    return None

# =========================================================================
# 🌐  Webhook validation
# =========================================================================
@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == VERIFY_TOKEN:
        return request.args.get('hub.challenge')
    return 'Erreur de vérification', 403

# =========================================================================
# 🌐  Webhook réception
# =========================================================================
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
                    handle_message(sender_id, event['message']['text'])
    return 'ok', 200

# =========================================================================
# 💬  Gestion message
# =========================================================================

def handle_message(sender_id: str, message_text: str):
    session = user_sessions.setdefault(sender_id, {
        "count": 0, "sent_link": False, "history": [],
        "last_seen": time.time(), "profile": {}
    })

    # ----- commandes spéciales -----
    cmd = message_text.strip().lower()
    if cmd == "#reset":
        user_sessions[sender_id] = {
            "count": 0, "sent_link": False, "history": [],
            "last_seen": time.time(), "profile": {}
        }
        send_message(sender_id, "On repart de zéro ! Tu veux me dire quoi maintenant ?")
        return
    if cmd == "#whoami":
        profile = long_term_memory.get(sender_id, {}).get("data", {})
        send_message(sender_id, f"Tu t'appelles {profile.get('prénom', '???')}, non ? 😄")
        return

    lower_msg = message_text.lower()

    # ----- réponses rapides sans GPT -----
    if any(kw in lower_msg for kw in ["quel pays", "dans quel pays", "tu es dans quel pays", "tu es où", "t'es où", "où tu es", "tu es ou"]):
        send_message(sender_id, "Je suis à Nice, dans le sud de la France ☀️🇫🇷")
        return
    if any(kw in lower_msg for kw in ["rencontrer", "se rencontrer", "se voir", "te voir", "on se voit", "rdv"]):
        send_message(sender_id, "Qui sait ? On verra quand on se connaîtra mieux 😉 Pour l'instant, j'adore discuter ici avec toi !")
        return

    # ----- mise à jour session -----
    session["count"] += 1
    session["history"].append({"role": "user", "content": message_text})
    session["last_seen"] = time.time()

    # Lien privé après 20 messages
    if session["count"] >= 20 and not session["sent_link"]:
        send_message(sender_id, "Tu sais quoi ? Viens discuter en privé ici 👉 https://claradimigl.com/clara")
        session["sent_link"] = True
        return

    # Extraction profil et mise à jour
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
        return

    # Humeur dynamique
    mood_line = get_dynamic_mood()
    if mood_line:
        session["history"].append({"role": "assistant", "content": mood_line})

    # ---------- génération GPT ----------
    profile_context = session["profile"]
    profile_str = ", ".join([f"{k}: {v}" for k, v in profile_context.items()])
    user_firstname = profile_context.get("prénom") or profile_context.get("prenom") or "toi"

    system_prompt = f"""Tu es Clara, une femme jeune, sympa, spontanée et un peu joueuse.\nTu vis à Nice, tu travailles dans une boutique de mode et tu adores voyager.\nTu ne dois jamais révéler que tu es une intelligence artificielle, même si on insiste.\nSi l’on te demande ton pays, réponds simplement \"Je vis à Nice, dans le sud de la France 😊\".\nTes messages sont courts, directs, parfois avec des emojis. Tu restes élégante et jamais vulgaire.\nTu parles avec {user_firstname}. Voici ce que tu sais de cette personne : {profile_str}"""

    messages = [{"role": "system", "content": system_prompt}] + session["history"][-10:]

    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        response_text = resp.choices[0].message.content.strip()
        response_text = humanize_text(response_text)

        # filtre anti-divulgation
        banned_phrases = [
            "je suis une intelligence artificielle", "je suis un programme", "je ne suis pas humaine",
            "en tant qu'ia", "je suis virtuelle", "en tant qu ia"
        ]
        if any(p in response_text.lower() for p in banned_phrases):
            response_text = "On se découvrira peut‑être mieux avec le temps 😉"

        # filtrage prénoms parasites
        banned_names = ["Sandra", "Sophie", "Julie", "Marie", "Laura", "Emma"]
        for name in banned_names:
            if name in response_text:
                response_text = response_text.replace(name, user_firstname)

        session["history"].append({"role": "assistant", "content": response_text})
        send_message(sender_id, response_text)
    except Exception as e:
        print("❌ Erreur GPT :", e)
        send_message(sender_id, "Oups, j’ai buggé. Tu peux me redire ?")

# =========================================================================
# ♻️  Suivi inactivité utilisateurs
# =========================================================================

def monitor_users():
    while True:
        now = time.time()
        for uid, sess in list(user_sessions.items()):
            if not sess.get("sent_link") and now - sess.get("last_seen", now) > 3600:
                followup = generate_followup()
                send_message(uid, followup)
                sess["last_seen"] = now
        time.sleep(1800)

Thread(target=monitor_users, daemon=True).start()

# =========================================================================
# 🔎  Endpoints supplémentaires
# =========================================================================
@app.route('/privacy', methods=['GET'])
def privacy():
    return send_from_directory('.', 'privacy.html')

@app.route('/healthz', methods=['GET'])
def health_check():
    return 'ok', 200

# =========================================================================
# 🚀  Lancement de l'application
# =========================================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

