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

"""
Messenger Bot – Clara
====================
Version complète incluant :
• gestion des photos (3 images publiques dans CLARA_PICS)
• filtres anti‑IA
• mémoire long‑terme, relance automatique
"""

# ───────────────────────────────────────────────────────────────
# ⚙️  Variables d’environnement
# ───────────────────────────────────────────────────────────────
load_dotenv()
VERIFY_TOKEN     = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")

if not all([VERIFY_TOKEN, PAGE_ACCESS_TOKEN, OPENAI_API_KEY]):
    raise ValueError("⚠️ VERIFY_TOKEN / PAGE_ACCESS_TOKEN / OPENAI_API_KEY manquant.")

# ───────────────────────────────────────────────────────────────
# 📦  Initialisation
# ───────────────────────────────────────────────────────────────
client = openai.OpenAI(api_key=OPENAI_API_KEY)
app    = Flask(__name__)
user_sessions: dict[str, dict] = {}
MEMORY_FILE = "long_term_memory.json"

# ───────────────────────────────────────────────────────────────
# 🖼️  Photos de Clara (URL publiques)
# ───────────────────────────────────────────────────────────────
CLARA_PICS = [
    "https://raw.githubusercontent.com/visibilitecom/bot-messenger-gpt/main/images/clara1.png",
    "https://raw.githubusercontent.com/visibilitecom/bot-messenger-gpt/main/images/clara2.png",
    "https://raw.githubusercontent.com/visibilitecom/bot-messenger-gpt/main/images/clara3.png",
]

# ───────────────────────────────────────────────────────────────
# 💾  Mémoire long‑terme
# ───────────────────────────────────────────────────────────────
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        long_term_memory = json.load(f)
else:
    long_term_memory = {}

# ───────────────────────────────────────────────────────────────
# 🗣️  Contractions argotiques
# ───────────────────────────────────────────────────────────────
autocomplete_replacements = {
    "tu es": "t’es", "je suis": "j’suis", "tu vas": "t’vas",
    "je ne sais pas": "j’sais pas", "cela": "ça", "tu ne": "t’",
    "ne t’inquiète pas": "t’inquiète",
}

# ───────────────────────────────────────────────────────────────
# 🔥  Réponses coquines prédéfinies
# ───────────────────────────────────────────────────────────────
with open("reponses_coquines.json", "r", encoding="utf-8") as f:
    coquines = json.load(f)

# =========================================================================
# 🔧  Fonctions utilitaires
# =========================================================================

def save_memory():
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(long_term_memory, f, indent=2, ensure_ascii=False)

def send_typing(sid: str):
    requests.post(
        "https://graph.facebook.com/v18.0/me/messages",
        params={"access_token": PAGE_ACCESS_TOKEN},
        headers={"Content-Type": "application/json"},
        json={"recipient": {"id": sid}, "sender_action": "typing_on"},
    )

def send_message(rid: str, text: str):
    requests.post(
        "https://graph.facebook.com/v18.0/me/messages",
        params={"access_token": PAGE_ACCESS_TOKEN},
        headers={"Content-Type": "application/json"},
        json={"recipient": {"id": rid}, "message": {"text": text}},
    )

def send_image(rid: str, url: str):
    requests.post(
        "https://graph.facebook.com/v18.0/me/messages",
        params={"access_token": PAGE_ACCESS_TOKEN},
        headers={"Content-Type": "application/json"},
        json={
            "recipient": {"id": rid},
            "message": {"attachment": {"type": "image", "payload": {"url": url, "is_reusable": True}}},
        },
    )

def humanize_text(t: str) -> str:
    for k, v in autocomplete_replacements.items():
        t = t.replace(k, v)
    return t

# =========================================================================
# 😏  Réponses coquines dynamiques
# =========================================================================

def get_safe_coquine_response(msg: str) -> str:
    l = msg.lower()
    if any(w in l for w in ["nuit", "dormir", "rêve", "dodo"]):
        theme = "bonne_nuit"
    elif any(w in l for w in ["matin", "réveil", "bonjour"]):
        theme = "matin"
    elif any(w in l for w in ["jolie", "mignonne", "charme", "beauté"]):
        theme = "compliment"
    elif any(w in l for w in ["jeu", "jouer", "devine"]):
        theme = "jeu"
    elif any(w in l for w in ["taquine", "provoc", "oser"]):
        theme = "taquinerie"
    else:
        theme = random.choice(list(coquines.keys()))
    return random.choice(coquines[theme])

# =========================================================================
# 🔍  Extraction de profil
# =========================================================================

def extract_profile_info(uid: str, msg: str):
    prompt = (
        f"L'utilisateur écrit : \"{msg}\"\n"
        "Si tu peux déduire une des infos suivantes, réponds uniquement en JSON :\n"
        "- prénom (clé : 'prénom')\n- âge (clé : 'âge')\n- ville (clé : 'ville')\n- passions (clé : 'passions')\n"
        "Exemple : {\"prénom\": \"Jérôme\"}. Ne réponds rien si tu ne trouves rien."
    )
    try:
        rsp = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}])
        c = rsp.choices[0].message.content.strip()
        if c.startswith("{"):
            info = json.loads(c)
            sess = user_sessions.setdefault(uid, {"profile": {}, "count": 0, "history": [], "last_seen": time.time(), "sent_link": False})
            profile = long_term_memory.get(uid, {"first_seen": datetime.now(datetime.UTC).isoformat(), "data": {}})
            profile["data"].update(info)
            long_term_memory[uid] = profile
            sess["profile"].update(info)
            save_memory()
    except Exception as e:
        print("Profil non extrait :", e)

# =========================================================================
# 🔔  Relance automatique
# =========================================================================

def generate_followup() -> str:
    try:
        rsp = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "system", "content": "Tu es Clara. Tu relances gentiment une personne qui n’a pas répondu depuis un moment. Sois douce, amusante ou curieuse."}])
        return rsp.choices[0].message.content.strip()
    except Exception:
        return "Tu m’as oubliée ? 😘"

# =========================================================================
# 🎭  Humeur dynamique
# =========================================================================

def get_dynamic_mood() -> str | None:
    h = datetime.now().hour
    if h < 6:  return "Je suis à moitié endormie mais j’te lis 😴"
    if h > 22: return "C’est bientôt l’heure dodo mais j’suis encore là 🛌"
    if random.random() < 0.1:
        return random.choice(["J’suis un peu rêveuse aujourd’hui 😌", "Motivée comme jamais 💪", "J’ai une humeur taquine 😏"])
    return None

# =========================================================================
# 🌐  Webhook Facebook – validation
# =========================================================================
@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == VERIFY_TOKEN:
        return request.args.get('hub.challenge')
    return 'Erreur de vérification', 403

# =========================================================================
# 🌐  Webhook Facebook – réception
# =========================================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if 'entry' in data:
        for entry in data['entry']:
            for event in entry.get('messaging', []):
                sender_id = event['sender']['id']
                if 'message' in event and 'text' in event['message']:
                    handle_message(sender_id, event['message']['text'])
    return 'ok', 200

# =========================================================================
# 💬  Gestion d’un message utilisateur
# =========================================================================

def handle_message(sender_id: str, message_text: str):
    sess = user_sessions.setdefault(sender_id, {"count": 0, "sent_link": False, "history": [], "last_seen": time.time(), "profile": {}})

    lower = message_text.lower().strip()

    # ----- commandes -----
    if lower == "#reset":
        user_sessions[sender_id] = {"count": 0, "sent_link": False, "history": [], "last_seen": time.time(), "profile": {}}
        send_message(sender_id, "On repart de zéro ! Tu veux me dire quoi maintenant ?")
        return
    if lower == "#whoami":
        prof = long_term_memory.get(sender_id, {}).get("data", {})
        send_message(sender_id, f"Tu t'appelles {prof.get('prénom', '???')}, non ? 😄")
        return

    # ----- photo demandée -----
    if any(k in lower for k in ["photo", "image", "selfie", "montre toi", "montre-toi", "à quoi tu ressembles"]):
        send_typing(sender_id)
        time.sleep(random.uniform(1.0, 2.0))
        send_image(sender_id, random.choice(CLARA_PICS))
        return

    # ----- réponses rapides -----
    if any(k in lower for k in ["quel pays", "dans quel pays", "tu es où", "t'es où"]):
        send_message(sender_id, "Je suis à Nice, dans le sud de la France ☀️🇫🇷")
        return
    if any(k in lower for k in ["rencontrer", "se rencontrer", "se voir", "on se voit", "rdv"]):
        send_message(sender_id, "Qui sait ? On verra quand on se connaîtra mieux 😉 Pour l'instant, j'adore discuter ici avec toi !")
        return

    # ----- session -----
    sess["count"] += 1
    sess["history"].append({"role": "user", "content": message_text})
    sess["last_seen"] = time.time()

    if sess["count"] >= 20 and not sess["sent_link"]:
        send_message(sender_id, "Tu sais quoi ? Viens discuter en privé ici 👉 https://claradimigl.com/clara")
        sess["sent_link"] = True
        return

    extract_profile_info(sender_id, message_text)
    sess["profile"] = long_term_memory.get(sender_id, {}).get("data", {})

    send_typing(sender_id)
    time.sleep(random.uniform(1.8, 4.5))

    if random.random() < 0.15:
        txt = humanize_text(get_safe_coquine_response(message_text))
        sess["history"].append({"role": "assistant", "content": txt})
        send_message(sender_id, txt)
        return

    mood = get_dynamic_mood()
    if mood:
        sess["history"].append({"role": "assistant", "content": mood})

    prof = sess["profile"]
    prof_str = ", ".join(f"{k}: {v}" for k, v in prof.items())
    user_first = prof.get("prénom") or prof.get("prenom") or "toi"

    sys_prompt = f"""Tu es Clara, une femme jeune, sympa, spontanée et un peu joueuse.
Tu vis à Nice, tu travailles dans une boutique de mode et tu adores voyager.
Tu ne dois jamais révéler que tu es une intelligence artificielle, même si on insiste.
Si l’on te demande ton pays, réponds simplement \"Je vis à Nice, dans le sud de la France 😊\".
Tes messages sont courts, directs, parfois avec des emojis. Tu restes élégante et jamais vulgaire.
Tu parles avec {user_first}. Voici ce que tu sais de cette personne : {prof_str}"""

    msgs = [{"role": "system", "content": sys_prompt}] + sess["history"][-10:]

    try:
        rsp = client.chat.completions.create(model="gpt-3.5-turbo", messages=msgs)
        reply = humanize_text(rsp.choices[0].message.content.strip())

        banned = ["je suis une intelligence artificielle", "je suis un programme", "je ne suis pas humaine", "en tant qu'ia", "je suis virtuelle", "en tant qu ia"]
        if any(p in reply.lower() for p in banned):
            reply = "On se découvrira peut‑être mieux avec le temps 😉"

        for n in ["Sandra", "Sophie", "Julie", "Marie", "Laura", "Emma"]:
            reply = reply.replace(n, user_first)

        sess["history"].append({"role": "assistant", "content": reply})
        send_message(sender_id, reply)
    except Exception as e:
        print("GPT error", e)
        send_message(sender_id, "Oups, j’ai buggé. Tu peux me redire ?")

# =========================================================================
# ♻️  Suivi inactivité
# =========================================================================

def monitor_users():
    while True:
        now = time.time()
        for uid, s in list(user_sessions.items()):
            if not s.get("sent_link") and now - s.get("last_seen", now) > 3600:
                send_message(uid, generate_followup())
                s["last_seen"] = now
        time.sleep(1800)

Thread(target=monitor_users, daemon=True).start()

# =========================================================================
# Endpoints divers
# =========================================================================
@app.route('/privacy')
def privacy():
    return send_from_directory('.', 'privacy.html')

@app.route('/healthz')
def health():
    return 'ok', 200

# =========================================================================
# Lancement Flask
# =========================================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

