from flask import Flask, render_template_string
import requests
import os

app = Flask(__name__)

@app.route('/')
def home():
    try:
        api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?count=100&lng=fr&gr=70&mode=4&country=96&top=true"
        response = requests.get(api_url)
        matches = response.json().get("Value", [])

        data = []
        for match in matches:
            try:
                odds_data = []
                prediction = "–"
                
                # Récupère les cotes depuis Markets > E
                for market in match.get("Markets", []):
                    if market.get("G") == 1:
                        events = market.get("E", [])
                        for o in events:
                            label = {1: '1', 2: '2', 3: 'X'}.get(o.get("T"))
                            if label and o.get("C"):
                                odds_data.append({
                                    "label": label,
                                    "cote": o.get("C")
                                })

                # Format affichable des cotes
                formatted_odds = [f"{od['label']}: {od['cote']}" for od in odds_data]

                # Déterminer une prédiction simple basée sur la plus faible cote
                if odds_data:
                    best = min(odds_data, key=lambda x: x["cote"])
                    if best["label"] == "1":
                        prediction = f"{match.get('O1', 'Équipe 1')} gagne"
                    elif best["label"] == "2":
                        prediction = f"{match.get('O2', 'Équipe 2')} gagne"
                    elif best["label"] == "X":
                        prediction = "Match nul"

                data.append({
                    "match": f"{match.get('O1', '–')} vs {match.get('O2', '–')}",
                    "league": match.get("LE", "–"),
                    "score": match.get("SC", {}).get("FS", {}).get("S1", "–"),
                    "temp": match.get("MIS", [{}]*10)[2].get("V", "–"),
                    "humid": match.get("MIS", [{}]*10)[8].get("V", "–"),
                    "odds": formatted_odds or ["–"],
                    "prediction": prediction
                })
            except:
                continue

        return render_template_string(TEMPLATE, data=data)

    except Exception as e:
        return f"Erreur : {e}"

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>1xBet Live</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            padding: 20px;
            background: #f4f4f4;
        }
        h2 {
            text-align: center;
            color: #333;
        }
        table {
            border-collapse: collapse;
            margin: auto;
            width: 95%;
            background: white;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }
        th, td {
            padding: 12px;
            text-align: center;
            border: 1px solid #ddd;
        }
        th {
            background-color: #2ecc71;
            color: white;
        }
        tr:nth-child(even) {
            background-color: #f9f9f9;
        }
    </style>
</head>
<body>
    <h2>⚽ Matchs en direct 1xBet</h2>
    <table>
        <tr>
            <th>Match</th><th>League</th><th>Score</th>
            <th>Température</th><th>Humidité</th><th>Cotes</th><th>Prédiction</th>
        </tr>
        {% for m in data %}
        <tr>
            <td>{{m.match}}</td><td>{{m.league}}</td><td>{{m.score}}</td>
            <td>{{m.temp}}°C</td><td>{{m.humid}}%</td><td>{{m.odds|join(" | ")}}</td><td>{{m.prediction}}</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
