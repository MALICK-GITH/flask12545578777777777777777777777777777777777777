import requests
import csv
import os
import datetime
from app import save_matches_sql

API_URL = "https://1xbet.com/LiveFeed/Get1x2_VZip?sports=85&count=50&lng=fr&gr=70&mode=4&country=96&getEmpty=true"
HISTO_CSV = "historique_matchs.csv"

# Champs à sauvegarder
CSV_FIELDS = [
    "id_match", "equipe1", "score1", "score2", "equipe2", "sport", "ligue", "date_heure", "statut"
]

def detect_sport(league):
    if "foot" in league.lower():
        return "Football"
    if "basket" in league.lower():
        return "Basketball"
    if "tennis" in league.lower():
        return "Tennis"
    return "?"

def fetch_matches():
    r = requests.get(API_URL)
    r.raise_for_status()
    return r.json().get("Value", [])

def load_existing_ids():
    if not os.path.exists(HISTO_CSV):
        return set()
    ids = set()
    with open(HISTO_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ids.add(row["id_match"])
    return ids

def save_matches(matches):
    file_exists = os.path.exists(HISTO_CSV)
    with open(HISTO_CSV, "a", newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        for m in matches:
            writer.writerow(m)

def main():
    try:
        matches = fetch_matches()
        existing_ids = load_existing_ids()
        nouveaux = []
        for match in matches:
            statut = match.get("TN", "")
            if "Terminé" in statut or "Fin" in statut or statut.lower() == "finished":
                id_match = str(match.get("I"))
                if id_match in existing_ids:
                    continue
                team1 = match.get("O1", "–")
                team2 = match.get("O2", "–")
                score1 = match.get("SC", {}).get("FS", {}).get("S1", "–")
                score2 = match.get("SC", {}).get("FS", {}).get("S2", "–")
                league = match.get("LE", "–")
                sport = detect_sport(league)
                match_ts = match.get("S", 0)
                match_time = datetime.datetime.utcfromtimestamp(match_ts).strftime('%d/%m/%Y %H:%M') if match_ts else "–"
                nouveaux.append({
                    "id_match": id_match,
                    "equipe1": team1,
                    "score1": score1,
                    "score2": score2,
                    "equipe2": team2,
                    "sport": sport,
                    "ligue": league,
                    "date_heure": match_time,
                    "statut": statut
                })
        if nouveaux:
            save_matches_sql(nouveaux)
            print(f"{len(nouveaux)} nouveaux matchs terminés sauvegardés.")
        else:
            print("Aucun nouveau match terminé à sauvegarder.")
    except Exception as e:
        print(f"Erreur lors de la sauvegarde automatique : {e}")

if __name__ == "__main__":
    main() 
