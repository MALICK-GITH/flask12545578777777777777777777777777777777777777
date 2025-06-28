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
                team1 = match.get("O1", "–")
                team2 = match.get("O2", "–")

                # Score par équipe
                s1 = match.get("SC", {}).get("FS", {}).get("S1", "–")
                s2 = match.get("SC", {}).get("FS", {}).get("S2", "–")
                score = f"{team1}: {s1} — {team2}: {s2}"

                # Statut
                minute = match.get("SC", {}).get("ST")
                if isinstance(minute, int):
                    status = f"En cours ({minute}′)"
                elif match.get("SC", {}).get("TT") == 3:
                    status = "Terminé"
                else:
                    status = "À venir"

                # Cotes et prédiction
                odds_data = []
                for market in match.get("Markets", []):
                    if market.get("G") == 1:
                        for o in market.get("E", []):
                            t = o.get("T")
                            if t in [1, 2, 3]:
                                odds_data.append({
                                    "type": {1: "1", 2: "2", 3: "X"}.get(t),
                                    "cote": o.get("C")
                                })

                formatted_odds = [f"{od['type']}: {od['cote']}" for od in odds_data] or ["–"]

                prediction = "–"
                if odds_data:
                    best = min(odds_data, key=lambda x: x["cote"])
                    prediction = {
                        "1": f"{team1} gagne",
                        "2": f"{team2} gagne",
                        "X": "Match nul"
                    }.get(best["type"], "–")

                # Météo
                meteo_data = match.get("MIS", [{}]*10)
                temp = meteo_data[2].get("V", "–")
                humid = meteo_data[8].get("V", "–")

                data.append({
                    "match": f"{team1} vs {team2}",
                    "league": match.get("LE", "–"),
                    "score": score,
                    "status": status,
                    "temp": temp,
                    "humid": humid,
                    "odds": formatted_odds,
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
        body { font-family: Arial, sans-serif; padding: 20px; background: #f4f4f4; }
        h2 { text-align: center; color: #333; }
        table { border-collapse: collapse; margin: auto; width: 95%; background: white; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        th, td { padding: 12px; border: 1px solid #ddd; text-align: center; }
        th { background: #2ecc71; color: white; }
        tr:nth-child(even) { background: #f9f9f9; }
    </style>
</head>
<body>
    <h2>⚽ Matchs en direct 1xBet</h2>
    <table>
        <tr>
            <th>Match</th>
            <th>Ligue</th>
            <th>Score</th>
            <th>Statut</th>
            <th>Température</th>
            <th>Humidité</th>
            <th>Cotes</th>
            <th>Prédiction</th>
        </tr>
        {% for m in data %}
        <tr>
            <td>{{m.match}}</td>
            <td>{{m.league}}</td>
            <td>{{m.score}}</td>
            <td>{{m.status}}</td>
            <td>{{m.temp}}°C</td>
            <td>{{m.humid}}%</td>
            <td>{{m.odds|join(" | ")}}</td>
            <td>{{m.prediction}}</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
