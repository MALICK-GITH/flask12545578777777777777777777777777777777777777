from flask import Flask, request, render_template_string, jsonify
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

        api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?sports=85&count=50&lng=fr&gr=70&mode=4&country=96&getEmpty=true"
        response = requests.get(api_url)
        matches = response.json().get("Value", [])

        sports_detected = set()
        leagues_detected = set()
        data = []

        for match in matches:
            try:
                # Ajout des clés manquantes pour compatibilité
                required_keys = {
                    "O1": "–",
                    "O2": "–",
                    "LE": "–",
                    "AE": [],
                    "MIS": [],
                    "I": None,
                    "T": None,
                    "TN": "",
                    "TNS": "",
                    "SE": "",
                    "SN": ""
                }
                for key, default in required_keys.items():
                    if key not in match:
                        match[key] = default
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

                # --- Statut officiel ---
                statut_officiel = match.get('TN') or match.get('TNS')

                # --- Heure de fin estimée ---
                heure_fin = "–"
                if match_ts and statut.startswith("En cours"):
                    if sport == "Football":
                        fin_ts = match_ts + 2*3600  # 2h
                    elif sport == "Basketball":
                        fin_ts = match_ts + 90*60  # 1h30
                    else:
                        fin_ts = match_ts + 2*3600
                    heure_fin = datetime.datetime.utcfromtimestamp(fin_ts).strftime('%d/%m/%Y %H:%M')

                data.append({
                    "team1": team1,
                    "team2": team2,
                    "score1": score1,
                    "score2": score2,
                    "league": league,
                    "sport": sport,
                    "status": statut,
                    "status_officiel": statut_officiel,
                    "datetime": match_time,
                    "temp": temp,
                    "humid": humid,
                    "odds": formatted_odds,
                    "prediction": prediction,
                    "heure_fin": heure_fin,
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
        api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?sports=85&count=50&lng=fr&gr=70&mode=4&country=96&getEmpty=true"
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
        # Section toutes les options de paris
        def render_all_options(match):
            html = '<h3>Toutes les options de paris</h3>'
            # Cotes principales (E)
            if match.get('E'):
                html += '<b>1X2 :</b><ul>'
                for o in match['E']:
                    t = o.get('T')
                    label = {1: 'Victoire ' + team1, 2: 'Match nul', 3: 'Victoire ' + team2}.get(t, f'Option {t}')
                    html += f'<li>{label} : {o.get("C", "–")}</li>'
                html += '</ul>'
            # Cotes alternatives (AE)
            if match.get('AE'):
                for ae in match['AE']:
                    g = ae.get('G')
                    html += f'<ul>'
                    for me in ae.get('ME', []):
                        p = me.get('P', '')
                        t = me.get('T', '')
                        c = me.get('C', '–')
                        traduction = traduire_option_pari(g, t, p)
                        html += f'<li>{traduction} : {c}</li>'
                    html += '</ul>'
            return html
        def render_predictor(match):
            min_cote = 1.399
            max_cote = 3.0
            predictions = []
            for ae in match.get('AE', []):
                g = ae.get('G')
                if g not in [2, 17]:
                    continue
                for me in ae.get('ME', []):
                    c = me.get('C')
                    t = me.get('T')
                    p = me.get('P')
                    if c and min_cote <= c <= max_cote:
                        traduction = traduire_option_pari(g, t, p)
                        proba = round(1/float(c), 3) if c else '?' 
                        predictions.append({
                            'traduction': traduction,
                            'cote': c,
                            'proba': proba
                        })
            html = '<h3>Prédicteur alternatives (Handicap & Over/Under, cotes 1.399 à 3)</h3>'
            if predictions:
                # Mettre en avant la meilleure prédiction (plus forte proba)
                best = max(predictions, key=lambda x: x['proba'])
                html += f'<div style="background:#27ae60;color:white;padding:8px 15px;border-radius:8px;font-weight:bold;margin-bottom:10px;">Meilleure prédiction : {best["traduction"]} | Cote: {best["cote"]} | Proba: {best["proba"]}</div>'
                html += '<ul>'
                for pred in predictions:
                    html += f'<li>{pred["traduction"]} | Cote: {pred["cote"]} | Proba: {pred["proba"]}</li>'
                html += '</ul>'
            else:
                html += '<p>Aucune prédiction alternative disponible dans la fourchette demandée.</p>'
            return html
        # Statut officiel pour la page de détails
        statut_officiel = match.get('TN') or match.get('TNS')
        # HTML avec graphiques Chart.js CDN
        return f'''
        <!DOCTYPE html>
        <html><head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <meta http-equiv="refresh" content="5">
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
                <p><b>Statut officiel :</b> {statut_officiel or '–'}</p>
                <p><b>Prédiction du bot :</b> {prediction}</p>
                <p><b>Explication :</b> {explication}</p>
                <h3>Statistiques principales</h3>
                <table class="stats-table">
                    <tr><th>Statistique</th><th>{team1}</th><th>{team2}</th></tr>
                    {''.join(f'<tr><td>{s["nom"]}</td><td>{s["s1"]}</td><td>{s["s2"]}</td></tr>' for s in stats)}
                </table>
                <canvas id="statsChart" height="200"></canvas>
                <div id="details-match">
                {details_match_ajax(match_id)}
                </div>
                <script>
                setInterval(function() {{
                    fetch('/details-match-ajax/{match_id}')
                      .then(response => response.text())
                      .then(html => {{
                        document.getElementById('details-match').innerHTML = html;
                      }});
                }}, 5000);
                </script>
            </div>
            <footer style="text-align:center; margin-top:40px; color:#888; font-size:15px;">
              Créateur : <b>SOLITAIRE HACK</b><br>
              Télégram : <a href="https://t.me/Roidesombres225" target="_blank">@Roidesombres225</a><br>
              Canal : <a href="https://t.me/SOLITAIREHACK" target="_blank">https://t.me/SOLITAIREHACK</a>
            </footer>
        </body></html>
        '''
    except Exception as e:
        return f"Erreur lors de l'affichage des détails du match : {e}"

def format_parametre(parametre):
    try:
        return f"{float(parametre):+g}"
    except (TypeError, ValueError):
        return str(parametre) if parametre is not None else "?"

def traduire_option_pari(type_pari, resultat, parametre):
    type_map = {2: 'Handicap', 17: 'Over/Under'}
    type_str = type_map.get(type_pari, f'Groupe {type_pari}')
    if type_pari == 2:  # Handicap
        if resultat == 7:
            return f"{type_str} équipe 2 ({format_parametre(parametre)})"
        elif resultat == 8:
            return f"{type_str} équipe 1 ({format_parametre(parametre)})"
        else:
            return f"{type_str} (T={resultat}, P={parametre})"
    elif type_pari == 17:  # Over/Under
        if resultat == 9:
            return f"Plus de {parametre} buts"
        elif resultat == 10:
            return f"Moins de {parametre} buts"
        else:
            return f"{type_str} (T={resultat}, P={parametre})"
    else:
        return f"{type_str} (T={resultat}, P={parametre})"

# Fonction utilitaire pour ajouter le meta refresh sur les pages HTML simples
def add_refresh(html):
    if '<head>' in html:
        return html.replace('<head>', '<head>\n<meta http-equiv="refresh" content="5">', 1)
    return html

@app.route('/paris-alternatifs-ajax')
def paris_alternatifs_ajax():
    min_cote = float(request.args.get('min_cote', 1.399))
    max_cote = float(request.args.get('max_cote', 3.0))
    api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?sports=85&count=50&lng=fr&gr=70&mode=4&country=96&getEmpty=true"
    response = requests.get(api_url)
    data = response.json()
    predictions = []
    for match in data.get("Value", []):
        match_info = {
            "match": f"{match.get('O1', '–')} vs {match.get('O2', '–')}",
            "prédictions": []
        }
        for ae in match.get("AE", []):
            type_pari = ae.get("G")
            if type_pari == 1:
                continue  # Ignore les 1X2
            for me in ae.get("ME", []):
                cote = me.get("C")
                if cote and min_cote <= cote <= max_cote:
                    prediction = {
                        "type": type_pari,
                        "parametre": me.get("P"),
                        "résultat": me.get("T"),
                        "cote": cote,
                        "proba": round(1 / cote, 3),
                        "traduction": traduire_option_pari(type_pari, me.get("T"), me.get("P"))
                    }
                    match_info["prédictions"].append(prediction)
        if match_info["prédictions"]:
            predictions.append(match_info)
    html = "<h2>Paris alternatifs filtrés (hors 1X2)</h2>"
    for r in predictions:
        html += f"<h4>📌 Match : {r['match']}</h4><ul>"
        for pari in r['prédictions']:
            html += f"<li>🔹 {pari['traduction']} | Cote: {pari['cote']} | Proba: {pari['proba']}</li>"
        html += "</ul>"
    if not predictions:
        html += "<p>Aucun pari alternatif dans la fourchette demandée.</p>"
    return html

@app.route('/paris-alternatifs-proba-ajax')
def paris_alternatifs_proba_ajax():
    min_cote = float(request.args.get('min_cote', 1.399))
    max_cote = float(request.args.get('max_cote', 3.0))
    seuil_proba = float(request.args.get('seuil_proba', 0.33))
    api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?sports=85&count=50&lng=fr&gr=70&mode=4&country=96&getEmpty=true"
    response = requests.get(api_url)
    donnees = response.json()
    predictions = []
    for match in donnees.get("Value", []):
        equipe1 = match.get("O1", "Équipe 1")
        equipe2 = match.get("O2", "Équipe 2")
        label = f"{equipe1} vs {equipe2}"
        suggestions = []
        for ae in match.get("AE", []):
            type_pari = ae.get("G")
            if type_pari == 1:
                continue  # Ignore 1X2
            for option in ae.get("ME", []):
                cote = option.get("C")
                if cote and min_cote <= cote <= max_cote:
                    proba = round(1 / cote, 3)
                    if proba >= seuil_proba:
                        suggestions.append({
                            "type_pari": type_pari,
                            "paramètre": option.get("P"),
                            "résultat": option.get("T"),
                            "cote": cote,
                            "proba_estimée": proba,
                            "traduction": traduire_option_pari(type_pari, option.get("T"), option.get("P"))
                        })
        if suggestions:
            predictions.append({
                "match": label,
                "prédictions_ae": suggestions
            })
    html = "<h2>Paris alternatifs filtrés (hors 1X2, proba ≥ seuil)</h2>"
    for match in predictions:
        html += f"<h4>🎯 {match['match']}</h4><ul>"
        for pari in match["prédictions_ae"]:
            html += (f"<li>🔹 {pari['traduction']} | Cote: {pari['cote']} | Proba: {pari['proba_estimée']}</li>")
        html += "</ul>"
    if not predictions:
        html += "<p>Aucun pari alternatif dans la fourchette demandée et le seuil de proba.</p>"
    return html

# Nouveau template pour juste le tableau (pour AJAX)
TABLEAU_TEMPLATE = """
<table>
    <tr>
        <th>Équipe 1</th><th>Score 1</th><th>Score 2</th><th>Équipe 2</th>
        <th>Sport</th><th>Ligue</th><th>Statut</th><th>Date & Heure</th>
        <th>Température</th><th>Humidité</th><th>Cotes</th><th>Heure fin estimée</th><th>Détails</th>
    </tr>
    {% for m in data %}
    <tr>
        <td>{{m.team1}}</td><td>{{m.score1}}</td><td>{{m.score2}}</td><td>{{m.team2}}</td>
        <td>{{m.sport}}</td><td>{{m.league}}</td><td>
            {% if m.status.startswith('En cours') %}
                <span style="background:#27ae60;color:white;padding:3px 10px;border-radius:8px;font-weight:bold;">{{m.status}}</span>
            {% elif m.status == 'Terminé' %}
                <span style="background:#c0392b;color:white;padding:3px 10px;border-radius:8px;font-weight:bold;">{{m.status}}</span>
            {% else %}
                <span style="background:#f39c12;color:white;padding:3px 10px;border-radius:8px;font-weight:bold;">{{m.status}}</span>
            {% endif %}
            <br><small style="color:#888">{{m.status_officiel}}</small>
        </td><td>{{m.datetime}}</td>
        <td>{{m.temp}}°C</td><td>{{m.humid}}%</td><td>{{m.odds|join(" | ")}}</td><td>{{m.heure_fin}}</td>
        <td>{% if m.id %}<a href="/match/{{m.id}}"><button>Détails</button></a>{% else %}–{% endif %}</td>
    </tr>
    {% endfor %}
</table>
"""

@app.route('/tableau-matches')
def tableau_matches():
    try:
        selected_sport = request.args.get("sport", "").strip()
        selected_league = request.args.get("league", "").strip()
        selected_status = request.args.get("status", "").strip()
        page = int(request.args.get('page', 1))
        # Copie de la logique de la route home() pour filtrer et paginer les données
        api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?sports=85&count=50&lng=fr&gr=70&mode=4&country=96&getEmpty=true"
        response = requests.get(api_url)
        matches = response.json().get("Value", [])
        data = []
        sports_detected = set()
        leagues_detected = set()
        for match in matches:
            try:
                required_keys = {
                    "O1": "–",
                    "O2": "–",
                    "LE": "–",
                    "AE": [],
                    "MIS": [],
                    "I": None,
                    "T": None,
                    "TN": "",
                    "TNS": "",
                    "SE": "",
                    "SN": ""
                }
                for key, default in required_keys.items():
                    if key not in match:
                        match[key] = default
                league = match.get("LE", "–")
                team1 = match.get("O1", "–")
                team2 = match.get("O2", "–")
                sport = detect_sport(league).strip()
                sports_detected.add(sport)
                leagues_detected.add(league)
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
                minute = None
                sc = match.get("SC", {})
                if "TS" in sc and isinstance(sc["TS"], int):
                    minute = sc["TS"] // 60
                elif "ST" in sc and isinstance(sc["ST"], int):
                    minute = sc["ST"]
                elif "T" in match and isinstance(match["T"], int):
                    minute = match["T"] // 60
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
                meteo_data = match.get("MIS", [])
                temp = next((item["V"] for item in meteo_data if item.get("K") == 9), "–")
                humid = next((item["V"] for item in meteo_data if item.get("K") == 27), "–")
                statut_officiel = match.get('TN') or match.get('TNS')
                # --- Heure de fin estimée ---
                heure_fin = "–"
                if match_ts and statut.startswith("En cours"):
                    if sport == "Football":
                        fin_ts = match_ts + 2*3600  # 2h
                    elif sport == "Basketball":
                        fin_ts = match_ts + 90*60  # 1h30
                    else:
                        fin_ts = match_ts + 2*3600
                    heure_fin = datetime.datetime.utcfromtimestamp(fin_ts).strftime('%d/%m/%Y %H:%M')
                data.append({
                    "team1": team1,
                    "team2": team2,
                    "score1": score1,
                    "score2": score2,
                    "league": league,
                    "sport": sport,
                    "status": statut,
                    "status_officiel": statut_officiel,
                    "datetime": match_time,
                    "temp": temp,
                    "humid": humid,
                    "odds": formatted_odds,
                    "heure_fin": heure_fin,
                    "id": match.get("I", None)
                })
            except Exception as e:
                continue
        per_page = 20
        total = len(data)
        page = max(1, page)
        data_paginated = data[(page-1)*per_page:page*per_page]
        return render_template_string(TABLEAU_TEMPLATE, data=data_paginated)

# --- Adapter le TEMPLATE principal pour AJAX ---
TEMPLATE = TEMPLATE.replace(
    '<table>', '<div id="tableau-matches">\n<table>', 1
).replace(
    '</table>', '</table>\n</div>', 1
)
# Ajouter le script AJAX juste avant </body>
TEMPLATE = TEMPLATE.replace(
    '</body>',
    '''<script>
    setInterval(function() {
        // On garde les filtres et la page courante
        let params = new URLSearchParams(window.location.search);
        fetch('/tableau-matches?' + params.toString())
          .then(response => response.text())
          .then(html => {
            document.getElementById('tableau-matches').innerHTML = html;
          });
    }, 5000);
    </script>\n</body>''
)

@app.route('/details-match-ajax/<int:match_id>')
def details_match_ajax(match_id):
    try:
        api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?sports=85&count=50&lng=fr&gr=70&mode=4&country=96&getEmpty=true"
        response = requests.get(api_url)
        matches = response.json().get("Value", [])
        match = next((m for m in matches if m.get("I") == match_id), None)
        if not match:
            return f"Aucun match trouvé pour l'identifiant {match_id}"
        team1 = match.get("O1", "–")
        team2 = match.get("O2", "–")
        league = match.get("LE", "–")
        sport = detect_sport(league)
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
        stats = []
        st = match.get("SC", {}).get("ST", [])
        if st and isinstance(st, list) and len(st) > 0 and "Value" in st[0]:
            for stat in st[0]["Value"]:
                nom = stat.get("N", "?")
                s1 = stat.get("S1", "0")
                s2 = stat.get("S2", "0")
                stats.append({"nom": nom, "s1": s1, "s2": s2})
        explication = "La prédiction est basée sur les cotes et les statistiques principales (tirs, possession, etc.)."
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
        def render_all_options(match):
            html = '<h3>Toutes les options de paris</h3>'
            if match.get('E'):
                html += '<b>1X2 :</b><ul>'
                for o in match['E']:
                    t = o.get('T')
                    label = {1: 'Victoire ' + team1, 2: 'Match nul', 3: 'Victoire ' + team2}.get(t, f'Option {t}')
                    html += f'<li>{label} : {o.get("C", "–")}</li>'
                html += '</ul>'
            if match.get('AE'):
                for ae in match['AE']:
                    g = ae.get('G')
                    html += f'<ul>'
                    for me in ae.get('ME', []):
                        p = me.get('P', '')
                        t = me.get('T', '')
                        c = me.get('C', '–')
                        traduction = traduire_option_pari(g, t, p)
                        html += f'<li>{traduction} : {c}</li>'
                    html += '</ul>'
            return html
        def render_predictor(match):
            min_cote = 1.399
            max_cote = 3.0
            predictions = []
            for ae in match.get('AE', []):
                g = ae.get('G')
                if g not in [2, 17]:
                    continue
                for me in ae.get('ME', []):
                    c = me.get('C')
                    t = me.get('T')
                    p = me.get('P')
                    if c and min_cote <= c <= max_cote:
                        traduction = traduire_option_pari(g, t, p)
                        proba = round(1/float(c), 3) if c else '?' 
                        predictions.append({
                            'traduction': traduction,
                            'cote': c,
                            'proba': proba
                        })
            html = '<h3>Prédicteur alternatives (Handicap & Over/Under, cotes 1.399 à 3)</h3>'
            if predictions:
                best = max(predictions, key=lambda x: x['proba'])
                html += f'<div style="background:#27ae60;color:white;padding:8px 15px;border-radius:8px;font-weight:bold;margin-bottom:10px;">Meilleure prédiction : {best["traduction"]} | Cote: {best["cote"]} | Proba: {best["proba"]}</div>'
                html += '<ul>'
                for pred in predictions:
                    html += f'<li>{pred["traduction"]} | Cote: {pred["cote"]} | Proba: {pred["proba"]}</li>'
                html += '</ul>'
            else:
                html += '<p>Aucune prédiction alternative disponible dans la fourchette demandée.</p>'
            return html
        statut_officiel = match.get('TN') or match.get('TNS')
        return f'''
            <p><b>Score :</b> {score1} - {score2}</p>
            <p><b>Statut officiel :</b> {statut_officiel or '–'}</p>
            <p><b>Prédiction du bot :</b> {prediction}</p>
            <p><b>Explication :</b> {explication}</p>
            <h3>Statistiques principales</h3>
            <table class="stats-table">
                <tr><th>Statistique</th><th>{team1}</th><th>{team2}</th></tr>
                {''.join(f'<tr><td>{s["nom"]}</td><td>{s["s1"]}</td><td>{s["s2"]}</td></tr>' for s in stats)}
            </table>
            <canvas id="statsChart" height="200"></canvas>
            {render_all_options(match)}
            {render_predictor(match)}
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
        '''

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
