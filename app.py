from flask import Flask, request, render_template_string
import requests
import os
import datetime
import json

app = Flask(__name__)

def load_json_data():
    """Charge les données depuis le fichier JSON local"""
    try:
        with open('Get1x2_VZip (3).json', 'r', encoding='utf-8') as file:
            data = json.load(file)
            return data.get("Value", [])
    except FileNotFoundError:
        print("Fichier JSON non trouvé, utilisation de l'API en ligne")
        return load_from_api()
    except Exception as e:
        print(f"Erreur lors du chargement du fichier JSON: {e}")
        return load_from_api()

def load_from_api():
    """Charge les données depuis l'API en ligne (fallback)"""
    try:
        api_url = "https://1xbet.com/LiveFeed/Get1x2_VZip?count=100&lng=fr&gr=70&mode=4&country=96&top=true"
        response = requests.get(api_url)
        return response.json().get("Value", [])
    except Exception as e:
        print(f"Erreur lors du chargement depuis l'API: {e}")
        return []

@app.route('/')
def home():
    try:
        selected_sport = request.args.get("sport", "").strip()
        selected_league = request.args.get("league", "").strip()
        selected_status = request.args.get("status", "").strip()

        # Utiliser le fichier JSON local
        matches = load_json_data()

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

def traduire_pari(nom, valeur=None):
    """Traduit le nom d'un pari alternatif et sa valeur en français."""
    nom_str = str(nom).lower() if nom else ""
    valeur_str = str(valeur) if valeur is not None else ""
    valeur_str_lower = valeur_str.lower()
    # Cas Oui/Non
    if valeur_str_lower in ["yes", "oui"]:
        choix = "Oui"
    elif valeur_str_lower in ["no", "non"]:
        choix = "Non"
    else:
        choix = valeur_str
    if "total" in nom_str:
        if "over" in nom_str or "over" in valeur_str_lower or "+" in valeur_str:
            return ("Plus de buts", choix)
        elif "under" in nom_str or "under" in valeur_str_lower or "-" in valeur_str:
            return ("Moins de buts", choix)
        else:
            return ("Total buts", choix)
    elif "both teams to score" in nom_str:
        return ("Les deux équipes marquent", choix)
    elif "handicap" in nom_str:
        return ("Handicap", choix)
    elif "double chance" in nom_str:
        return ("Double chance", choix)
    elif "draw no bet" in nom_str:
        return ("Remboursé si match nul", choix)
    elif "odd/even" in nom_str or "odd" in nom_str or "even" in nom_str:
        return ("Nombre de buts pair/impair", choix)
    elif "clean sheet" in nom_str:
        return ("Clean sheet (équipe ne prend pas de but)", choix)
    elif "correct score" in nom_str:
        return ("Score exact", choix)
    elif "win to nil" in nom_str:
        return ("Gagne sans encaisser de but", choix)
    elif "first goal" in nom_str:
        return ("Première équipe à marquer", choix)
    elif "to win" in nom_str:
        return ("Pour gagner", choix)
    else:
        return (nom_str.capitalize(), choix)

def traduire_pari_type_groupe(type_pari, groupe, param, team1=None, team2=None):
    """Traduit le type de pari selon T, G et P (structure 1xbet) avec mapping explicite, noms d'équipes et distinction Over/Under."""
    # 1X2
    if groupe == 1 and type_pari in [1, 2, 3]:
        return {1: f"Victoire {team1}", 2: f"Victoire {team2}", 3: "Match nul"}.get(type_pari, "1X2")
    # Handicap
    if groupe == 2:
        if param is not None:
            if type_pari == 1 and team1:
                return f"Handicap {team1} {param}"
            elif type_pari == 2 and team2:
                return f"Handicap {team2} {param}"
            else:
                return f"Handicap {param}"
        return "Handicap"
    # Over/Under (souvent G8 ou G17 ou G62)
    if groupe in [8, 17, 62]:
        if param is not None:
            seuil = abs(float(param))
            if type_pari in [9]:  # T=9 = Over (Plus de)
                return f"Plus de {seuil} buts"
            elif type_pari in [10]:  # T=10 = Under (Moins de)
                return f"Moins de {seuil} buts"
            # fallback si on ne sait pas
            if float(param) > 0:
                return f"Plus de {seuil} buts"
            else:
                return f"Moins de {seuil} buts"
        return "Plus/Moins de buts"
    # Score exact
    if groupe == 15:
        if param is not None:
            return f"Score exact {param}"
        return "Score exact"
    # Double chance
    if groupe == 3:
        if type_pari == 1 and team1 and team2:
            return f"Double chance {team1} ou {team2}"
        elif type_pari == 2 and team1:
            return f"Double chance {team1} ou Nul"
        elif type_pari == 3 and team2:
            return f"Double chance {team2} ou Nul"
        return "Double chance"
    # Nombre de buts
    if groupe in [19, 180, 181]:
        return "Nombre de buts"
    # Ajoute d'autres mappings selon tes observations
    return f"Pari spécial (G{groupe} T{type_pari})"

@app.route('/match/<int:match_id>')
def match_details(match_id):
    try:
        # Récupérer les données depuis le fichier JSON local
        matches = load_json_data()
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
        # Prédiction 1X2
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
        # --- Paris alternatifs ---
        paris_alternatifs = []
        # 1. E (marchés principaux et alternatifs)
        for o in match.get("E", []):
            if o.get("G") != 1 and o.get("C") is not None:
                type_pari = o.get("T")
                groupe = o.get("G")
                param = o.get("P") if "P" in o else None
                nom_traduit = traduire_pari_type_groupe(type_pari, groupe, param, team1, team2)
                valeur = param if param is not None else ""
                cote = o.get("C")
                paris_alternatifs.append({
                    "nom": nom_traduit,
                    "valeur": valeur,
                    "cote": cote
                })
        # 2. AE (marchés alternatifs étendus)
        for ae in match.get("AE", []):
            if ae.get("G") != 1:
                for o in ae.get("ME", []):
                    if o.get("C") is not None:
                        type_pari = o.get("T")
                        groupe = o.get("G")
                        param = o.get("P") if "P" in o else None
                        nom_traduit = traduire_pari_type_groupe(type_pari, groupe, param, team1, team2)
                        valeur = param if param is not None else ""
                        cote = o.get("C")
                        paris_alternatifs.append({
                            "nom": nom_traduit,
                            "valeur": valeur,
                            "cote": cote
                        })
        # Filtrer les paris alternatifs selon la cote demandée
        paris_alternatifs = [p for p in paris_alternatifs if 1.499 <= float(p["cote"]) <= 3]
        # Sélection de la prédiction alternative la plus probable (cote la plus basse)
        prediction_alt = None
        if paris_alternatifs:
            meilleur_pari = min(paris_alternatifs, key=lambda x: x["cote"])
            prediction_alt = f"{meilleur_pari['nom']} ({meilleur_pari['valeur']}) à {meilleur_pari['cote']}"
        # HTML avec tableau des paris alternatifs
        return f'''
        <!DOCTYPE html>
        <html><head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Détails du match</title>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                body {{ font-family: Arial; padding: 20px; background: #f4f4f4; }}
                .container {{ max-width: 800px; margin: auto; background: white; border-radius: 10px; box-shadow: 0 2px 8px #ccc; padding: 20px; }}
                h2 {{ text-align: center; }}
                .stats-table, .alt-table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                .stats-table th, .stats-table td, .alt-table th, .alt-table td {{ border: 1px solid #ccc; padding: 8px; text-align: center; }}
                .back-btn {{ margin-bottom: 20px; display: inline-block; }}
                .highlight-pred {{ background: #eaf6fb; color: #2980b9; font-weight: bold; padding: 10px; border-radius: 6px; margin-bottom: 15px; }}
                .contact-box {{ background: #f0f8ff; border: 1.5px solid #2980b9; border-radius: 8px; margin-top: 30px; padding: 18px; text-align: center; font-size: 17px; }}
                .contact-box a {{ color: #1565c0; font-weight: bold; text-decoration: none; }}
            </style>
        </head><body>
            <div class="container">
                <a href="/" class="back-btn">&larr; Retour à la liste</a>
                <h2>{team1} vs {team2}</h2>
                <p><b>Ligue :</b> {league} | <b>Sport :</b> {sport}</p>
                <p><b>Score :</b> {score1} - {score2}</p>
                <p><b>Prédiction 1X2 du bot :</b> {prediction}</p>
                <p><b>Explication :</b> {explication}</p>
                <div class="highlight-pred">
                    <b>Prédiction alternative du bot :</b><br>
                    {prediction_alt if prediction_alt else 'Aucune prédiction alternative disponible'}
                </div>
                <h3>Statistiques principales</h3>
                <table class="stats-table">
                    <tr><th>Statistique</th><th>{team1}</th><th>{team2}</th></tr>
                    {''.join(f'<tr><td>{s["nom"]}</td><td>{s["s1"]}</td><td>{s["s2"]}</td></tr>' for s in stats)}
                </table>
                <h3>Tableau des paris alternatifs</h3>
                <table class="alt-table">
                    <tr><th>Type de pari</th><th>Valeur</th><th>Cote</th><th>Prédiction</th></tr>
                    {''.join(f'<tr><td>{p["nom"]}</td><td>{p["valeur"]}</td><td>{p["cote"]}</td><td>{generer_prediction_lisible(p["nom"], p["valeur"], team1, team2)}</td></tr>' for p in paris_alternatifs)}
                </table>
                <canvas id="statsChart" height="200"></canvas>
                <div class="contact-box">
                    <b>Contact & Services :</b><br>
                    📬 Inbox Telegram : <a href="https://t.me/Roidesombres225" target="_blank">@Roidesombres225</a><br>
                    📢 Canal Telegram : <a href="https://t.me/SOLITAIREHACK" target="_blank">SOLITAIREHACK</a><br>
                    🎨 Je suis aussi concepteur graphique et créateur de logiciels.<br>
                    <span style="color:#2980b9;">Vous avez un projet en tête ? Contactez-moi, je suis là pour vous !</span>
                </div>
            </div>
            <script>
                const labels = {json.dumps([s['nom'] for s in stats])};
                const data1 = {json.dumps([float(s['s1']) if str(s['s1']).replace('.', '', 1).isdigit() else 0 for s in stats])};
                const data2 = {json.dumps([float(s['s2']) if str(s['s2']).replace('.', '', 1).isdigit() else 0 for s in stats])};
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
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
            padding: 30px;
            animation: fadeInUp 0.8s ease-out;
        }
        
        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(30px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        h2 { 
            text-align: center; 
            font-size: 2.5em;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 30px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
        }
        
        .filters-container {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 30px;
            box-shadow: 0 10px 20px rgba(0,0,0,0.1);
        }
        
        form { 
            text-align: center; 
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            justify-content: center;
            align-items: center;
        }
        
        label { 
            font-weight: bold; 
            color: white;
            font-size: 1.1em;
            text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
        }
        
        select { 
            padding: 12px 20px; 
            font-size: 16px; 
            border-radius: 25px; 
            border: none; 
            background: rgba(255,255,255,0.9); 
            color: #333;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
            cursor: pointer;
        }
        
        select:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        }
        
        select:focus { 
            outline: none;
            box-shadow: 0 0 0 3px rgba(255,255,255,0.5);
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            box-shadow: 0 10px 20px rgba(0,0,0,0.1);
            transition: transform 0.3s ease;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
        }
        
        .stat-card i {
            font-size: 2em;
            margin-bottom: 10px;
        }
        
        .table-container {
            background: white;
            border-radius: 15px;
            overflow: hidden;
            box-shadow: 0 15px 35px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }
        
        table { 
            width: 100%;
            border-collapse: collapse;
            background: white;
        }
        
        th, td { 
            padding: 15px; 
            text-align: center; 
            font-size: 16px; 
            border-bottom: 1px solid #eee;
        }
        
        th { 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 18px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        tr { transition: all 0.3s ease; }
        
        tr:hover {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            transform: scale(1.02);
        }
        
        tr:nth-child(even) { background-color: #f8f9fa; }
        
        .status-badge {
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.9em;
            text-transform: uppercase;
        }
        
        .status-live {
            background: linear-gradient(45deg, #ff6b6b, #ee5a24);
            color: white;
            animation: pulse 2s infinite;
        }
        
        .status-finished {
            background: linear-gradient(45deg, #2ed573, #1e90ff);
            color: white;
        }
        
        .status-upcoming {
            background: linear-gradient(45deg, #ffa726, #ff7043);
            color: white;
        }
        
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(255, 107, 107, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(255, 107, 107, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 107, 107, 0); }
        }
        
        .pagination { 
            text-align: center; 
            margin: 30px 0; 
        }
        
        .pagination button { 
            padding: 15px 30px; 
            margin: 0 10px; 
            font-size: 16px; 
            border: none; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; 
            border-radius: 25px; 
            cursor: pointer; 
            font-weight: bold; 
            transition: all 0.3s ease;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        
        .pagination button:hover {
            transform: translateY(-3px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.2);
        }
        
        .pagination button:disabled { 
            background: #b2bec3; 
            color: #636e72; 
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }
        
        .details-btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: bold;
        }
        
        .details-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        
        .contact-box { 
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
            border: none;
            border-radius: 20px; 
            margin: 40px auto 0 auto; 
            padding: 30px; 
            text-align: center; 
            font-size: 20px; 
            font-weight: bold; 
            color: white; 
            max-width: 700px; 
            box-shadow: 0 20px 40px rgba(255, 107, 107, 0.3);
            animation: bounceIn 1s ease-out;
        }
        
        @keyframes bounceIn {
            0% { transform: scale(0.3); opacity: 0; }
            50% { transform: scale(1.05); }
            70% { transform: scale(0.9); }
            100% { transform: scale(1); opacity: 1; }
        }
        
        .contact-box a { 
            color: white; 
            font-weight: bold; 
            text-decoration: none; 
            font-size: 24px; 
            transition: all 0.3s ease;
        }
        
        .contact-box a:hover {
            text-shadow: 0 0 10px rgba(255,255,255,0.8);
            transform: scale(1.05);
        }
        
        .contact-box .icon { 
            font-size: 28px; 
            vertical-align: middle; 
            margin-right: 10px; 
            animation: float 3s ease-in-out infinite;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-10px); }
        }
        
        /* Loader amélioré */
        #loader { 
            display: none; 
            position: fixed; 
            left: 0; 
            top: 0; 
            width: 100vw; 
            height: 100vh; 
            background: rgba(0,0,0,0.8); 
            z-index: 9999; 
            justify-content: center; 
            align-items: center; 
            backdrop-filter: blur(5px);
        }
        
        #loader .spinner { 
            width: 80px;
            height: 80px;
            border: 8px solid rgba(255,255,255,0.3);
            border-top: 8px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            box-shadow: 0 0 30px rgba(102, 126, 234, 0.5);
        }
        
        @keyframes spin { 
            100% { transform: rotate(360deg); } 
        }
        
        /* Responsive amélioré */
        @media (max-width: 768px) {
            .container { padding: 20px; margin: 10px; }
            h2 { font-size: 2em; }
            form { flex-direction: column; }
            .stats-grid { grid-template-columns: 1fr; }
            .table-container { overflow-x: auto; }
            table, thead, tbody, th, td, tr { display: block; }
            th { position: absolute; left: -9999px; top: -9999px; }
            tr { 
                margin-bottom: 20px; 
                background: white; 
                border-radius: 15px; 
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                padding: 15px;
            }
            td { 
                border: none; 
                border-bottom: 1px solid #eee; 
                position: relative; 
                padding-left: 50%; 
                min-height: 50px; 
                font-size: 16px; 
                display: flex;
                align-items: center;
            }
            td:before { 
                position: absolute; 
                top: 50%;
                left: 15px; 
                width: 45%; 
                white-space: nowrap; 
                font-weight: bold; 
                color: #667eea;
                transform: translateY(-50%);
            }
            td:nth-of-type(1):before { content: '🏆 Équipe 1'; }
            td:nth-of-type(2):before { content: '⚽ Score 1'; }
            td:nth-of-type(3):before { content: '⚽ Score 2'; }
            td:nth-of-type(4):before { content: '🏆 Équipe 2'; }
            td:nth-of-type(5):before { content: '🎯 Sport'; }
            td:nth-of-type(6):before { content: '🏅 Ligue'; }
            td:nth-of-type(7):before { content: '📊 Statut'; }
            td:nth-of-type(8):before { content: '🕐 Date & Heure'; }
            td:nth-of-type(9):before { content: '🌡️ Température'; }
            td:nth-of-type(10):before { content: '💧 Humidité'; }
            td:nth-of-type(11):before { content: '💰 Cotes'; }
            td:nth-of-type(12):before { content: '🔮 Prédiction'; }
            td:nth-of-type(13):before { content: '📋 Détails'; }
        }
        
        /* Effets de scroll */
        .scroll-reveal {
            opacity: 0;
            transform: translateY(30px);
            transition: all 0.6s ease;
        }
        
        .scroll-reveal.revealed {
            opacity: 1;
            transform: translateY(0);
        }
    </style>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Animation au scroll
            const observerOptions = {
                threshold: 0.1,
                rootMargin: '0px 0px -50px 0px'
            };
            
            const observer = new IntersectionObserver(function(entries) {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('revealed');
                    }
                });
            }, observerOptions);
            
            document.querySelectorAll('.scroll-reveal').forEach(el => {
                observer.observe(el);
            });
            
            // Loader
            var forms = document.querySelectorAll('form');
            forms.forEach(function(form) {
                form.addEventListener('submit', function() {
                    document.getElementById('loader').style.display = 'flex';
                });
            });
            
            // Effet de parallaxe sur le titre
            window.addEventListener('scroll', function() {
                const scrolled = window.pageYOffset;
                const title = document.querySelector('h2');
                if (title) {
                    title.style.transform = `translateY(${scrolled * 0.5}px)`;
                }
            });
        });
    </script>
</head><body>
    <div id="loader" role="status" aria-live="polite">
        <div class="spinner" aria-label="Chargement"></div>
    </div>
    
    <div class="container">
        <h2 class="scroll-reveal">⚽ Live Football & Sports | Prédictions & Stats 📊</h2>

        <div class="filters-container scroll-reveal">
            <form method="get" aria-label="Filtres de matchs">
                <label for="sport-select"><i class="fas fa-futbol"></i> Sport :</label>
                <select id="sport-select" name="sport" onchange="this.form.submit()" aria-label="Filtrer par sport">
                    <option value="">Tous les sports</option>
                    {% for s in sports %}
                        <option value="{{s}}" {% if s == selected_sport %}selected{% endif %}>{{s}}</option>
                    {% endfor %}
                </select>
                
                <label for="league-select"><i class="fas fa-trophy"></i> Ligue :</label>
                <select id="league-select" name="league" onchange="this.form.submit()" aria-label="Filtrer par ligue">
                    <option value="">Toutes les ligues</option>
                    {% for l in leagues %}
                        <option value="{{l}}" {% if l == selected_league %}selected{% endif %}>{{l}}</option>
                    {% endfor %}
                </select>
                
                <label for="status-select"><i class="fas fa-clock"></i> Statut :</label>
                <select id="status-select" name="status" onchange="this.form.submit()" aria-label="Filtrer par statut">
                    <option value="">Tous les statuts</option>
                    <option value="live" {% if selected_status == "live" %}selected{% endif %}>En direct</option>
                    <option value="upcoming" {% if selected_status == "upcoming" %}selected{% endif %}>À venir</option>
                    <option value="finished" {% if selected_status == "finished" %}selected{% endif %}>Terminé</option>
                </select>
            </form>
        </div>

        <div class="stats-grid scroll-reveal">
            <div class="stat-card">
                <i class="fas fa-futbol"></i>
                <h3>{{ selected_sport if selected_sport != 'Tous' else 'Tous les sports' }}</h3>
                <p>Sport sélectionné</p>
            </div>
            <div class="stat-card">
                <i class="fas fa-trophy"></i>
                <h3>{{ selected_league if selected_league != 'Toutes' else 'Toutes les ligues' }}</h3>
                <p>Ligue sélectionnée</p>
            </div>
            <div class="stat-card">
                <i class="fas fa-chart-line"></i>
                <h3>{{ data|length }} matchs</h3>
                <p>Résultats trouvés</p>
            </div>
        </div>

        <div class="pagination scroll-reveal">
            <form method="get" style="display:inline;" aria-label="Page précédente">
                <input type="hidden" name="sport" value="{{ selected_sport if selected_sport != 'Tous' else '' }}">
                <input type="hidden" name="league" value="{{ selected_league if selected_league != 'Toutes' else '' }}">
                <input type="hidden" name="status" value="{{ selected_status if selected_status != 'Tous' else '' }}">
                <button type="submit" name="page" value="{{ page-1 }}" {% if page <= 1 %}disabled{% endif %} aria-label="Page précédente">
                    <i class="fas fa-chevron-left"></i> Précédente
                </button>
            </form>
            <span aria-live="polite" style="margin: 0 20px; font-weight: bold; color: #667eea;">Page {{ page }} / {{ total_pages }}</span>
            <form method="get" style="display:inline;" aria-label="Page suivante">
                <input type="hidden" name="sport" value="{{ selected_sport if selected_sport != 'Tous' else '' }}">
                <input type="hidden" name="league" value="{{ selected_league if selected_league != 'Toutes' else '' }}">
                <input type="hidden" name="status" value="{{ selected_status if selected_status != 'Tous' else '' }}">
                <button type="submit" name="page" value="{{ page+1 }}" {% if page >= total_pages %}disabled{% endif %} aria-label="Page suivante">
                    Suivante <i class="fas fa-chevron-right"></i>
                </button>
            </form>
        </div>

        <div class="table-container scroll-reveal">
            <table>
                <tr>
                    <th><i class="fas fa-users"></i> Équipe 1</th>
                    <th><i class="fas fa-futbol"></i> Score 1</th>
                    <th><i class="fas fa-futbol"></i> Score 2</th>
                    <th><i class="fas fa-users"></i> Équipe 2</th>
                    <th><i class="fas fa-trophy"></i> Sport</th>
                    <th><i class="fas fa-medal"></i> Ligue</th>
                    <th><i class="fas fa-clock"></i> Statut</th>
                    <th><i class="fas fa-calendar"></i> Date & Heure</th>
                    <th><i class="fas fa-thermometer-half"></i> Température</th>
                    <th><i class="fas fa-tint"></i> Humidité</th>
                    <th><i class="fas fa-coins"></i> Cotes</th>
                    <th><i class="fas fa-magic"></i> Prédiction</th>
                    <th><i class="fas fa-info-circle"></i> Détails</th>
                </tr>
                {% for m in data %}
                <tr class="scroll-reveal">
                    <td><strong>{{m.team1}}</strong></td>
                    <td><span class="score">{{m.score1}}</span></td>
                    <td><span class="score">{{m.score2}}</span></td>
                    <td><strong>{{m.team2}}</strong></td>
                    <td><i class="fas fa-{{ 'futbol' if m.sport == 'Football' else 'basketball-ball' if m.sport == 'Basketball' else 'table-tennis' if m.sport == 'Tennis' else 'hockey-puck' if m.sport == 'Hockey' else 'cricket' if m.sport == 'Cricket' else 'trophy' }}"></i> {{m.sport}}</td>
                    <td>{{m.league}}</td>
                    <td>
                        <span class="status-badge {% if 'En cours' in m.status %}status-live{% elif 'Terminé' in m.status %}status-finished{% else %}status-upcoming{% endif %}">
                            {{m.status}}
                        </span>
                    </td>
                    <td><i class="fas fa-calendar-alt"></i> {{m.datetime}}</td>
                    <td><i class="fas fa-thermometer-half"></i> {{m.temp}}°C</td>
                    <td><i class="fas fa-tint"></i> {{m.humid}}%</td>
                    <td><i class="fas fa-coins"></i> {{m.odds|join(" | ")}}</td>
                    <td><i class="fas fa-magic"></i> {{m.prediction}}</td>
                    <td>
                        {% if m.id %}
                            <a href="/match/{{m.id}}">
                                <button class="details-btn">
                                    <i class="fas fa-eye"></i> Détails
                                </button>
                            </a>
                        {% else %}
                            –
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>
        
        <div class="contact-box scroll-reveal">
            <span class="icon">📬</span> Inbox Telegram : <a href="https://t.me/Roidesombres225" target="_blank">@Roidesombres225</a><br>
            <span class="icon">📢</span> Canal Telegram : <a href="https://t.me/SOLITAIREHACK" target="_blank">SOLITAIREHACK</a><br>
            <span class="icon">🎨</span> Je suis aussi concepteur graphique et créateur de logiciels.<br>
            <span style="color:#fff; font-size:22px; font-weight:bold; text-shadow: 0 2px 4px rgba(0,0,0,0.3);">Vous avez un projet en tête ? Contactez-moi, je suis là pour vous !</span>
        </div>
    </div>
</body></html>"""

def generer_prediction_lisible(nom, valeur, team1, team2):
    """Génère une phrase prédictive claire pour chaque pari, en précisant l'équipe si besoin."""
    if nom.startswith("Victoire "):
        return f"{nom}"
    if nom.startswith("Handicap "):
        return f"{nom}"
    if nom.startswith("Plus de") or nom.startswith("Moins de"):
        return f"{nom}"
    if nom.startswith("Score exact"):
        return f"{nom}"
    if nom.startswith("Double chance"):
        return f"{nom}"
    if nom.startswith("Nombre de buts"):
        return f"{nom}"
    if team1 and team1 in nom:
        return f"{nom} ({team1})"
    if team2 and team2 in nom:
        return f"{nom} ({team2})"
    return nom

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
