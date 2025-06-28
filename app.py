from flask import Flask, render_template_string
import requests
import os  # ← ajouté ici pour accéder à la variable PORT

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
                data.append({
                    "match": f"{match['O1']} vs {match['O2']}",
                    "league": match.get("LE", ""),
                    "score": match.get("SC", {}).get("FS", {}).get("S1", "–"),
                    "temp": match.get("MIS", [{}]*10)[2].get("V", "–"),
                    "humid": match.get("MIS", [{}]*10)[8].get("V", "–"),
                    "odds": [f"{ {1:'1',2:'2',3:'X'}.get(m.get('T')) }: {m.get('C')}" 
                             for m in match.get("Markets", []) if m.get("G") == 1]
                })
            except:
                continue

        return render_template_string(TEMPLATE, data=data)

    except Exception as e:
        return f"Erreur : {e}"

TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>1xBet Live</title></head>
<body>
    <h2>⚽ Matchs en direct 1xBet</h2>
    <table border="1">
        <tr>
            <th>Match</th><th>League</th><th>Score</th>
            <th>Température</th><th>Humidité</th><th>Cotes</th>
        </tr>
        {% for m in data %}
        <tr>
            <td>{{m.match}}</td><td>{{m.league}}</td><td>{{m.score}}</td>
            <td>{{m.temp}}°C</td><td>{{m.humid}}%</td><td>{{m.odds|join(" | ")}}</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""

# 👉 Ce bloc permet à Render de détecter correctement l'application
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
