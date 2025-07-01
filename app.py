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
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import logging

# Configuration du logger
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

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

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, unique=True, nullable=False)
    password_hash = db.Column(db.String, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    access_until = db.Column(db.DateTime, nullable=True)  # Date/heure de fin d'accès
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    def is_access_valid(self):
        from datetime import datetime
        return self.access_until is None or self.access_until > datetime.utcnow()

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
                if match_db and match_db.prediction and not ("Terminé" in statut):
                    prediction = match_db.prediction
                elif match_db and not ("Terminé" in statut):
                    prediction, all_probs = get_best_prediction(odds_data, team1, team2)
                    match_db.prediction = prediction
                    db.session.commit()
                elif match_db and ("Terminé" in statut):
                    prediction = match_db.prediction
                else:
                    prediction, all_probs = get_best_prediction(odds_data, team1, team2)
                # Prédiction mi-temps
                if match_db and match_db.halftime_prediction and not ("Terminé" in statut):
                    halftime_prediction = match_db.halftime_prediction
                elif match_db and not ("Terminé" in statut):
                    halftime_prediction, halftime_probs = get_best_prediction(halftime_odds_data, team1, team2)
                    match_db.halftime_prediction = halftime_prediction
                    db.session.commit()
                elif match_db and ("Terminé" in statut):
                    halftime_prediction = match_db.halftime_prediction
                else:
                    halftime_prediction, halftime_probs = get_best_prediction(halftime_odds_data, team1, team2)

                # Prédiction ML
                prediction_ml = predict_ml(team1, team2, score1, score2)

                # Ajout de la fonction de conseils sur les autres marchés
                conseils = predire_options(match)

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
                    "prediction_ml": prediction_ml,
                    "conseils": conseils
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
                .row-finished-animate {{
                    animation: highlight-fade 2s ease-in-out;
                    background: #d4efdf !important;
                }}
                @keyframes highlight-fade {{
                    0% {{ background: #f9e79f; }}
                    50% {{ background: #d4efdf; }}
                    100% {{ background: inherit; }}
                }}
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
                const labels = {[repr(s['nom']) for s in stats]};
                const data1 = {[float(s['s1']) if s['s1'].replace('.', '', 1).isdigit() else 0 for s in stats]};
                const data2 = {[float(s['s2']) if s['s2'].replace('.', '', 1).isdigit() else 0 for s in stats]};
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
                const timelineLabels = {[repr(t['label']) for t in timeline]};
                const timelineS1 = {[int(t['s1']) if str(t['s1']).isdigit() else 0 for t in timeline]};
                const timelineS2 = {[int(t['s2']) if str(t['s2']).isdigit() else 0 for t in timeline]};
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
                let previousStatus = {{}};
                function animateFinishedRows() {{
                    const rows = document.querySelectorAll('table tr');
                    rows.forEach(row => {{
                        const cells = row.querySelectorAll('td');
                        if (cells.length > 0) {{
                            const status = cells[6]?.innerText || '';
                            const id = cells[0]?.innerText + cells[3]?.innerText;
                            if (status.includes('Terminé')) {{
                                if (!previousStatus[id]) {{
                                    row.classList.add('row-finished-animate');
                                    setTimeout(() => row.classList.remove('row-finished-animate'), 2000);
                                }}
                                previousStatus[id] = true;
                            }} else {{
                                previousStatus[id] = false;
                            }}
                        }}
                    }});
                }}
                setInterval(animateFinishedRows, 2000);
                document.addEventListener('DOMContentLoaded', animateFinishedRows);
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

@app.route('/historique_data')
def historique_data():
    rows = Match.query.order_by(Match.date_heure.desc()).all()
    data = [
        {
            'date_heure': r.date_heure,
            'equipe1': r.equipe1,
            'score1': r.score1,
            'score2': r.score2,
            'equipe2': r.equipe2,
            'sport': r.sport,
            'ligue': r.ligue,
            'statut': r.statut
        } for r in rows
    ]
    return {'matches': data}

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
            #toast {
                visibility: hidden;
                min-width: 250px;
                margin-left: -125px;
                background-color: #27ae60;
                color: #fff;
                text-align: center;
                border-radius: 2px;
                padding: 16px;
                position: fixed;
                z-index: 1;
                left: 50%;
                bottom: 30px;
                font-size: 17px;
            }
            #toast.show {
                visibility: visible;
                -webkit-animation: fadein 0.5s, fadeout 0.5s 2.5s;
                animation: fadein 0.5s, fadeout 0.5s 2.5s;
            }
            @-webkit-keyframes fadein {
                from {bottom: 0; opacity: 0;} 
                to {bottom: 30px; opacity: 1;}
            }
            @keyframes fadein {
                from {bottom: 0; opacity: 0;}
                to {bottom: 30px; opacity: 1;}
            }
            @-webkit-keyframes fadeout {
                from {bottom: 30px; opacity: 1;} 
                to {bottom: 0; opacity: 0;}
            }
            @keyframes fadeout {
                from {bottom: 30px; opacity: 1;}
                to {bottom: 0; opacity: 0;}
            }
        </style>
    </head><body>
        <div class="container">
            <a href="/" class="back-btn">&larr; Retour à la liste</a>
            <h2>Historique des matchs terminés</h2>
            <table id="match-table">
                <thead>
                <tr>
                    <th>Date & Heure</th><th>Équipe 1</th><th>Score</th><th>Équipe 2</th><th>Sport</th><th>Ligue</th><th>Statut</th>
                </tr>
                </thead>
                <tbody id="match-tbody">
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
                </tbody>
            </table>
        </div>
        <div id="toast">Nouveau match ajouté à l'historique !</div>
        <script>
        let lastMatchId = null;
        function showToast(msg) {
            var x = document.getElementById("toast");
            x.textContent = msg;
            x.className = "show";
            setTimeout(function(){ x.className = x.className.replace("show", ""); }, 3000);
        }
        function showDesktopNotification(msg) {
            if (window.Notification && Notification.permission === "granted") {
                new Notification(msg);
            }
        }
        function askNotificationPermission() {
            if (window.Notification && Notification.permission !== "granted") {
                Notification.requestPermission();
            }
        }
        function refreshTable() {
            fetch('/historique_data').then(r => r.json()).then(data => {
                const tbody = document.getElementById('match-tbody');
                let html = '';
                let newMatch = false;
                let newFirstId = null;
                data.matches.forEach((r, idx) => {
                    if(idx === 0) newFirstId = r.date_heure + r.equipe1 + r.equipe2;
                    html += `<tr><td>${r.date_heure}</td><td>${r.equipe1}</td><td>${r.score1} - ${r.score2}</td><td>${r.equipe2}</td><td>${r.sport}</td><td>${r.ligue}</td><td>${r.statut}</td></tr>`;
                });
                if (lastMatchId && newFirstId && newFirstId !== lastMatchId) {
                    showToast("Nouveau match ajouté à l'historique !");
                    showDesktopNotification("Nouveau match ajouté à l'historique !");
                }
                lastMatchId = newFirstId;
                tbody.innerHTML = html;
            });
        }
        document.addEventListener('DOMContentLoaded', function() {
            askNotificationPermission();
            // Initialiser l'ID du dernier match
            fetch('/historique_data').then(r => r.json()).then(data => {
                if(data.matches.length > 0) {
                    lastMatchId = data.matches[0].date_heure + data.matches[0].equipe1 + data.matches[0].equipe2;
                }
            });
            setInterval(refreshTable, 20000); // 20 secondes
        });
        </script>
    </body></html>
    ''', rows=rows)

def extract_bet_options(match):
    """Retourne une liste structurée de toutes les options de paris alternatives (hors 1X2) disponibles pour un match."""
    options = []
    # E = options principales
    for o in match.get('E', []):
        if o.get('G') == 1:
            continue  # On ignore 1X2
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
        if g == 1:
            continue  # On ignore 1X2
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

def predire_options(match):
    conseils = []
    team1 = match.get('O1', 'Équipe 1')
    team2 = match.get('O2', 'Équipe 2')
    # 1. Over/Under (G=17, T=9/10)
    over_under = []
    for source in [match.get('E', []), sum([ae.get('ME', []) for ae in match.get('AE', []) if ae.get('G') == 17], [])]:
        for o in source:
            try:
                cote_f = float(o.get('C'))
            except:
                continue
            if o.get('G') == 17 and o.get('T') == 10 and 1.399 <= cote_f <= 3:
                over_under.append(("Moins", o.get('P', 0), o.get('C')))
            elif o.get('G') == 17 and o.get('T') == 9 and 1.399 <= cote_f <= 3:
                over_under.append(("Plus", o.get('P', 0), o.get('C')))
    # Trie : Moins/Plus, puis valeur croissante de P
    over_under_sorted = sorted(over_under, key=lambda x: (x[0], float(x[1]) if x[1] is not None else 0))
    for typ, p, c in over_under_sorted:
        conseils.append(f"{typ} de {p} buts (cote {c})")
    # 2. Handicap (G=2, T=7/8)
    handicaps = []
    for source in [match.get('E', []), sum([ae.get('ME', []) for ae in match.get('AE', []) if ae.get('G') == 2], [])]:
        for o in source:
            try:
                cote_f = float(o.get('C'))
            except:
                continue
            if o.get('G') == 2 and o.get('T') == 7 and 1.399 <= cote_f <= 3:
                handicaps.append((team1, o.get('P', 0), o.get('C')))
            elif o.get('G') == 2 and o.get('T') == 8 and 1.399 <= cote_f <= 3:
                handicaps.append((team2, o.get('P', 0), o.get('C')))
    # Trie par valeur absolue de P croissante
    handicaps_sorted = sorted(handicaps, key=lambda x: abs(float(x[1])) if x[1] is not None else 0)
    for equipe, p, c in handicaps_sorted:
        conseils.append(f"Handicap {equipe} ({p:+}) (cote {c})")
    # 3. Total équipe (G=62, T=13/14)
    totaux = []
    for source in [match.get('E', []), sum([ae.get('ME', []) for ae in match.get('AE', []) if ae.get('G') == 62], [])]:
        for o in source:
            try:
                cote_f = float(o.get('C'))
            except:
                continue
            if o.get('G') == 62 and o.get('T') == 13 and 1.399 <= cote_f <= 3:
                totaux.append((team1, o.get('P', 0), o.get('C')))
            elif o.get('G') == 62 and o.get('T') == 14 and 1.399 <= cote_f <= 3:
                totaux.append((team2, o.get('P', 0), o.get('C')))
    # Trie par valeur croissante de P
    totaux_sorted = sorted(totaux, key=lambda x: float(x[1]) if x[1] is not None else 0)
    for equipe, p, c in totaux_sorted:
        conseils.append(f"Total buts {equipe} : plus de {p} (cote {c})")
    return conseils

TEMPLATE = """<!DOCTYPE html>
<html><head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Matchs en direct</title>
    <style>
        body { font-family: Arial; padding: 20px; background: #f4f4f4; }
        h2 { text-align: center; }
        form { text-align: center; margin-bottom: 20px; }
        select { padding: 8px; margin: 0 10px; font-size: 14px; }
        table { border-collapse: collapse; margin: auto; width: 98%; background: white; }
        th, td { padding: 10px; border: 1px solid #ccc; text-align: center; }
        th { background: #2c3e50; color: white; }
        tr:nth-child(even) { background-color: #f9f9f9; }
        .pagination { text-align: center; margin: 20px 0; }
        .pagination button { padding: 8px 16px; margin: 0 4px; font-size: 16px; border: none; background: #2c3e50; color: white; border-radius: 4px; cursor: pointer; }
        .pagination button:disabled { background: #ccc; cursor: not-allowed; }
        .probs { font-size: 12px; color: #555; margin-top: 2px; }
        .prob-high { color: #27ae60; font-weight: bold; }
        .prob-mid { color: #f39c12; font-weight: bold; }
        .prob-low { color: #c0392b; font-weight: bold; }
        .team-logo { width: 28px; height: 28px; vertical-align: middle; border-radius: 50%; margin-right: 4px; }
        .status-dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 4px; }
        .status-live { background: #27ae60; }
        .status-finished { background: #7f8c8d; }
        .status-upcoming { background: #2980b9; }
        /* Responsive */
        @media (max-width: 800px) {
            table, thead, tbody, th, td, tr { display: block; }
            th { position: absolute; left: -9999px; top: -9999px; }
            tr { margin-bottom: 15px; background: white; border-radius: 8px; box-shadow: 0 2px 6px #ccc; }
            td { border: none; border-bottom: 1px solid #eee; position: relative; padding-left: 50%; min-height: 40px; }
            td:before { position: absolute; top: 10px; left: 10px; width: 45%; white-space: nowrap; font-weight: bold; }
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
            td:nth-of-type(12):before { content: 'Cotes mi-temps'; }
            td:nth-of-type(13):before { content: 'Prédiction mi-temps'; }
        }
        /* Loader */
        #loader { display: none; position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; background: rgba(255,255,255,0.7); z-index: 9999; justify-content: center; align-items: center; }
        #loader .spinner { border: 8px solid #f3f3f3; border-top: 8px solid #2c3e50; border-radius: 50%; width: 60px; height: 60px; animation: spin 1s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
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
    <div id="loader"><div class="spinner"></div></div>
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
    <table>
        <tr>
            <th>Équipe 1</th><th>Score 1</th><th>Score 2</th><th>Équipe 2</th>
            <th>Sport</th><th>Ligue</th><th>Statut</th><th>Date & Heure</th>
            <th>Température</th><th>Humidité</th><th>Cotes</th>
            <th>Cotes mi-temps</th><th>Prédiction mi-temps</th><th>Détails</th>
        </tr>
        {% for m in data %}
        <tr>
            <td>{% if m.team1 and m.id %}<img class='team-logo' src='https://1xbet.com/images/events/{{m.id}}_1.png' onerror="this.style.display='none'">{% endif %}{{m.team1}}</td>
            <td>{{m.score1}}</td><td>{{m.score2}}</td>
            <td>{% if m.team2 and m.id %}<img class='team-logo' src='https://1xbet.com/images/events/{{m.id}}_2.png' onerror="this.style.display='none'">{% endif %}{{m.team2}}</td>
            <td>{{m.sport}}</td><td>{{m.league}}</td>
            <td><span class='status-dot {% if 'En cours' in m.status %}status-live{% elif 'Terminé' in m.status %}status-finished{% else %}status-upcoming{% endif %}'></span>{{m.status}}</td>
            <td>{{m.datetime}}</td>
            <td>{{m.temp}}°C</td><td>{{m.humid}}%</td><td>
              {% if m.conseils %}
                {% for conseil in m.conseils[:3] %}
                  <div style='font-size:14px;color:#27ae60;font-weight:bold;margin-bottom:4px;'>🔮 Conseil du bot : {{ conseil }}</div>
                {% endfor %}
              {% else %}
                <div style='font-size:13px;color:#c0392b;'>Aucun conseil fiable disponible pour ce match</div>
              {% endif %}
              <details style='font-size:12px;'>
                <summary style='cursor:pointer;color:#2980b9;'>Toutes les options</summary>
                <ul style='text-align:left;'>
                  {% for opt in m.bet_options %}
                    <li>{{opt.label}} : <b>{{opt.cote}}</b></li>
                  {% endfor %}
                </ul>
              </details>
            </td>
            <td>{{m.halftime_odds|join(" | ")}}</td>
            <td>{{m.halftime_prediction}}<div class='probs'>{% for p in m.halftime_probs %}<span class='{% if loop.index0 == 0 %}prob-high{% elif loop.index0 == 1 %}prob-mid{% else %}prob-low{% endif %}'>{{p.type}}: {{p.prob}}</span> {% if not loop.last %}| {% endif %}{% endfor %}</div></td>
            <td>{% if m.id %}<a href="/match/{{m.id}}"><button>Détails</button></a> <button class="share-btn" onclick="navigator.clipboard.writeText(window.location.origin+'/match/{{m.id}}');alert('Lien copié !');">Partager</button>{% else %}–{% endif %}
        </tr>
        {% endfor %}
    </table>
    <footer style="margin-top:40px;text-align:center;font-size:15px;color:#888;">
        Créateur : <b>SOLITAIRE HACK</b> | Telegram : <a href="https://t.me/Roidesombres225" target="_blank">@Roidesombres225</a> | Canal : <a href="https://t.me/SOLITAIREHACK" target="_blank">https://t.me/SOLITAIREHACK</a>
    </footer>
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

# Initialisation Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Création d'un admin par défaut si aucun n'existe
with app.app_context():
    db.create_all()
    if not User.query.filter_by(email=ADMIN_EMAIL).first():
        admin = User(email=ADMIN_EMAIL, is_admin=True)
        admin.set_password(ADMIN_PASSWORD)
        from datetime import datetime, timedelta
        admin.access_until = datetime.utcnow() + timedelta(days=365*10)
        db.session.add(admin)
        db.session.commit()

from flask import flash, session

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if not user.is_access_valid():
                logging.warning(f"Tentative d'accès expiré pour {email}")
                return render_template_string('<div style="padding:40px;text-align:center;color:#c0392b;font-size:22px;">Accès expiré. Contactez l\'administrateur.</div>')
            login_user(user)
            logging.info(f"Connexion réussie pour {email}")
            return redirect(url_for('home'))
        else:
            logging.warning(f"Échec de connexion pour {email}")
            return render_template_string(LOGIN_TEMPLATE, error="Identifiants invalides.")
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
@login_required
def logout():
    logging.info(f"Déconnexion de {current_user.email}")
    logout_user()
    return redirect(url_for('login'))

# Protection de la page d'accueil et autres routes sensibles
@app.before_request
def restrict_access():
    allowed_routes = ['login', 'static']
    if request.endpoint not in allowed_routes:
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if not current_user.is_access_valid():
            logout_user()
            return render_template_string('<div style="padding:40px;text-align:center;color:#c0392b;font-size:22px;">Votre accès a expiré.</div>')

# Page de gestion des utilisateurs (admin uniquement)
@app.route('/users', methods=['GET', 'POST'])
@login_required
def users():
    if not current_user.is_admin:
        return render_template_string('<div style="padding:40px;text-align:center;color:#c0392b;font-size:22px;">Accès réservé à l\'administrateur.</div>')
    from datetime import datetime, timedelta
    # Suppression d'utilisateur
    if request.method == 'POST' and 'delete_user' in request.form:
        del_email = request.form['delete_user']
        if del_email != current_user.email:
            user = User.query.filter_by(email=del_email).first()
            if user:
                db.session.delete(user)
                db.session.commit()
                logging.info(f"Suppression de l'utilisateur {del_email} par {current_user.email}")
                flash(f"Utilisateur {del_email} supprimé.")
    # Ajout/modification d'utilisateur
    elif request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        # Empêcher la création d'autres admins
        is_admin = (email.strip().lower() == ADMIN_EMAIL)
        duration = request.form['duration'] if 'duration' in request.form else '30min'
        now = datetime.utcnow()
        if duration == '30min':
            access_until = now + timedelta(minutes=30)
        elif duration == '1j':
            access_until = now + timedelta(days=1)
        elif duration == '1w':
            access_until = now + timedelta(weeks=1)
        elif duration == '1m':
            access_until = now + timedelta(days=30)
        elif duration == '2m':
            access_until = now + timedelta(days=60)
        elif duration == 'custom' and 'custom_date' in request.form:
            access_until = datetime.strptime(request.form['custom_date'], '%Y-%m-%dT%H:%M')
        else:
            access_until = now + timedelta(minutes=30)  # Par défaut 30 min
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(password)
            user.is_admin = is_admin
            user.access_until = access_until
            action = "modifié"
        else:
            user = User(email=email, is_admin=is_admin, access_until=access_until)
            user.set_password(password)
            db.session.add(user)
            action = "créé"
        db.session.commit()
        logging.info(f"Utilisateur {email} {action} par {current_user.email}")
        flash('Utilisateur ajouté ou modifié avec succès.')
    users = User.query.all()
    return render_template_string(USERS_TEMPLATE, users=users, current_user=current_user)

# Page de profil utilisateur
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    message = None
    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        if not current_user.check_password(old_password):
            message = "Ancien mot de passe incorrect."
        elif new_password != confirm_password:
            message = "Les nouveaux mots de passe ne correspondent pas."
        elif len(new_password) < 5:
            message = "Le nouveau mot de passe doit contenir au moins 5 caractères."
        else:
            user = User.query.get(current_user.id)
            user.set_password(new_password)
            db.session.commit()
            logging.info(f"Mot de passe changé pour {current_user.email}")
            message = "Mot de passe changé avec succès !"
    return render_template_string(PROFILE_TEMPLATE, user=current_user, message=message)

# Templates HTML pour login, gestion utilisateurs, profil
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Connexion</title></head><body style="background:#f4f4f4;font-family:Arial;">
<div style="max-width:400px;margin:60px auto;background:white;padding:30px;border-radius:10px;box-shadow:0 2px 8px #ccc;">
<h2 style="text-align:center;">Connexion</h2>
{% if error %}<div style="color:#c0392b;text-align:center;">{{error}}</div>{% endif %}
<form method="post">
<label>Email :<input type="email" name="email" required style="width:100%;padding:8px;margin:8px 0;"></label><br>
<label>Mot de passe :<input type="password" name="password" required style="width:100%;padding:8px;margin:8px 0;"></label><br>
<button type="submit" style="width:100%;padding:10px;background:#27ae60;color:white;border:none;border-radius:4px;font-size:16px;">Se connecter</button>
</form>
<div style="text-align:center;margin-top:10px;">
Pas encore de compte ? <a href="/register">S'inscrire</a>
</div>
</div></body></html>
'''

USERS_TEMPLATE = '''
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Utilisateurs</title></head><body style="background:#f4f4f4;font-family:Arial;">
<div style="max-width:700px;margin:40px auto;background:white;padding:30px;border-radius:10px;box-shadow:0 2px 8px #ccc;">
<h2>Gestion des utilisateurs</h2>
<form method="post" style="margin-bottom:30px;">
<label>Email :<input type="email" name="email" required></label>
<label>Mot de passe :<input type="password" name="password" required></label>
<label>Durée d'accès :<select name="duration" onchange="document.getElementById('custom_date_block').style.display = this.value=='custom'?'inline':'none';">
<option value="1j">1 jour</option>
<option value="1w">1 semaine</option>
<option value="1m">1 mois</option>
<option value="2m">2 mois</option>
<option value="30min">30 minutes</option>
<option value="custom">Date personnalisée</option>
</select></label>
<span id="custom_date_block" style="display:none;">
<input type="datetime-local" name="custom_date">
</span>
<label><input type="checkbox" name="is_admin"> Administrateur</label>
<button type="submit">Ajouter/Modifier</button>
</form>
<table border="1" style="width:100%;border-collapse:collapse;">
<tr><th>Email</th><th>Admin</th><th>Accès jusqu'au</th><th>Action</th></tr>
{% for u in users %}
<tr><td>{{u.email}}</td><td>{{'Oui' if u.is_admin else 'Non'}}</td><td>{{u.access_until if u.access_until else 'Illimité'}}</td><td>{% if u.email != current_user.email %}<form method="post" style="display:inline;"><input type="hidden" name="delete_user" value="{{u.email}}"><button type="submit" onclick="return confirm('Supprimer {{u.email}} ?');">Supprimer</button></form>{% else %}<span style="color:#888;">(vous)</span>{% endif %}</td></tr>
{% endfor %}
</table>
<a href="/logout">Déconnexion</a> | <a href="/profile">Mon profil</a> | <a href="/">Accueil</a>
</div></body></html>
'''

PROFILE_TEMPLATE = '''
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Profil</title></head><body style="background:#f4f4f4;font-family:Arial;">
<div style="max-width:400px;margin:60px auto;background:white;padding:30px;border-radius:10px;box-shadow:0 2px 8px #ccc;">
<h2>Mon profil</h2>
<p><b>Email :</b> {{user.email}}</p>
<p><b>Administrateur :</b> {{'Oui' if user.is_admin else 'Non'}}</p>
<p><b>Accès jusqu'au :</b> {{user.access_until if user.access_until else 'Illimité'}}</p>
{% if message %}<div style="color:#27ae60;text-align:center;margin-bottom:10px;">{{message}}</div>{% endif %}
<h3>Changer mon mot de passe</h3>
<form method="post">
<label>Ancien mot de passe :<input type="password" name="old_password" required></label><br>
<label>Nouveau mot de passe :<input type="password" name="new_password" required></label><br>
<label>Confirmer le nouveau :<input type="password" name="confirm_password" required></label><br>
<button type="submit">Changer le mot de passe</button>
</form>
<a href="/logout">Déconnexion</a> | <a href="/">Accueil</a>
</div></body></html>
'''

@app.route('/register', methods=['GET', 'POST'])
def register():
    from datetime import datetime, timedelta
    message = None
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        confirm = request.form['confirm']
        if User.query.filter_by(email=email).first():
            message = "Cet email est déjà utilisé."
        elif email.strip().lower() == ADMIN_EMAIL:
            message = "Impossible de s'inscrire avec cet email."
        elif len(password) < 5:
            message = "Le mot de passe doit contenir au moins 5 caractères."
        elif password != confirm:
            message = "Les mots de passe ne correspondent pas."
        else:
            user = User(email=email, is_admin=False, access_until=datetime.utcnow() + timedelta(minutes=30))
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            logging.info(f"Nouvel utilisateur inscrit : {email}")
            return redirect(url_for('login'))
    return render_template_string(REGISTER_TEMPLATE, message=message)

REGISTER_TEMPLATE = '''
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Inscription</title></head><body style="background:#f4f4f4;font-family:Arial;">
<div style="max-width:400px;margin:60px auto;background:white;padding:30px;border-radius:10px;box-shadow:0 2px 8px #ccc;">
<h2 style="text-align:center;">Inscription</h2>
{% if message %}<div style="color:#c0392b;text-align:center;">{{message}}</div>{% endif %}
<form method="post">
<label>Email :<input type="email" name="email" required style="width:100%;padding:8px;margin:8px 0;"></label><br>
<label>Mot de passe :<input type="password" name="password" required style="width:100%;padding:8px;margin:8px 0;"></label><br>
<label>Confirmer le mot de passe :<input type="password" name="confirm" required style="width:100%;padding:8px;margin:8px 0;"></label><br>
<button type="submit" style="width:100%;padding:10px;background:#27ae60;color:white;border:none;border-radius:4px;font-size:16px;">S'inscrire</button>
</form>
<div style="text-align:center;margin-top:10px;">
Déjà inscrit ? <a href="/login">Se connecter</a>
</div>
</div></body></html>
'''

ADMIN_EMAIL = 'kingsaddes@gmail.com'
ADMIN_PASSWORD = '66240702Mkings'

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "verif_conseils":
        import json
        with open("Get1x2_VZip.json", encoding="utf-8") as f:
            data = json.load(f)
        matchs = data.get("Value", [])
        total = 0
        sans_conseil = 0
        for match in matchs:
            team1 = match.get('O1', 'Équipe 1')
            team2 = match.get('O2', 'Équipe 2')
            conseils = predire_options(match)
            print(f"\n=== {team1} vs {team2} ===")
            if conseils:
                for c in conseils:
                    print(f"  - {c}")
            else:
                print("  Aucun conseil généré pour ce match !")
                sans_conseil += 1
            total += 1
        print(f"\n{total} matchs analysés. {sans_conseil} sans aucun conseil.")
    else:
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port)
