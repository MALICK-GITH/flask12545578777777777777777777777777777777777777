from flask import Flask, request, render_template_string
import requests
import os

app = Flask(__name__)

@app.route('/')
def home():
    try:
        selected_sport = request.args.get("sport", "")

        api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?count=100&lng=fr&gr=70&mode=4&country=96&top=true"
        response = requests.get(api_url)
        matches = response.json().get("Value", [])

        sports_detected = set()
        data = []

        for match in matches:
            try:
                league = match.get("LE", "–")
                team1 = match.get("O1", "–")
                team2 = match.get("O2", "–")
                sport = detect_sport(league)
                sports_detected.add(sport)

                if selected_sport and sport != selected_sport:
                    continue

                s1 = match.get("SC", {}).get("FS", {}).get("S1", "–")
                s2 = match.get("SC", {}).get("FS", {}).get("S2", "–")
                score = f"{team1}: {s1} — {team2}: {s2}"

                minute = match.get("SC", {}).get("ST")
                if isinstance(minute, int):
                    status = f"En cours ({minute}′)"
                elif match.get("SC", {}).get("TT") == 3:
                    status = "Terminé"
                else:
                    status = "À venir"

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

                meteo_data = match.get("MIS", [{}]*10)
                temp = meteo_data[2].get("V", "–")
                humid = meteo_data[8].get("V", "–")

                data.append({
                    "match": f"{team1} vs {team2}",
                    "league": league,
                    "score": score,
                    "status": status,
                    "temp": temp,
                    "humid": humid,
                    "odds": formatted_odds,
                    "prediction": prediction
                })
            except:
                continue

        return render_template_string(TEMPLATE, data=data, sports=sorted(sports_detected), selected_sport=selected_sport or "Tous les sports")

    except Exception as e:
        return f"Erreur : {e}"

def detect_sport(league_name):
    league = league_name.lower()
    if any(word in league for word in ["wta", "atp", "tennis"]):
        return "Tennis"
    elif any(word in league for word in ["nbl", "ipbl", "basket"]):
        return "Basketball"
    elif "hockey" in league:
        return "Hockey"
    elif any(word in league for word in ["tbl", "table"]):
        return "Table Basketball"
    else:
        return "Football"

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Matchs en direct</title>
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; background: #f4f4f4; }
        h2 { text-align: center; margin-bottom: 10px; }
        form { text-align: center; margin-bottom: 20px; }
        select { padding: 8px; font-size: 14px; }
        table { border-collapse: collapse; margin: auto; width: 95%; background: white; }
        th, td { padding: 10px; border: 1px solid #ccc; text-align: center; }
        th { background: #3498db; color: white; }
        tr:nth-child(even) { background-color: #f9f9f9; }
    </style>
</head>
<body>
    <h2>📊 Matchs en direct – {{ selected_sport }}</h2>

    <form method="get">
        <label for="sport">Choisir un sport :</label>
        <select name="sport" onchange="this.form.submit()">
            <option value="">Tous les sports</option>
            {% for s in sports %}
                <option value="{{s}}" {% if s == selected_sport %}selected{% endif %}>{{s}}</option>
            {% endfor %}
        </select>
    </form>

    <table>
        <tr>
            <th>Match</th><th>Ligue</th><th>Score</th><th>Statut</th>
            <th>Température</th><th>Humidité</th><th>Cotes</th><th>Prédiction</th>
        </tr>
        {% for m in data %}
        <tr>
            <td>{{m.match}}</td><td>{{m.league}}</td><td>{{m.score}}</td><td>{{m.status}}</td>
            <td>{{m.temp}}°C</td><td>{{m.humid}}%</td><td>{{m.odds|join(" | ")}}</td><td>{{m.prediction}}</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
