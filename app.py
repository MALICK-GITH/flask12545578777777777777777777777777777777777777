from flask import Flask, request, render_template_string, send_file, redirect, url_for
import requests
import os
import datetime
from operator import itemgetter
import io
import csv
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import joblib

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///matchs.db'
db = SQLAlchemy(app)

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    id_match = db.Column(db.String, unique=True)
    equipe1 = db.Column(db.String)
    score1 = db.Column(db.String)
    score2 = db.Column(db.String)
    equipe2 = db.Column(db.String)
    sport = db.Column(db.String)
    ligue = db.Column(db.String)
    date_heure = db.Column(db.String)
    statut = db.Column(db.String)
    prediction = db.Column(db.String)  # Prédiction principale
    halftime_prediction = db.Column(db.String)  # Prédiction mi-temps

# Migration automatique du CSV vers la base SQL (à faire une seule fois)
def migrate_csv_to_sql():
    import csv
    import os
    csv_file = 'historique_matchs.csv'
    if os.path.exists(csv_file):
        with open(csv_file, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not Match.query.filter_by(id_match=row['id_match']).first():
                    m = Match(
                        id_match=row['id_match'],
                        equipe1=row['equipe1'],
                        score1=row['score1'],
                        score2=row['score2'],
                        equipe2=row['equipe2'],
                        sport=row['sport'],
                        ligue=row['ligue'],
                        date_heure=row['date_heure'],
                        statut=row['statut']
                    )
                    db.session.add(m)
            db.session.commit()
        print('Migration CSV -> SQL terminée.')

# Appel automatique de la migration au démarrage (ne fait rien si déjà migré)
with app.app_context():
    db.create_all()
    migrate_csv_to_sql()

# Dans la fonction de sauvegarde automatique (remplace l'écriture CSV par SQL)
def save_matches_sql(matches):
    for m in matches:
        if not Match.query.filter_by(id_match=m['id_match']).first():
            match = Match(**m)
            db.session.add(match)
    db.session.commit()

# Fonction pour entraîner le modèle ML à partir de la base SQL
def train_ml_model():
    matchs = Match.query.all()
    if not matchs:
        return None
    data = []
    for m in matchs:
        try:
            s1 = int(m.score1)
            s2 = int(m.score2)
        except:
            s1, s2 = 0, 0
        data.append({
            'equipe1': m.equipe1,
            'equipe2': m.equipe2,
            'score1': s1,
            'score2': s2,
            'resultat': 1 if s1 > s2 else (2 if s1 < s2 else 0)
        })
    df = pd.DataFrame(data)
    if df.empty:
        return None
    df['equipe1_id'] = df['equipe1'].astype('category').cat.codes
    df['equipe2_id'] = df['equipe2'].astype('category').cat.codes
    X = df[['equipe1_id', 'equipe2_id', 'score1', 'score2']]
    y = df['resultat']
    clf = RandomForestClassifier()
    clf.fit(X, y)
    joblib.dump((clf, df['equipe1'].astype('category').cat.categories, df['equipe2'].astype('category').cat.categories), 'ml_model.joblib')
    return clf

# Fonction pour prédire avec le modèle ML
def predict_ml(equipe1, equipe2, score1=0, score2=0):
    if not os.path.exists('ml_model.joblib'):
        return "Pas de modèle ML"
    clf, cat1, cat2 = joblib.load('ml_model.joblib')
    try:
        equipe1_id = list(cat1).index(equipe1)
        equipe2_id = list(cat2).index(equipe2)
    except ValueError:
        return "Pas assez d'historique pour ces équipes"
    X = [[equipe1_id, equipe2_id, score1, score2]]
    pred = clf.predict(X)[0]
    if pred == 1:
        return f"Victoire {equipe1} (ML)"
    elif pred == 2:
        return f"Victoire {equipe2} (ML)"
    else:
        return "Match nul (ML)"

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
                    # Enregistrement automatique dans la base SQL si non déjà présent
                    id_match = str(match.get("I"))
                    if id_match and not Match.query.filter_by(id_match=id_match).first():
                        nouveau = Match(
                            id_match=id_match,
                            equipe1=team1,
                            score1=str(score1),
                            score2=str(score2),
                            equipe2=team2,
                            sport=sport,
                            ligue=league,
                            date_heure=match_time,
                            statut=statut
                        )
                        db.session.add(nouveau)
                        db.session.commit()
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

                # --- Prédiction avancée ---
                prediction, all_probs = get_best_prediction(odds_data, team1, team2)
                # --- Cotes mi-temps ---
                halftime_odds_data = []
                for o in match.get("E", []):
                    if o.get("G") == 8 and o.get("T") in [1, 2, 3] and o.get("C") is not None:
                        halftime_odds_data.append({
                            "type": {1: "1", 2: "2", 3: "X"}.get(o.get("T")),
                            "cote": o.get("C")
                        })
                if not halftime_odds_data:
                    for ae in match.get("AE", []):
                        if ae.get("G") == 8:
                            for o in ae.get("ME", []):
                                if o.get("T") in [1, 2, 3] and o.get("C") is not None:
                                    halftime_odds_data.append({
                                        "type": {1: "1", 2: "2", 3: "X"}.get(o.get("T")),
                                        "cote": o.get("C")
                                    })
                if not halftime_odds_data:
                    formatted_halftime_odds = ["Pas de cotes mi-temps"]
                else:
                    formatted_halftime_odds = [f"{od['type']}: {od['cote']}" for od in halftime_odds_data]
                halftime_prediction, halftime_probs = get_best_prediction(halftime_odds_data, team1, team2)
                # --- Météo ---
                meteo_data = match.get("MIS", [])
                temp = next((item["V"] for item in meteo_data if item.get("K") == 9), "–")
                humid = next((item["V"] for item in meteo_data if item.get("K") == 27), "–")

                bet_options = extract_bet_options(match)

                # Recherche du match en base
                id_match = str(match.get("I"))
                match_db = Match.query.filter_by(id_match=id_match).first() if id_match else None
                # Prédiction principale
                if match_db and match_db.prediction:
                    prediction = match_db.prediction
                else:
                    prediction, all_probs = get_best_prediction(odds_data, team1, team2)
                    if match_db:
                        match_db.prediction = prediction
                        db.session.commit()
                # Prédiction mi-temps
                if match_db and match_db.halftime_prediction:
                    halftime_prediction = match_db.halftime_prediction
                else:
                    halftime_prediction, halftime_probs = get_best_prediction(halftime_odds_data, team1, team2)
                    if match_db:
                        match_db.halftime_prediction = halftime_prediction
                        db.session.commit()

                # Prédiction ML
                prediction_ml = predict_ml(team1, team2, score1, score2)

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
                    "all_probs": all_probs,
                    "halftime_odds": formatted_halftime_odds,
                    "halftime_prediction": halftime_prediction,
                    "halftime_probs": halftime_probs,
                    "id": match.get("I", None),
                    "bet_options": bet_options,
                    "prediction_ml": prediction_ml
                })
            except Exception as e:
                print(f"Erreur lors du traitement d'un match: {e}")
                continue

        # --- Tri des matchs ---
        sort_by = request.args.get('sort', 'datetime')
        if sort_by == 'prob':
            data.sort(key=lambda m: float(m['all_probs'][0]['prob'][:-1]) if m['all_probs'] else 0, reverse=True)
        elif sort_by == 'cote':
            data.sort(key=lambda m: float(m['odds'][0].split(': ')[1]) if m['odds'] and m['odds'][0] != 'Pas de cotes disponibles' else 9999)
        else:
            data.sort(key=lambda m: m['datetime'])
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
        api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?sports=85&count=50&lng=fr&gr=70&mode=4&country=96&getEmpty=true"
        response = requests.get(api_url)
        matches = response.json().get("Value", [])
        match = next((m for m in matches if m.get("I") == match_id), None)
        if not match:
            return render_template_string('<div style="padding:40px;text-align:center;color:#c0392b;font-size:22px;">Aucun match trouvé pour cet identifiant.</div>')
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
        # Timeline score (si PS existe)
        timeline = []
        ps = match.get("SC", {}).get("PS", [])
        if ps:
            for period in ps:
                label = period.get("Key", "?")
                val = period.get("Value", {})
                s1 = val.get("S1", 0)
                s2 = val.get("S2", 0)
                nf = val.get("NF", "?")
                timeline.append({"label": nf, "s1": s1, "s2": s2})
        # Historique équipes (3 derniers matchs)
        team1_hist = []
        team2_hist = []
        for m in matches:
            if m.get("O1") == team1 or m.get("O2") == team1:
                if m.get("I") != match_id:
                    s1 = m.get("SC", {}).get("FS", {}).get("S1", "–")
                    s2 = m.get("SC", {}).get("FS", {}).get("S2", "–")
                    team1_hist.append(f"{m.get('O1','?')} {s1} - {s2} {m.get('O2','?')}")
            if m.get("O1") == team2 or m.get("O2") == team2:
                if m.get("I") != match_id:
                    s1 = m.get("SC", {}).get("FS", {}).get("S1", "–")
                    s2 = m.get("SC", {}).get("FS", {}).get("S2", "–")
                    team2_hist.append(f"{m.get('O1','?')} {s1} - {s2} {m.get('O2','?')}")
        team1_hist = team1_hist[:3]
        team2_hist = team2_hist[:3]
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
        prediction, all_probs = get_best_prediction(odds_data, team1, team2)
        # --- Cotes mi-temps ---
        halftime_odds_data = []
        for o in match.get("E", []):
            if o.get("G") == 8 and o.get("T") in [1, 2, 3] and o.get("C") is not None:
                halftime_odds_data.append({
                    "type": {1: "1", 2: "2", 3: "X"}.get(o.get("T")),
                    "cote": o.get("C")
                })
        if not halftime_odds_data:
            for ae in match.get("AE", []):
                if ae.get("G") == 8:
                    for o in ae.get("ME", []):
                        if o.get("T") in [1, 2, 3] and o.get("C") is not None:
                            halftime_odds_data.append({
                                "type": {1: "1", 2: "2", 3: "X"}.get(o.get("T")),
                                "cote": o.get("C")
                            })
        halftime_prediction, halftime_probs = get_best_prediction(halftime_odds_data, team1, team2)
        # --- Lecture de l'historique pour la forme récente ---
        def get_forme(equipe):
            vic, nul, defaite = 0, 0, 0
            total = 0
            derniers = []
            try:
                with open('historique_matchs.csv', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row['equipe1'] == equipe or row['equipe2'] == equipe:
                            s1 = row['score1']
                            s2 = row['score2']
                            try:
                                s1 = int(s1)
                                s2 = int(s2)
                            except:
                                continue
                            if row['equipe1'] == equipe:
                                if s1 > s2:
                                    vic += 1
                                    derniers.append('V')
                                elif s1 == s2:
                                    nul += 1
                                    derniers.append('N')
                                else:
                                    defaite += 1
                                    derniers.append('D')
                            else:
                                if s2 > s1:
                                    vic += 1
                                    derniers.append('V')
                                elif s2 == s1:
                                    nul += 1
                                    derniers.append('N')
                                else:
                                    defaite += 1
                                    derniers.append('D')
                            total += 1
                            if len(derniers) >= 5:
                                break
            except:
                pass
            return {
                'vic': vic, 'nul': nul, 'defaite': defaite, 'total': total,
                'derniers': derniers[:5],
                'pct_vic': f"{(vic/total*100):.0f}%" if total else "–",
                'pct_nul': f"{(nul/total*100):.0f}%" if total else "–",
                'pct_defaite': f"{(defaite/total*100):.0f}%" if total else "–"
            }
        forme1 = get_forme(team1)
        forme2 = get_forme(team2)
        # HTML avec graphiques Chart.js CDN + timeline + historique + partage + forme récente
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
                .probs {{ font-size: 13px; color: #555; margin-top: 2px; }}
                .timeline-chart {{ margin-top: 30px; }}
                .history-block {{ margin-top: 20px; background: #f9f9f9; border-radius: 8px; padding: 10px; }}
                .share-btn {{ background: #2980b9; color: #fff; border: none; border-radius: 4px; padding: 6px 12px; cursor: pointer; margin-top: 10px; }}
                .forme-block {{ margin-top: 20px; background: #eafaf1; border-radius: 8px; padding: 10px; }}
            </style>
        </head><body>
            <div class="container">
                <a href="/" class="back-btn">&larr; Retour à la liste</a>
                <h2>{team1} vs {team2}</h2>
                <p><b>Ligue :</b> {league} | <b>Sport :</b> {sport}</p>
                <p><b>Score :</b> {score1} - {score2}</p>
                <p><b>Prédiction du bot :</b> {prediction}<span class='probs'> | {' | '.join([f"{p[0]}: {p[1]*100:.1f}% (cote {p[2]})" for p in [(p['type'], float(p['prob'][:-1])/100, p['cote']) for p in all_probs]])}</span></p>
                <p><b>Prédiction mi-temps :</b> {halftime_prediction}<span class='probs'> | {' | '.join([f"{p[0]}: {p[1]*100:.1f}% (cote {p[2]})" for p in [(p['type'], float(p['prob'][:-1])/100, p['cote']) for p in halftime_probs]])}</span></p>
                <p><b>Cotes mi-temps :</b> {' | '.join([f"{od['type']}: {od['cote']}" for od in halftime_odds_data]) if halftime_odds_data else 'Pas de cotes mi-temps'}</p>
                <p><b>Explication :</b> {explication}</p>
                <div class="forme-block">
                    <b>Forme récente {team1} :</b> {' '.join(forme1['derniers']) if forme1['derniers'] else '–'}
                    <span style="color:#27ae60;">{forme1['pct_vic']} V</span> /
                    <span style="color:#f39c12;">{forme1['pct_nul']} N</span> /
                    <span style="color:#c0392b;">{forme1['pct_defaite']} D</span><br>
                    <b>Forme récente {team2} :</b> {' '.join(forme2['derniers']) if forme2['derniers'] else '–'}
                    <span style="color:#27ae60;">{forme2['pct_vic']} V</span> /
                    <span style="color:#f39c12;">{forme2['pct_nul']} N</span> /
                    <span style="color:#c0392b;">{forme2['pct_defaite']} D</span>
                </div>
                <h3>Statistiques principales</h3>
                <table class="stats-table">
                    <tr><th>Statistique</th><th>{team1}</th><th>{team2}</th></tr>
                    {''.join(f'<tr><td>{s["nom"]}</td><td>{s["s1"]}</td><td>{s["s2"]}</td></tr>' for s in stats)}
                </table>
                <canvas id="statsChart" height="200"></canvas>
                <div class="timeline-chart">
                    <h3>Évolution du score</h3>
                    <canvas id="timelineChart" height="120"></canvas>
                </div>
                <div class="history-block">
                    <b>3 derniers résultats {team1} :</b><br> {'<br>'.join(team1_hist) if team1_hist else 'Aucun'}<br><br>
                    <b>3 derniers résultats {team2} :</b><br> {'<br>'.join(team2_hist) if team2_hist else 'Aucun'}
                </div>
                <button class="share-btn" onclick="navigator.clipboard.writeText(window.location.href);alert('Lien copié !');">Partager ce match</button>
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
                // Timeline score
                const timelineLabels = { [repr(t['label']) for t in timeline] };
                const timelineS1 = { [int(t['s1']) if str(t['s1']).isdigit() else 0 for t in timeline] };
                const timelineS2 = { [int(t['s2']) if str(t['s2']).isdigit() else 0 for t in timeline] };
                new Chart(document.getElementById('timelineChart'), {{
                    type: 'line',
                    data: {{
                        labels: timelineLabels,
                        datasets: [
                            {{ label: '{team1}', data: timelineS1, borderColor: 'rgba(44,62,80,0.9)', fill: false }},
                            {{ label: '{team2}', data: timelineS2, borderColor: 'rgba(39,174,96,0.9)', fill: false }}
                        ]
                    }},
                    options: {{ responsive: true, plugins: {{ legend: {{ position: 'top' }} }} }}
                }});
            </script>
        </body></html>
        '''
    except Exception as e:
        return render_template_string(f'<div style="padding:40px;text-align:center;color:#c0392b;font-size:22px;">Erreur l\'affichage des détails du match : {e}</div>')

def get_best_prediction(odds_data, team1, team2):
    if not odds_data:
        return "–", []
    probs = []
    total = sum(1/od['cote'] for od in odds_data)
    for od in odds_data:
        prob = (1/od['cote']) / total
        probs.append((od['type'], prob, od['cote']))
    best = max(probs, key=lambda x: x[1])
    pred = {
        "1": f"{team1} gagne ({best[1]*100:.1f}%)",
        "2": f"{team2} gagne ({best[1]*100:.1f}%)",
        "X": f"Match nul ({best[1]*100:.1f}%)"
    }.get(best[0], "–")
    # Format all probabilities
    all_probs = [
        {
            "type": {"1": team1, "2": team2, "X": "Nul"}.get(t, t),
            "prob": f"{p*100:.1f}%",
            "cote": c
        }
        for t, p, c in probs
    ]
    return pred, all_probs

@app.route('/export_csv')
def export_csv():
    try:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Equipe 1", "Score 1", "Score 2", "Equipe 2", "Sport", "Ligue", "Statut", "Date & Heure"])
        for m in Match.query.order_by(Match.date_heure.desc()).all():
            writer.writerow([
                m.equipe1, m.score1, m.score2, m.equipe2, m.sport, m.ligue, m.statut, m.date_heure
            ])
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='matchs.csv')
    except Exception as e:
        return f"Erreur lors de l'export CSV : {e}"

@app.route('/historique')
def historique():
    rows = Match.query.order_by(Match.date_heure.desc()).all()
    return render_template_string('''
    <!DOCTYPE html>
    <html><head>
        <meta charset="utf-8">
        <title>Historique des matchs terminés</title>
        <style>
            body { font-family: Arial; background: #f4f4f4; padding: 20px; }
            .container { max-width: 900px; margin: auto; background: white; border-radius: 10px; box-shadow: 0 2px 8px #ccc; padding: 20px; }
            h2 { text-align: center; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { border: 1px solid #ccc; padding: 8px; text-align: center; }
            th { background: #27ae60; color: #fff; }
            tr:nth-child(even) { background: #f9f9f9; }
            .back-btn { margin-bottom: 20px; display: inline-block; }
        </style>
    </head><body>
        <div class="container">
            <a href="/" class="back-btn">&larr; Retour à la liste</a>
            <h2>Historique des matchs terminés</h2>
            <table>
                <tr>
                    <th>Date & Heure</th><th>Équipe 1</th><th>Score</th><th>Équipe 2</th><th>Sport</th><th>Ligue</th><th>Statut</th>
                </tr>
                {% for r in rows %}
                <tr>
                    <td>{{r.date_heure}}</td>
                    <td>{{r.equipe1}}</td>
                    <td>{{r.score1}} - {{r.score2}}</td>
                    <td>{{r.equipe2}}</td>
                    <td>{{r.sport}}</td>
                    <td>{{r.ligue}}</td>
                    <td>{{r.statut}}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </body></html>
    ''', rows=rows)

def extract_bet_options(match):
    """Retourne une liste structurée de toutes les options de paris disponibles pour un match."""
    options = []
    # E = options principales
    for o in match.get('E', []):
        label = f"Groupe {o.get('G')} - Type {o.get('T')}"
        if o.get('P') is not None:
            label += f" (param: {o.get('P')})"
        options.append({
            'label': label,
            'cote': o.get('C'),
            'groupe': o.get('G'),
            'type': o.get('T'),
            'param': o.get('P')
        })
    # AE = options avancées
    for ae in match.get('AE', []):
        g = ae.get('G')
        for o in ae.get('ME', []):
            label = f"Groupe {g} - Type {o.get('T')}"
            if o.get('P') is not None:
                label += f" (param: {o.get('P')})"
            options.append({
                'label': label,
                'cote': o.get('C'),
                'groupe': g,
                'type': o.get('T'),
                'param': o.get('P')
            })
    return options

def bet_option_label(opt, team1, team2):
    g, t, p = opt.get('groupe'), opt.get('type'), opt.get('param')
    # 1N2
    if g == 1:
        if t == 1:
            return f"Victoire {team1}"
        elif t == 2:
            return f"Victoire {team2}"
        elif t == 3:
            return "Match nul"
    # Mi-temps
    if g == 8:
        if t == 4:
            return f"Mi-temps : {team1}"
        elif t == 5:
            return "Mi-temps : Nul"
        elif t == 6:
            return f"Mi-temps : {team2}"
    # Handicap
    if g == 2:
        if t == 7:
            return f"Handicap {team1} {p:+}"
        elif t == 8:
            return f"Handicap {team2} {p:+}"
    # Over/Under
    if g == 17:
        if t == 9:
            return f"Plus de {p} buts"
        elif t == 10:
            return f"Moins de {p} buts"
    # Autres (fallback)
    return opt.get('label')

TEMPLATE = """<!DOCTYPE html>
<html><head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Matchs en direct</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600&family=Montserrat:wght@400;700&display=swap" rel="stylesheet">
    <style>
    body {
      font-family: 'Montserrat', Arial, sans-serif;
      margin:0; padding:0;
      min-height:100vh;
      background: linear-gradient(135deg, #1e003a 0%, #2d0b5a 50%, #ffb300 100%);
      color:#f3f3f3;
      transition: background 0.7s;
    }
    body.dark {
      background: linear-gradient(135deg, #0a0a23 0%, #1e003a 60%, #ffb300 100%);
      color:#e0e0e0;
    }
    .container {
      max-width: 1200px;
      margin: auto;
      padding: 10px;
    }
    .match-card {
      background: rgba(255,255,255,0.10);
      box-shadow: 0 8px 32px 0 rgba(31,38,135,0.37);
      backdrop-filter: blur(8px);
      border-radius: 18px;
      border: 1px solid rgba(255,255,255,0.18);
      margin-bottom: 18px;
      padding: 18px 10px;
      transition: transform 0.2s, box-shadow 0.2s;
      animation: fadeIn 0.7s;
    }
    .match-card:hover {
      transform: scale(1.025);
      box-shadow: 0 12px 40px 0 #ffb30055;
    }
    @keyframes fadeIn {
      from { opacity:0; transform:translateY(30px); }
      to { opacity:1; transform:translateY(0); }
    }
    table { width: 100%; border-collapse: collapse; font-size: 15px; background: none; }
    th, td { padding: 7px 4px; text-align: center; background: none; }
    th { background: rgba(30,0,58,0.8); color: #ffb300; font-family: 'Orbitron', Arial, sans-serif; font-size: 17px; letter-spacing: 1px; }
    tr { background: none; }
    tr:nth-child(even) { background: none; }
    tr:hover { background: none; }
    .team-logo { height: 22px; vertical-align: middle; margin-right: 4px; filter: drop-shadow(0 0 2px #ffb30088); }
    .status-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:3px; }
    .status-live { background:#1ec700; box-shadow:0 0 8px #1ec70088; }
    .status-finished { background:#e74c3c; box-shadow:0 0 8px #e74c3c88; }
    .status-upcoming { background:#aaa; }
    .neon-btn {
      background: #ffb300;
      color: #1e003a;
      border: none;
      border-radius: 8px;
      padding: 8px 18px;
      font-family: 'Orbitron', Arial, sans-serif;
      font-size: 15px;
      box-shadow: 0 0 12px #ffb30088, 0 0 2px #fff;
      cursor: pointer;
      transition: background 0.2s, color 0.2s, box-shadow 0.2s;
    }
    .neon-btn:hover {
      background: #fff;
      color: #ffb300;
      box-shadow: 0 0 24px #ffb300cc, 0 0 8px #fff;
    }
    @media (max-width: 700px) {
      .container { padding: 2px; }
      .match-card { padding: 8px 2px; }
      table, th, td { font-size: 12px; }
      th, td { padding: 4px 1px; }
      .team-logo { height: 16px; }
    }
    footer { margin-top:40px;text-align:center;font-size:15px;color:#ffb300; text-shadow:0 0 2px #fff; }
    ::-webkit-scrollbar { width: 8px; background: #2d0b5a; }
    ::-webkit-scrollbar-thumb { background: #ffb300; border-radius: 8px; }
    </style>
    <script>
    function toggleDark() {
      document.body.classList.toggle('dark');
      localStorage.setItem('darkmode', document.body.classList.contains('dark'));
    }
    window.onload = function() {
      if(localStorage.getItem('darkmode')==='true') document.body.classList.add('dark');
    }
    </script>
</head><body>
    <div style="text-align:right;padding:7px 10px;"><button onclick="toggleDark()" class="neon-btn">🌓 Mode sombre</button></div><div class="container">
        <h2>📊 Matchs en direct — {{ selected_sport }} / {{ selected_league }} / {{ selected_status }}</h2>
        <div style="text-align:center; color:#888; font-size:13px; margin-bottom:10px;">La prédiction est basée sur les cotes converties en probabilités implicites.</div>
        <form method="get">
            <label>Sport :
                <select name="sport" onchange="this.form.submit()">
                    <option value="">Tous</option>
                    {% for s in sports %}
                        <option value="{{s}}" {% if s == selected_sport %}selected{% endif %}>{{s}}</option>
                    {% endfor %}
                </select>
            </label>
            <label>Ligue :
                <select name="league" onchange="this.form.submit()">
                    <option value="">Toutes</option>
                    {% for l in leagues %}
                        <option value="{{l}}" {% if l == selected_league %}selected{% endif %}>{{l}}</option>
                    {% endfor %}
                </select>
            </label>
            <label>Statut :
                <select name="status" onchange="this.form.submit()">
                    <option value="">Tous</option>
                    <option value="live" {% if selected_status == "live" %}selected{% endif %}>En direct</option>
                    <option value="upcoming" {% if selected_status == "upcoming" %}selected{% endif %}>À venir</option>
                    <option value="finished" {% if selected_status == "finished" %}selected{% endif %}>Terminé</option>
                </select>
            </label>
            <label>Trier par :
                <select name="sort" onchange="this.form.submit()">
                    <option value="datetime" {% if request.args.get('sort', 'datetime') == 'datetime' %}selected{% endif %}>Heure</option>
                    <option value="prob" {% if request.args.get('sort') == 'prob' %}selected{% endif %}>Probabilité</option>
                    <option value="cote" {% if request.args.get('sort') == 'cote' %}selected{% endif %}>Cote</option>
                </select>
            </label>
        </form>
        <div class="pagination">
            <form method="get" style="display:inline;">
                <input type="hidden" name="sport" value="{{ selected_sport if selected_sport != 'Tous' else '' }}">
                <input type="hidden" name="league" value="{{ selected_league if selected_league != 'Toutes' else '' }}">
                <input type="hidden" name="status" value="{{ selected_status if selected_status != 'Tous' else '' }}">
                <input type="hidden" name="sort" value="{{ request.args.get('sort', 'datetime') }}">
                <button type="submit" name="page" value="{{ page-1 }}" {% if page <= 1 %}disabled{% endif %}>Page précédente</button>
            </form>
            <span>Page {{ page }} / {{ total_pages }}</span>
            <form method="get" style="display:inline;">
                <input type="hidden" name="sport" value="{{ selected_sport if selected_sport != 'Tous' else '' }}">
                <input type="hidden" name="league" value="{{ selected_league if selected_league != 'Toutes' else '' }}">
                <input type="hidden" name="status" value="{{ selected_status if selected_status != 'Tous' else '' }}">
                <input type="hidden" name="sort" value="{{ request.args.get('sort', 'datetime') }}">
                <button type="submit" name="page" value="{{ page+1 }}" {% if page >= total_pages %}disabled{% endif %}>Page suivante</button>
            </form>
        </div>
        <div style="text-align:right;max-width:98%;margin:auto 0 10px auto;">
            <a href="/export_csv" style="background:#27ae60;color:#fff;padding:7px 16px;border-radius:4px;text-decoration:none;font-size:15px;">Exporter CSV</a>
            <a href="/historique" style="background:#2980b9;color:#fff;padding:7px 16px;border-radius:4px;text-decoration:none;font-size:15px;margin-left:10px;">Historique</a>
        </div>
        <div class="table-wrap">
            {% for m in data %}
            <div class="match-card">
                <div class="match-header">
                    <div class="match-teams">
                        {% if m.team1 and m.id %}<img class='team-logo' src='https://1xbet.com/images/events/{{m.id}}_1.png' onerror="this.style.display='none'">{% endif %}{{ get_flag(m.team1)|safe }} {{m.team1}}
                    </div>
                    <span class='match-status {% if 'En cours' in m.status %}status-live{% elif 'Terminé' in m.status %}status-finished{% else %}status-upcoming{% endif %}'></span>{{m.status}}
                </div>
                <div class="match-info">
                    <b>Ligue :</b> {{m.league}} | <b>Sport :</b> {{m.sport}}
                </div>
                <div class="match-info">
                    <b>Score :</b> {{m.score1}} - {{m.score2}}
                </div>
                <div class="match-info">
                    <b>Date & Heure :</b> {{m.datetime}}
                </div>
                <div class="match-info">
                    <b>Température :</b> {{m.temp}}°C | <b>Humidité :</b> {{m.humid}}%
                </div>
                <div class="match-info">
                    <b>Cotes :</b> {{m.odds|join(" | ")}}
                </div>
                <div class="match-info">
                    <b>Prédiction :</b> {{m.prediction}}
                </div>
                <div class="match-info">
                    <b>Cotes mi-temps :</b> {{m.halftime_odds|join(" | ")}}
                </div>
                <div class="match-info">
                    <b>Prédiction mi-temps :</b> {{m.halftime_prediction}}
                </div>
                <div class="match-info">
                    <b>Prédiction ML :</b> {{m.prediction_ml}}
                </div>
                <div class="bet-options">
                    {% for opt in m.bet_options %}
                        <li>{{ bet_option_label(opt, m.team1, m.team2) }} : <b>{{opt.cote}}</b></li>
                    {% endfor %}
                </div>
                <div class="match-pred">
                    <b>Prédiction :</b> {{m.prediction}}
                </div>
                <div class="match-pred">
                    <b>Prédiction ML :</b> {{m.prediction_ml}}
                </div>
                <div class="match-pred">
                    <b>Probabilités :</b> {{' | '.join([f"{p.type}: {p.prob}" for p in m.all_probs])}}
                </div>
                <div class="match-pred">
                    <b>Cotes mi-temps :</b> {{' | '.join([f"{od['type']}: {od['cote']}" for od in m.halftime_odds_data]) if m.halftime_odds_data else 'Pas de cotes mi-temps'}}
                </div>
                <div class="match-pred">
                    <b>Prédiction mi-temps :</b> {{m.halftime_prediction}}
                </div>
                <div class="match-pred">
                    <b>Probabilités mi-temps :</b> {{' | '.join([f"{p.type}: {p.prob}" for p in m.halftime_probs])}}
                </div>
                <div class="match-pred">
                    <b>Probabilités :</b> {{' | '.join([f"{p.type}: {p.prob}" for p in m.all_probs])}}
                </div>
                <div class="match-pred">
                    <b>Cotes :</b> {{' | '.join([f"{od['type']}: {od['cote']}" for od in m.odds_data]) if m.odds_data else 'Pas de cotes disponibles'}}
                </div>
                <div class="match-pred">
                    <b>Prédiction :</b> {{m.prediction}}
                </div>
                <div class="match-pred">
                    <b>Cotes mi-temps :</b> {{' | '.join([f"{od['type']}: {od['cote']}" for od in m.halftime_odds_data]) if m.halftime_odds_data else 'Pas de cotes mi-temps'}}
                </div>
                <div class="match-pred">
                    <b>Prédiction mi-temps :</b> {{m.halftime_prediction}}
                </div>
                <div class="match-pred">
                    <b>Probabilités mi-temps :</b> {{' | '.join([f"{p.type}: {p.prob}" for p in m.halftime_probs])}}
                </div>
                <div class="match-pred">
                    <b>Probabilités :</b> {{' | '.join([f"{p.type}: {p.prob}" for p in m.all_probs])}}
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>
      setInterval(function() {
        window.location.reload();
      }, 30000); // 30 secondes
    </script>
</body></html>"""

def import_matches_from_csv(csv_path):
    import csv
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not Match.query.filter_by(id_match=row['id_match']).first():
                m = Match(
                    id_match=row['id_match'],
                    equipe1=row['equipe1'],
                    score1=row['score1'],
                    score2=row['score2'],
                    equipe2=row['equipe2'],
                    sport=row.get('sport', ''),
                    ligue=row.get('ligue', ''),
                    date_heure=row.get('date_heure', ''),
                    statut=row.get('statut', ''),
                    prediction=row.get('prediction', None),
                    halftime_prediction=row.get('halftime_prediction', None)
                )
                db.session.add(m)
        db.session.commit()
    print('Import terminé.')

def import_matches_from_excel(xlsx_path):
    import pandas as pd
    df = pd.read_excel(xlsx_path)
    for _, row in df.iterrows():
        id_match = str(row.get('id_match', ''))
        if not id_match or Match.query.filter_by(id_match=id_match).first():
            continue
        m = Match(
            id_match=id_match,
            equipe1=row.get('equipe1', ''),
            score1=str(row.get('score1', '')),
            score2=str(row.get('score2', '')),
            equipe2=row.get('equipe2', ''),
            sport=row.get('sport', ''),
            ligue=row.get('ligue', ''),
            date_heure=row.get('date_heure', ''),
            statut=row.get('statut', ''),
            prediction=row.get('prediction', None),
            halftime_prediction=row.get('halftime_prediction', None)
        )
        db.session.add(m)
    db.session.commit()
    print('Import Excel terminé.')

# Appel automatique de l'import Excel au démarrage
with app.app_context():
    db.create_all()
    migrate_csv_to_sql()
    if os.path.exists('historique_matchs.csv'):
        import_matches_from_csv('historique_matchs.csv')
    if os.path.exists('historique_matchs.xlsx'):
        import_matches_from_excel('historique_matchs.xlsx')
    train_ml_model()

def get_flag(team):
    # Mapping équipe -> code pays (ISO 3166-1 alpha-2)
    flags = {
        'france': 'fr', 'espagne': 'es', 'italie': 'it', 'allemagne': 'de', 'angleterre': 'gb',
        'brazil': 'br', 'argentine': 'ar', 'portugal': 'pt', 'maroc': 'ma', 'sénégal': 'sn',
        "côte d'ivoire": 'ci', "cote d'ivoire": 'ci', 'nigeria': 'ng', 'usa': 'us', 'belgique': 'be',
        'tunisie': 'tn', 'algérie': 'dz', 'pays-bas': 'nl', 'pays bas': 'nl', 'suisse': 'ch',
        'turquie': 'tr', 'croatie': 'hr', 'pologne': 'pl', 'suède': 'se', 'norvège': 'no',
        'japon': 'jp', 'corée': 'kr', 'chine': 'cn', 'canada': 'ca', 'mexique': 'mx'
    }
    t = team.lower() if team else ''
    for k, v in flags.items():
        if k in t:
            return f'<img src="https://flagcdn.com/16x12/{v}.png" style="vertical-align:middle;margin-right:2px;">'
    return ''

@app.route('/import_historique', methods=['GET', 'POST'])
def import_historique():
    msg = ''
    if request.method == 'POST':
        f = request.files.get('file')
        if f:
            filename = f.filename.lower()
            if filename.endswith('.csv'):
                path = 'import_temp.csv'
                f.save(path)
                import_matches_from_csv(path)
                os.remove(path)
                msg = 'Import CSV réussi !'
            elif filename.endswith('.xlsx'):
                path = 'import_temp.xlsx'
                f.save(path)
                import_matches_from_excel(path)
                os.remove(path)
                msg = 'Import Excel réussi !'
            else:
                msg = 'Format non supporté.'
    return render_template_string('''<html><body style="font-family:Arial;padding:30px;">
    <h2>Importer un historique de matchs</h2>
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="file" accept=".csv,.xlsx" required>
      <button type="submit">Importer</button>
    </form>
    <p style="color:green;">{{msg}}</p>
    <a href="/">Retour à l'accueil</a>
    </body></html>''', msg=msg)

@app.route('/stats_historique')
def stats_historique():
    matchs = Match.query.all()
    total = len(matchs)
    v1 = sum(1 for m in matchs if m.score1 and m.score2 and m.score1 > m.score2)
    nul = sum(1 for m in matchs if m.score1 == m.score2 and m.score1 != '' and m.score2 != '')
    v2 = sum(1 for m in matchs if m.score1 and m.score2 and m.score1 < m.score2)
    def bar(n, total):
        l = 40
        filled = int((n/total)*l) if total else 0
        return '█'*filled + '░'*(l-filled)
    return render_template_string('''<html><body style="font-family:Arial;padding:30px;">
    <h2>Répartition des résultats dans l'historique</h2>
    <table border=1 cellpadding=6><tr><th>Résultat</th><th>Nombre</th><th>Graphique</th></tr>
    <tr><td>Victoire équipe 1</td><td>{{v1}}</td><td><pre>{{bar(v1, total)}}</pre></td></tr>
    <tr><td>Nul</td><td>{{nul}}</td><td><pre>{{bar(nul, total)}}</pre></td></tr>
    <tr><td>Victoire équipe 2</td><td>{{v2}}</td><td><pre>{{bar(v2, total)}}</pre></td></tr>
    </table>
    <p>Total de matchs : <b>{{total}}</b></p>
    <a href="/">Retour à l'accueil</a>
    </body></html>''', v1=v1, nul=nul, v2=v2, total=total, bar=bar)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
