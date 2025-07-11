from flask import Flask, request, render_template_string
import requests
import os
import datetime

app = Flask(__name__)

@app.route('/')
def home():
    try:
        selected_sport = request.args.get("sport", "").strip()
        selected_league = request.args.get("league", "").strip()
        selected_status = request.args.get("status", "").strip()

        api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?count=100&lng=fr&gr=70&mode=4&country=96&top=true"
        response = requests.get(api_url)
        matches = response.json().get("Value", [])

        sports_detected = set()
        leagues_detected = set()
        data = []

        for match in matches:
            try:
                league = match.get("LE", "–")
                team1 = match.get("O1", "–")
                team2 = match.get("O2", "–")
                sport = detect_sport(league).strip()
                sports_detected.add(sport)
                leagues_detected.add(league)

                # --- Score ---
                score1 = match.get("SC", {}).get("FS", {}).get("S1")
                score2 = match.get("SC", {}).get("FS", {}).get("S2")
                try:
                    score1 = int(score1) if score1 is not None else 0
                except:
                    score1 = 0
                try:
                    score2 = int(score2) if score2 is not None else 0
                except:
                    score2 = 0

                # --- Minute ---
                minute = None
                # Prendre d'abord SC.TS (temps écoulé en secondes)
                sc = match.get("SC", {})
                if "TS" in sc and isinstance(sc["TS"], int):
                    minute = sc["TS"] // 60
                elif "ST" in sc and isinstance(sc["ST"], int):
                    minute = sc["ST"]
                elif "T" in match and isinstance(match["T"], int):
                    minute = match["T"] // 60

                # --- Statut ---
                tn = match.get("TN", "").lower()
                tns = match.get("TNS", "").lower()
                tt = match.get("SC", {}).get("TT")
                statut = "À venir"
                is_live = False
                is_finished = False
                is_upcoming = False
                if (minute is not None and minute > 0) or (score1 > 0 or score2 > 0):
                    statut = f"En cours ({minute}′)" if minute else "En cours"
                    is_live = True
                if ("terminé" in tn or "terminé" in tns) or (tt == 3):
                    statut = "Terminé"
                    is_live = False
                    is_finished = True
                if statut == "À venir":
                    is_upcoming = True

                if selected_sport and sport != selected_sport:
                    continue
                if selected_league and league != selected_league:
                    continue
                if selected_status == "live" and not is_live:
                    continue
                if selected_status == "finished" and not is_finished:
                    continue
                if selected_status == "upcoming" and not is_upcoming:
                    continue

                match_ts = match.get("S", 0)
                match_time = datetime.datetime.utcfromtimestamp(match_ts).strftime('%d/%m/%Y %H:%M') if match_ts else "–"

                # --- Cotes ---
                odds_data = []
                # 1. Chercher dans E (G=1)
                for o in match.get("E", []):
                    if o.get("G") == 1 and o.get("T") in [1, 2, 3] and o.get("C") is not None:
                        odds_data.append({
                            "type": {1: "1", 2: "2", 3: "X"}.get(o.get("T")),
                            "cote": o.get("C")
                        })
                # 2. Sinon, chercher dans AE
                if not odds_data:
                    for ae in match.get("AE", []):
                        if ae.get("G") == 1:
                            for o in ae.get("ME", []):
                                if o.get("T") in [1, 2, 3] and o.get("C") is not None:
                                    odds_data.append({
                                        "type": {1: "1", 2: "2", 3: "X"}.get(o.get("T")),
                                        "cote": o.get("C")
                                    })
                if not odds_data:
                    formatted_odds = ["Pas de cotes disponibles"]
                else:
                    formatted_odds = [f"{od['type']}: {od['cote']}" for od in odds_data]

                prediction = "–"
                if odds_data:
                    best = min(odds_data, key=lambda x: x["cote"])
                    prediction = {
                        "1": f"{team1} gagne",
                        "2": f"{team2} gagne",
                        "X": "Match nul"
                    }.get(best["type"], "–")

                # --- Météo ---
                meteo_data = match.get("MIS", [])
                temp = next((item["V"] for item in meteo_data if item.get("K") == 9), "–")
                humid = next((item["V"] for item in meteo_data if item.get("K") == 27), "–")

                data.append({
                    "team1": team1,
                    "team2": team2,
                    "score1": score1,
                    "score2": score2,
                    "league": league,
                    "sport": sport,
                    "status": statut,
                    "datetime": match_time,
                    "temp": temp,
                    "humid": humid,
                    "odds": formatted_odds,
                    "prediction": prediction,
                    "id": match.get("I", None)
                })
            except Exception as e:
                print(f"Erreur lors du traitement d'un match: {e}")
                continue

        # --- Pagination ---
        try:
            page = int(request.args.get('page', 1))
        except:
            page = 1
        per_page = 20
        total = len(data)
        total_pages = (total + per_page - 1) // per_page
        data_paginated = data[(page-1)*per_page:page*per_page]

        return render_template_string(TEMPLATE, data=data_paginated,
            sports=sorted(sports_detected),
            leagues=sorted(leagues_detected),
            selected_sport=selected_sport or "Tous",
            selected_league=selected_league or "Toutes",
            selected_status=selected_status or "Tous",
            page=page,
            total_pages=total_pages
        )

    except Exception as e:
        return f"Erreur : {e}"

def detect_sport(league_name):
    league = league_name.lower()
    if any(word in league for word in ["wta", "atp", "tennis"]):
        return "Tennis"
    elif any(word in league for word in ["basket", "nbl", "nba", "ipbl"]):
        return "Basketball"
    elif "hockey" in league:
        return "Hockey"
    elif any(word in league for word in ["tbl", "table"]):
        return "Table Basketball"
    elif "cricket" in league:
        return "Cricket"
    else:
        return "Football"

@app.route('/match/<int:match_id>')
def match_details(match_id):
    try:
        # Récupérer les données de l'API (ou brute.json si besoin)
        api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?count=100&lng=fr&gr=70&mode=4&country=96&top=true"
        response = requests.get(api_url)
        matches = response.json().get("Value", [])
        match = next((m for m in matches if m.get("I") == match_id), None)
        if not match:
            return f"Aucun match trouvé pour l'identifiant {match_id}"
        # Infos principales
        team1 = match.get("O1", "–")
        team2 = match.get("O2", "–")
        league = match.get("LE", "–")
        sport = detect_sport(league)
        # Scores
        score1 = match.get("SC", {}).get("FS", {}).get("S1")
        score2 = match.get("SC", {}).get("FS", {}).get("S2")
        try:
            score1 = int(score1) if score1 is not None else 0
        except:
            score1 = 0
        try:
            score2 = int(score2) if score2 is not None else 0
        except:
            score2 = 0
        # Statistiques avancées
        stats = []
        st = match.get("SC", {}).get("ST", [])
        if st and isinstance(st, list) and len(st) > 0 and "Value" in st[0]:
            for stat in st[0]["Value"]:
                nom = stat.get("N", "?")
                s1 = stat.get("S1", "0")
                s2 = stat.get("S2", "0")
                stats.append({"nom": nom, "s1": s1, "s2": s2})
        # Explication prédiction (simple)
        explication = "La prédiction est basée sur les cotes et les statistiques principales (tirs, possession, etc.)."  # Peut être enrichi
        # Prédiction
        odds_data = []
        for o in match.get("E", []):
            if o.get("G") == 1 and o.get("T") in [1, 2, 3] and o.get("C") is not None:
                odds_data.append({
                    "type": {1: "1", 2: "2", 3: "X"}.get(o.get("T")),
                    "cote": o.get("C")
                })
        if not odds_data:
            for ae in match.get("AE", []):
                if ae.get("G") == 1:
                    for o in ae.get("ME", []):
                        if o.get("T") in [1, 2, 3] and o.get("C") is not None:
                            odds_data.append({
                                "type": {1: "1", 2: "2", 3: "X"}.get(o.get("T")),
                                "cote": o.get("C")
                            })
        prediction = "–"
        if odds_data:
            best = min(odds_data, key=lambda x: x["cote"])
            prediction = {
                "1": f"{team1} gagne",
                "2": f"{team2} gagne",
                "X": "Match nul"
            }.get(best["type"], "–")
        # HTML avec graphiques Chart.js CDN
        return f'''
        <!DOCTYPE html>
        <html><head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Détails du match</title>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                body {{ font-family: Arial; padding: 20px; background: #f4f4f4; }}
                .container {{ max-width: 700px; margin: auto; background: white; border-radius: 10px; box-shadow: 0 2px 8px #ccc; padding: 20px; }}
                h2 {{ text-align: center; }}
                .stats-table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                .stats-table th, .stats-table td {{ border: 1px solid #ccc; padding: 8px; text-align: center; }}
                .back-btn {{ margin-bottom: 20px; display: inline-block; }}
            </style>
        </head><body>
            <div class="container">
                <a href="/" class="back-btn">&larr; Retour à la liste</a>
                <h2>{team1} vs {team2}</h2>
                <p><b>Ligue :</b> {league} | <b>Sport :</b> {sport}</p>
                <p><b>Score :</b> {score1} - {score2}</p>
                <p><b>Prédiction du bot :</b> {prediction}</p>
                <p><b>Explication :</b> {explication}</p>
                <h3>Statistiques principales</h3>
                <table class="stats-table">
                    <tr><th>Statistique</th><th>{team1}</th><th>{team2}</th></tr>
                    {''.join(f'<tr><td>{s["nom"]}</td><td>{s["s1"]}</td><td>{s["s2"]}</td></tr>' for s in stats)}
                </table>
                <canvas id="statsChart" height="200"></canvas>
            </div>
            <script>
                const labels = { [repr(s['nom']) for s in stats] };
                const data1 = { [float(s['s1']) if s['s1'].replace('.', '', 1).isdigit() else 0 for s in stats] };
                const data2 = { [float(s['s2']) if s['s2'].replace('.', '', 1).isdigit() else 0 for s in stats] };
                new Chart(document.getElementById('statsChart'), {{
                    type: 'bar',
                    data: {{
                        labels: labels,
                        datasets: [
                            {{ label: '{team1}', data: data1, backgroundColor: 'rgba(44,62,80,0.7)' }},
                            {{ label: '{team2}', data: data2, backgroundColor: 'rgba(39,174,96,0.7)' }}
                        ]
                    }},
                    options: {{ responsive: true, plugins: {{ legend: {{ position: 'top' }} }} }}
                }});
            </script>
        </body></html>
        '''
    except Exception as e:
        return f"Erreur lors de l'affichage des détails du match : {e}"

TEMPLATE = """<!DOCTYPE html>
<html><head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Live Football & Sports | Prédictions & Stats</title>
    <link rel="icon" type="image/png" href="https://cdn-icons-png.flaticon.com/512/197/197604.png">
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; background: #f4f4f4; }
        h2 { text-align: center; }
        form { text-align: center; margin-bottom: 20px; }
        label { font-weight: bold; margin-right: 10px; }
        select { padding: 12px; margin: 0 10px; font-size: 16px; border-radius: 6px; border: 1px solid #2c3e50; background: #fff; color: #2c3e50; }
        select:focus { outline: 2px solid #2980b9; }
        table { border-collapse: collapse; margin: auto; width: 98%; background: white; }
        th, td { padding: 14px; border: 1.5px solid #2c3e50; text-align: center; font-size: 16px; }
        th { background: #1a252f; color: #fff; font-size: 18px; }
        tr:nth-child(even) { background-color: #eaf6fb; }
        tr:nth-child(odd) { background-color: #f9f9f9; }
        .pagination { text-align: center; margin: 20px 0; }
        .pagination button { padding: 14px 24px; margin: 0 6px; font-size: 18px; border: none; background: #2980b9; color: #fff; border-radius: 6px; cursor: pointer; font-weight: bold; transition: background 0.2s; }
        .pagination button:disabled { background: #b2bec3; color: #636e72; cursor: not-allowed; }
        .pagination button:focus { outline: 2px solid #27ae60; }
        /* Responsive */
        @media (max-width: 800px) {
            table, thead, tbody, th, td, tr { display: block; }
            th { position: absolute; left: -9999px; top: -9999px; }
            tr { margin-bottom: 15px; background: white; border-radius: 8px; box-shadow: 0 2px 6px #ccc; }
            td { border: none; border-bottom: 1px solid #eee; position: relative; padding-left: 50%; min-height: 40px; font-size: 16px; }
            td:before { position: absolute; top: 10px; left: 10px; width: 45%; white-space: nowrap; font-weight: bold; color: #2980b9; }
            td:nth-of-type(1):before { content: 'Équipe 1'; }
            td:nth-of-type(2):before { content: 'Score 1'; }
            td:nth-of-type(3):before { content: 'Score 2'; }
            td:nth-of-type(4):before { content: 'Équipe 2'; }
            td:nth-of-type(5):before { content: 'Sport'; }
            td:nth-of-type(6):before { content: 'Ligue'; }
            td:nth-of-type(7):before { content: 'Statut'; }
            td:nth-of-type(8):before { content: 'Date & Heure'; }
            td:nth-of-type(9):before { content: 'Température'; }
            td:nth-of-type(10):before { content: 'Humidité'; }
            td:nth-of-type(11):before { content: 'Cotes'; }
            td:nth-of-type(12):before { content: 'Prédiction'; }
            td:nth-of-type(13):before { content: 'Détails'; }
        }
        /* Loader */
        #loader { display: none; position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; background: rgba(255,255,255,0.7); z-index: 9999; justify-content: center; align-items: center; }
        #loader .spinner { border: 8px solid #f3f3f3; border-top: 8px solid #2980b9; border-radius: 50%; width: 60px; height: 60px; animation: spin 1s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        /* Focus visible for accessibility */
        a:focus, button:focus, select:focus { outline: 2px solid #27ae60; }
    </style>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            var forms = document.querySelectorAll('form');
            forms.forEach(function(form) {
                form.addEventListener('submit', function() {
                    document.getElementById('loader').style.display = 'flex';
                });
            });
        });
    </script>
</head><body>
    <div id="loader" role="status" aria-live="polite"><div class="spinner" aria-label="Chargement"></div></div>
    <h2>📊 Matchs en direct — {{ selected_sport }} / {{ selected_league }} / {{ selected_status }}</h2>

    <form method="get" aria-label="Filtres de matchs">
        <label for="sport-select">Sport :</label>
        <select id="sport-select" name="sport" onchange="this.form.submit()" aria-label="Filtrer par sport">
            <option value="">Tous</option>
            {% for s in sports %}
                <option value="{{s}}" {% if s == selected_sport %}selected{% endif %}>{{s}}</option>
            {% endfor %}
        </select>
        <label for="league-select">Ligue :</label>
        <select id="league-select" name="league" onchange="this.form.submit()" aria-label="Filtrer par ligue">
            <option value="">Toutes</option>
            {% for l in leagues %}
                <option value="{{l}}" {% if l == selected_league %}selected{% endif %}>{{l}}</option>
            {% endfor %}
        </select>
        <label for="status-select">Statut :</label>
        <select id="status-select" name="status" onchange="this.form.submit()" aria-label="Filtrer par statut">
            <option value="">Tous</option>
            <option value="live" {% if selected_status == "live" %}selected{% endif %}>En direct</option>
            <option value="upcoming" {% if selected_status == "upcoming" %}selected{% endif %}>À venir</option>
            <option value="finished" {% if selected_status == "finished" %}selected{% endif %}>Terminé</option>
        </select>
    </form>

    <div class="pagination">
        <form method="get" style="display:inline;" aria-label="Page précédente">
            <input type="hidden" name="sport" value="{{ selected_sport if selected_sport != 'Tous' else '' }}">
            <input type="hidden" name="league" value="{{ selected_league if selected_league != 'Toutes' else '' }}">
            <input type="hidden" name="status" value="{{ selected_status if selected_status != 'Tous' else '' }}">
            <button type="submit" name="page" value="{{ page-1 }}" {% if page <= 1 %}disabled{% endif %} aria-label="Page précédente">Page précédente</button>
        </form>
        <span aria-live="polite">Page {{ page }} / {{ total_pages }}</span>
        <form method="get" style="display:inline;" aria-label="Page suivante">
            <input type="hidden" name="sport" value="{{ selected_sport if selected_sport != 'Tous' else '' }}">
            <input type="hidden" name="league" value="{{ selected_league if selected_league != 'Toutes' else '' }}">
            <input type="hidden" name="status" value="{{ selected_status if selected_status != 'Tous' else '' }}">
            <button type="submit" name="page" value="{{ page+1 }}" {% if page >= total_pages %}disabled{% endif %} aria-label="Page suivante">Page suivante</button>
        </form>
    </div>

    <table>
        <tr>
            <th>Équipe 1</th><th>Score 1</th><th>Score 2</th><th>Équipe 2</th>
            <th>Sport</th><th>Ligue</th><th>Statut</th><th>Date & Heure</th>
            <th>Température</th><th>Humidité</th><th>Cotes</th><th>Prédiction</th><th>Détails</th>
        </tr>
        {% for m in data %}
        <tr>
            <td>{{m.team1}}</td><td>{{m.score1}}</td><td>{{m.score2}}</td><td>{{m.team2}}</td>
            <td>{{m.sport}}</td><td>{{m.league}}</td><td>{{m.status}}</td><td>{{m.datetime}}</td>
            <td>{{m.temp}}°C</td><td>{{m.humid}}%</td><td>{{m.odds|join(" | ")}}</td><td>{{m.prediction}}</td>
            <td>{% if m.id %}<a href="/match/{{m.id}}"><button>Détails</button></a>{% else %}–{% endif %}</td>
        </tr>
        {% endfor %}
    </table>
</body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
