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
            <title>Détails du match - {team1} vs {team2}</title>
            <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                
                body {{ 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                }}
                
                .container {{ 
                    max-width: 1200px; 
                    margin: 0 auto; 
                    background: rgba(255, 255, 255, 0.95);
                    border-radius: 20px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                    backdrop-filter: blur(10px);
                    padding: 30px;
                    animation: fadeInUp 0.8s ease-out;
                }}
                
                @keyframes fadeInUp {{
                    from {{ opacity: 0; transform: translateY(30px); }}
                    to {{ opacity: 1; transform: translateY(0); }}
                }}
                
                .back-btn {{
                    display: inline-flex;
                    align-items: center;
                    gap: 10px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    text-decoration: none;
                    padding: 12px 24px;
                    border-radius: 25px;
                    font-weight: bold;
                    margin-bottom: 30px;
                    transition: all 0.3s ease;
                    box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                }}
                
                .back-btn:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 8px 25px rgba(0,0,0,0.2);
                }}
                
                .match-header {{
                    text-align: center;
                    margin-bottom: 40px;
                    padding: 30px;
                    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                    border-radius: 20px;
                    color: white;
                    box-shadow: 0 15px 35px rgba(0,0,0,0.1);
                }}
                
                .match-header h2 {{
                    font-size: 2.5em;
                    margin-bottom: 15px;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                }}
                
                .match-info {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px;
                    margin: 20px 0;
                }}
                
                .info-card {{
                    background: rgba(255,255,255,0.2);
                    padding: 15px;
                    border-radius: 15px;
                    text-align: center;
                    backdrop-filter: blur(10px);
                }}
                
                .score-display {{
                    font-size: 3em;
                    font-weight: bold;
                    margin: 20px 0;
                    text-shadow: 3px 3px 6px rgba(0,0,0,0.3);
                }}
                
                .prediction-section {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 25px;
                    border-radius: 20px;
                    margin: 30px 0;
                    box-shadow: 0 15px 35px rgba(0,0,0,0.1);
                }}
                
                .prediction-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin-top: 20px;
                }}
                
                .prediction-card {{
                    background: rgba(255,255,255,0.1);
                    padding: 20px;
                    border-radius: 15px;
                    text-align: center;
                    backdrop-filter: blur(10px);
                    border: 1px solid rgba(255,255,255,0.2);
                }}
                
                .charts-section {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                    gap: 30px;
                    margin: 40px 0;
                }}
                
                .chart-container {{
                    background: white;
                    border-radius: 20px;
                    padding: 25px;
                    box-shadow: 0 15px 35px rgba(0,0,0,0.1);
                    transition: transform 0.3s ease;
                }}
                
                .chart-container:hover {{
                    transform: translateY(-5px);
                }}
                
                .chart-title {{
                    text-align: center;
                    font-size: 1.5em;
                    font-weight: bold;
                    margin-bottom: 20px;
                    color: #667eea;
                }}
                
                .stats-table, .alt-table {{ 
                    width: 100%; 
                    border-collapse: collapse; 
                    margin-top: 20px;
                    background: white;
                    border-radius: 15px;
                    overflow: hidden;
                    box-shadow: 0 10px 25px rgba(0,0,0,0.1);
                }}
                
                .stats-table th, .stats-table td, .alt-table th, .alt-table td {{ 
                    padding: 15px; 
                    text-align: center; 
                    border-bottom: 1px solid #eee;
                }}
                
                .stats-table th, .alt-table th {{ 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    font-weight: bold;
                    font-size: 1.1em;
                }}
                
                .stats-table tr:nth-child(even), .alt-table tr:nth-child(even) {{ 
                    background-color: #f8f9fa; 
                }}
                
                .stats-table tr:hover, .alt-table tr:hover {{ 
                    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                    color: white;
                    transform: scale(1.02);
                    transition: all 0.3s ease;
                }}
                
                .contact-box {{ 
                    background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
                    color: white;
                    border-radius: 20px; 
                    margin: 40px auto 0 auto; 
                    padding: 30px; 
                    text-align: center; 
                    font-size: 18px; 
                    font-weight: bold; 
                    box-shadow: 0 20px 40px rgba(255, 107, 107, 0.3);
                    animation: bounceIn 1s ease-out;
                }}
                
                @keyframes bounceIn {{
                    0% {{ transform: scale(0.3); opacity: 0; }}
                    50% {{ transform: scale(1.05); }}
                    70% {{ transform: scale(0.9); }}
                    100% {{ transform: scale(1); opacity: 1; }}
                }}
                
                .contact-box a {{ 
                    color: white; 
                    font-weight: bold; 
                    text-decoration: none; 
                    font-size: 20px; 
                    transition: all 0.3s ease;
                }}
                
                .contact-box a:hover {{
                    text-shadow: 0 0 10px rgba(255,255,255,0.8);
                    transform: scale(1.05);
                }}
                
                .progress-bar {{
                    width: 100%;
                    height: 20px;
                    background: #e0e0e0;
                    border-radius: 10px;
                    overflow: hidden;
                    margin: 10px 0;
                }}
                
                .progress-fill {{
                    height: 100%;
                    background: linear-gradient(90deg, #667eea, #764ba2);
                    transition: width 0.3s ease;
                }}
                
                .section-title {{
                    font-size: 2em;
                    text-align: center;
                    margin: 40px 0 20px 0;
                    color: #667eea;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
                }}
                
                @media (max-width: 768px) {{
                    .container {{ 
                        padding: 15px; 
                        margin: 5px; 
                        border-radius: 15px;
                    }}
                    
                    .match-header {{
                        padding: 20px;
                        margin-bottom: 20px;
                    }}
                    
                    .match-header h2 {{ 
                        font-size: 1.8em; 
                        margin-bottom: 10px;
                    }}
                    
                    .score-display {{ 
                        font-size: 2.2em; 
                        margin: 15px 0;
                    }}
                    
                    .match-info {{
                        grid-template-columns: 1fr;
                        gap: 15px;
                    }}
                    
                    .info-card {{
                        padding: 12px;
                    }}
                    
                    .prediction-section {{
                        padding: 20px;
                        margin: 20px 0;
                    }}
                    
                    .prediction-grid {{ 
                        grid-template-columns: 1fr; 
                        gap: 15px;
                    }}
                    
                    .prediction-card {{
                        padding: 15px;
                    }}
                    
                    .charts-section {{ 
                        grid-template-columns: 1fr; 
                        gap: 20px;
                        margin: 20px 0;
                    }}
                    
                    .chart-container {{
                        padding: 20px;
                        margin-bottom: 20px;
                    }}
                    
                    .chart-title {{
                        font-size: 1.3em;
                        margin-bottom: 15px;
                    }}
                    
                    .section-title {{
                        font-size: 1.6em;
                        margin: 30px 0 15px 0;
                    }}
                    
                    .stats-table, .alt-table {{
                        font-size: 14px;
                    }}
                    
                    .stats-table th, .stats-table td, .alt-table th, .alt-table td {{
                        padding: 10px;
                    }}
                    
                    .contact-box {{
                        padding: 20px;
                        font-size: 16px;
                        margin: 20px auto;
                    }}
                    
                    .contact-box a {{
                        font-size: 18px;
                    }}
                }}
                
                /* Optimisations pour tablettes */
                @media (min-width: 769px) and (max-width: 1024px) {{
                    .container {{
                        max-width: 95%;
                        padding: 25px;
                    }}
                    
                    .charts-section {{
                        grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
                    }}
                    
                    .prediction-grid {{
                        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    }}
                }}
                
                /* Optimisations pour PC */
                @media (min-width: 1025px) {{
                    .container {{
                        max-width: 1200px;
                    }}
                    
                    .charts-section {{
                        grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                    }}
                    
                    .prediction-grid {{
                        grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    }}
                }}
            </style>
        </head><body>
            <div class="container">
                <a href="/" class="back-btn">
                    <i class="fas fa-arrow-left"></i> Retour à la liste
                </a>
                
                <div class="match-header">
                    <h2><i class="fas fa-futbol"></i> {team1} vs {team2}</h2>
                    <div class="score-display">{score1} - {score2}</div>
                    <div class="match-info">
                        <div class="info-card">
                            <i class="fas fa-trophy"></i><br>
                            <strong>Ligue</strong><br>
                            {league}
                        </div>
                        <div class="info-card">
                            <i class="fas fa-running"></i><br>
                            <strong>Sport</strong><br>
                            {sport}
                        </div>
                        <div class="info-card">
                            <i class="fas fa-clock"></i><br>
                            <strong>Statut</strong><br>
                            {'En cours' if score1 > 0 or score2 > 0 else 'À venir'}
                        </div>
                    </div>
                </div>
                
                <div class="prediction-section">
                    <h3><i class="fas fa-magic"></i> Prédictions du Bot</h3>
                    <div class="prediction-grid">
                        <div class="prediction-card">
                            <i class="fas fa-chart-line"></i><br>
                            <strong>Prédiction 1X2</strong><br>
                            {prediction}
                        </div>
                        <div class="prediction-card">
                            <i class="fas fa-star"></i><br>
                            <strong>Prédiction Alternative</strong><br>
                            {prediction_alt if prediction_alt else 'Aucune disponible'}
                        </div>
                    </div>
                    <p style="margin-top: 20px; font-style: italic;">
                        <i class="fas fa-info-circle"></i> {explication}
                    </p>
                </div>
                
                <h3 class="section-title"><i class="fas fa-chart-bar"></i> Statistiques Visuelles</h3>
                
                <div class="charts-section">
                    <div class="chart-container">
                        <div class="chart-title">
                            <i class="fas fa-chart-bar"></i> Comparaison des Statistiques
                        </div>
                        <canvas id="statsChart" height="300"></canvas>
                    </div>
                    
                    <div class="chart-container">
                        <div class="chart-title">
                            <i class="fas fa-chart-pie"></i> Répartition des Performances
                        </div>
                        <canvas id="performanceChart" height="300"></canvas>
                    </div>
                </div>
                
                <h3 class="section-title"><i class="fas fa-table"></i> Données Détaillées</h3>
                
                <div class="chart-container">
                    <div class="chart-title">Statistiques Principales</div>
                    <table class="stats-table">
                        <tr>
                            <th><i class="fas fa-chart-line"></i> Statistique</th>
                            <th><i class="fas fa-user"></i> {team1}</th>
                            <th><i class="fas fa-user"></i> {team2}</th>
                            <th><i class="fas fa-percentage"></i> Avantage</th>
                        </tr>
                        {''.join(f'<tr><td>{s["nom"]}</td><td>{s["s1"]}</td><td>{s["s2"]}</td><td><div class="progress-bar"><div class="progress-fill" style="width: {calculate_percentage(s["s1"], s["s2"])}%"></div></div></td></tr>' for s in stats)}
                    </table>
                </div>
                
                <div class="chart-container">
                    <div class="chart-title">Paris Alternatifs</div>
                    <table class="alt-table">
                        <tr>
                            <th><i class="fas fa-tag"></i> Type de Pari</th>
                            <th><i class="fas fa-hashtag"></i> Valeur</th>
                            <th><i class="fas fa-coins"></i> Cote</th>
                            <th><i class="fas fa-magic"></i> Prédiction</th>
                        </tr>
                        {''.join(f'<tr><td>{p["nom"]}</td><td>{p["valeur"]}</td><td><span style="color: #667eea; font-weight: bold;">{p["cote"]}</span></td><td>{generer_prediction_lisible(p["nom"], p["valeur"], team1, team2)}</td></tr>' for p in paris_alternatifs)}
                    </table>
                </div>
                
                <div class="contact-box">
                    <i class="fas fa-envelope" style="font-size: 24px; margin-right: 10px;"></i>
                    <strong>Contact & Services :</strong><br><br>
                    📬 Inbox Telegram : <a href="https://t.me/Roidesombres225" target="_blank">@Roidesombres225</a><br>
                    📢 Canal Telegram : <a href="https://t.me/SOLITAIREHACK" target="_blank">SOLITAIREHACK</a><br><br>
                    🎨 Je suis aussi concepteur graphique et créateur de logiciels.<br>
                    <span style="color:#fff; font-size:20px; font-weight:bold; text-shadow: 0 2px 4px rgba(0,0,0,0.3);">
                        Vous avez un projet en tête ? Contactez-moi, je suis là pour vous !
                    </span>
                </div>
            </div>
            
            <script>
                // Graphique des statistiques principales
                const labels = {json.dumps([s['nom'] for s in stats])};
                const data1 = {json.dumps([float(s['s1']) if str(s['s1']).replace('.', '', 1).isdigit() else 0 for s in stats])};
                const data2 = {json.dumps([float(s['s2']) if str(s['s2']).replace('.', '', 1).isdigit() else 0 for s in stats])};
                
                new Chart(document.getElementById('statsChart'), {{
                    type: 'bar',
                    data: {{
                        labels: labels,
                        datasets: [
                            {{
                                label: '{team1}',
                                data: data1,
                                backgroundColor: 'rgba(102, 126, 234, 0.8)',
                                borderColor: 'rgba(102, 126, 234, 1)',
                                borderWidth: 2,
                                borderRadius: 8,
                                borderSkipped: false,
                            }},
                            {{
                                label: '{team2}',
                                data: data2,
                                backgroundColor: 'rgba(118, 75, 162, 0.8)',
                                borderColor: 'rgba(118, 75, 162, 1)',
                                borderWidth: 2,
                                borderRadius: 8,
                                borderSkipped: false,
                            }}
                        ]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{
                                position: 'top',
                                labels: {{
                                    font: {{
                                        size: 14,
                                        weight: 'bold'
                                    }},
                                    padding: 20
                                }}
                            }},
                            title: {{
                                display: true,
                                text: 'Comparaison des Statistiques',
                                font: {{
                                    size: 18,
                                    weight: 'bold'
                                }}
                            }}
                        }},
                        scales: {{
                            y: {{
                                beginAtZero: true,
                                grid: {{
                                    color: 'rgba(0,0,0,0.1)'
                                }}
                            }},
                            x: {{
                                grid: {{
                                    display: false
                                }}
                            }}
                        }},
                        animation: {{
                            duration: 2000,
                            easing: 'easeInOutQuart'
                        }}
                    }}
                }});
                
                // Graphique de performance (donut chart)
                const total1 = data1.reduce((a, b) => a + b, 0);
                const total2 = data2.reduce((a, b) => a + b, 0);
                
                new Chart(document.getElementById('performanceChart'), {{
                    type: 'doughnut',
                    data: {{
                        labels: ['{team1}', '{team2}'],
                        datasets: [{{
                            data: [total1, total2],
                            backgroundColor: [
                                'rgba(102, 126, 234, 0.8)',
                                'rgba(118, 75, 162, 0.8)'
                            ],
                            borderColor: [
                                'rgba(102, 126, 234, 1)',
                                'rgba(118, 75, 162, 1)'
                            ],
                            borderWidth: 3,
                            hoverOffset: 4
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{
                                position: 'bottom',
                                labels: {{
                                    font: {{
                                        size: 14,
                                        weight: 'bold'
                                    }},
                                    padding: 20
                                }}
                            }},
                            title: {{
                                display: true,
                                text: 'Répartition des Performances',
                                font: {{
                                    size: 18,
                                    weight: 'bold'
                                }}
                            }}
                        }},
                        animation: {{
                            duration: 2000,
                            easing: 'easeInOutQuart'
                        }}
                    }}
                }});
                
                // Animation au scroll
                const observerOptions = {{
                    threshold: 0.1,
                    rootMargin: '0px 0px -50px 0px'
                }};
                
                const observer = new IntersectionObserver(function(entries) {{
                    entries.forEach(entry => {{
                        if (entry.isIntersecting) {{
                            entry.target.style.opacity = '1';
                            entry.target.style.transform = 'translateY(0)';
                        }}
                    }});
                }}, observerOptions);
                
                document.querySelectorAll('.chart-container').forEach(el => {{
                    el.style.opacity = '0';
                    el.style.transform = 'translateY(30px)';
                    el.style.transition = 'all 0.6s ease';
                    observer.observe(el);
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
        
        /* Responsive amélioré pour mobile et PC */
        @media (max-width: 768px) {
            .container { 
                padding: 15px; 
                margin: 5px; 
                border-radius: 15px;
            }
            
            h2 { 
                font-size: 1.8em; 
                margin-bottom: 20px;
            }
            
            .filters-container {
                padding: 20px;
                margin-bottom: 20px;
            }
            
            form { 
                flex-direction: column; 
                gap: 10px;
            }
            
            select {
                width: 100%;
                margin: 5px 0;
            }
            
            .stats-grid { 
                grid-template-columns: 1fr; 
                gap: 15px;
                margin-bottom: 20px;
            }
            
            .stat-card {
                padding: 15px;
            }
            
            .table-container { 
                overflow-x: auto; 
                margin-bottom: 20px;
                border-radius: 15px;
            }
            
            /* Transformation du tableau pour mobile */
            table { 
                min-width: 100%;
                border-collapse: collapse;
            }
            
            thead { display: none; }
            
            tbody { display: block; }
            
            tr { 
                display: block;
                margin-bottom: 15px; 
                background: white; 
                border-radius: 15px; 
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                padding: 15px;
                border: 1px solid #eee;
            }
            
            td { 
                display: block;
                border: none; 
                border-bottom: 1px solid #f0f0f0; 
                position: relative; 
                padding: 12px 15px 12px 120px; 
                min-height: 50px; 
                font-size: 14px; 
                text-align: left;
            }
            
            td:last-child {
                border-bottom: none;
                padding: 15px;
                text-align: center;
            }
            
            td:before { 
                position: absolute; 
                top: 50%;
                left: 15px; 
                width: 100px; 
                white-space: nowrap; 
                font-weight: bold; 
                color: #667eea;
                transform: translateY(-50%);
                font-size: 12px;
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
            
            .details-btn {
                width: 100%;
                padding: 15px;
                font-size: 16px;
                margin: 10px 0;
            }
            
            .pagination {
                margin: 20px 0;
            }
            
            .pagination button {
                padding: 12px 20px;
                font-size: 14px;
                margin: 5px;
            }
            
            .contact-box {
                padding: 20px;
                font-size: 16px;
                margin: 20px auto;
            }
            
            .contact-box a {
                font-size: 18px;
            }
        }
        
        /* Optimisations pour tablettes */
        @media (min-width: 769px) and (max-width: 1024px) {
            .container {
                max-width: 95%;
                padding: 25px;
            }
            
            .table-container {
                overflow-x: auto;
            }
            
            table {
                min-width: 800px;
            }
            
            .details-btn {
                padding: 8px 15px;
                font-size: 14px;
            }
        }
        
        /* Optimisations pour PC */
        @media (min-width: 1025px) {
            .container {
                max-width: 1400px;
            }
            
            .table-container {
                overflow: visible;
            }
            
            .details-btn {
                padding: 10px 20px;
                font-size: 16px;
                white-space: nowrap;
            }
            
            /* Assurer que le bouton détails est toujours visible */
            td:last-child {
                min-width: 120px;
                text-align: center;
            }
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

def calculate_percentage(s1, s2):
    """Calcule le pourcentage pour la barre de progression"""
    try:
        val1 = float(s1) if str(s1).replace('.', '', 1).isdigit() else 0
        val2 = float(s2) if str(s2).replace('.', '', 1).isdigit() else 0
        total = val1 + val2
        if total == 0:
            return 50  # 50% par défaut si pas de données
        percentage = (val1 / total) * 100
        return max(10, min(90, percentage))  # Limite entre 10% et 90%
    except:
        return 50

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
