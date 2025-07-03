from flask import Flask, request
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Messenger GPT actif !"

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        verify_token = "TON_TOKEN"
        if request.args.get("hub.verify_token") == verify_token:
            return request.args.get("hub.challenge")
        return "Erreur de vérification"
    elif request.method == 'POST':
        data = request.json
        # ici tu peux traiter le message
        return "OK", 200
