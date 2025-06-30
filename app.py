
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

@app.route("/")
def home():
    return "Bienvenue sur l'API de prédiction SOLITAIRE HACK !<br>Créateur : SOLITAIRE HACK<br>Telegram : @Roidesombres225<br>Canal : https://t.me/SOLITAIREHACK"

# --- Logique de prédiction importée de fifa site.py ---
def charger_donnees_json_depuis_api(country_code=225, count=50):
    url = f"https://1xbet.com/LiveFeed/Get1x2_VZip?sports=85&count={count}&lng=fr&gr=70&mode=4&country={country_code}&getEmpty=true"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return None

def prediction_fiable(match):
    cotes = { '1': None, 'N': None, '2': None }
    for e in match.get('E', []):
        if e.get('G') == 1:
            if e.get('T') == 1:
                cotes['1'] = e.get('C')
            elif e.get('T') == 2:
                cotes['N'] = e.get('C')
            elif e.get('T') == 3:
                cotes['2'] = e.get('C')
    prediction = min((v, k) for k, v in cotes.items() if v is not None)[1] if any(cotes.values()) else None
    return prediction, cotes

@app.route("/predict", methods=["GET"])
def predict():
    pays = request.args.get('pays', default='', type=str)
    country_code = request.args.get('country_code', default=225, type=int)
    count = request.args.get('count', default=50, type=int)
    if not pays:
        return jsonify({"error": "Veuillez fournir le paramètre 'pays' dans l'URL."}), 400
    data = charger_donnees_json_depuis_api(country_code, count)
    if not data or not data.get('Success'):
        return jsonify({"error": "Impossible de récupérer les données depuis l'API externe."}), 500
    matchs = data.get('Value', [])
    resultats = []
    for match in matchs:
        if pays.lower() in match.get('CN', '').lower() or pays.lower() in match.get('CE', '').lower():
            equipe1 = match.get('O1', 'Inconnu')
            equipe2 = match.get('O2', 'Inconnu')
            ligue = match.get('LE', match.get('L', ''))
            date = match.get('S', '-')
            prediction, cotes = prediction_fiable(match)
            if prediction == '1':
                resultat = f"Victoire probable : {equipe1}"
            elif prediction == '2':
                resultat = f"Victoire probable : {equipe2}"
            elif prediction == 'N':
                resultat = "Match nul probable"
            else:
                resultat = "Prédiction indisponible"
            resultats.append({
                "ligue": ligue,
                "equipe1": equipe1,
                "equipe2": equipe2,
                "date": date,
                "resultat": resultat,
                "cotes": cotes
            })
    return jsonify({
        "createur": "SOLITAIRE HACK",
        "telegram": "@Roidesombres225",
        "canal": "https://t.me/SOLITAIREHACK",
        "pays": pays,
        "resultats": resultats
    })

# Tu pourras ajouter ici d'autres routes pour l'API de prédiction 
