import requests
import json
import os

# Fonction pour charger le fichier JSON local
def charger_donnees_json(fichier):
    with open(fichier, 'r', encoding='utf-8') as f:
        return json.load(f)

def charger_donnees_json_depuis_api(country_code=96, count=50):
    url = f"https://1xbet.com/LiveFeed/Get1x2_VZip?sports=85&count={count}&lng=fr&gr=70&mode=4&country={country_code}&getEmpty=true"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print("❌ Erreur lors de la récupération des données depuis l'API :", e)
        return None

# Fonction de prédiction fiable basée sur les cotes 1X2
def prediction_fiable(match):
    cotes = { '1': None, 'N': None, '2': None }
    for e in match.get('E', []):
        if e.get('G') == 1:
            if e.get('T') == 1:
                cotes['1'] = e.get('C')
            elif e.get('T') == 2:
                cotes['N'] = e.get('C')
            elif e.get('T') == 3:
                cotes['2'] = e.get('C')
    prediction = min((v, k) for k, v in cotes.items() if v is not None)[1] if any(cotes.values()) else None
    return prediction, cotes

# Affichage des résultats filtrés et prédits
def afficher_resultats_par_pays(pays, country_code=96, count=50):
    data = charger_donnees_json_depuis_api(country_code, count)
    if not data or not data.get('Success'):
        print("❌ Impossible de récupérer les données depuis l'API.")
        return
    matchs = data.get('Value', [])
    print("\n═════════════════════════════════════════════════════════")
    print("         🔮 Prédictions de SOLITAIRE HACK 🔮")
    print("      Télégram : @Roidesombres225")
    print("      Canal : https://t.me/SOLITAIREHACK")
    print("═════════════════════════════════════════════════════════\n")
    trouve = False
    for match in matchs:
        if pays.lower() in match.get('CN', '').lower() or pays.lower() in match.get('CE', '').lower():
            equipe1 = match.get('O1', 'Inconnu')
            equipe2 = match.get('O2', 'Inconnu')
            ligue = match.get('LE', match.get('L', ''))
            date = match.get('S', '-')
            prediction, cotes = prediction_fiable(match)
            if prediction == '1':
                resultat = f"Victoire probable : {equipe1} ⭐"
            elif prediction == '2':
                resultat = f"Victoire probable : {equipe2} ⭐"
            elif prediction == 'N':
                resultat = "Match nul probable ⚖️"
            else:
                resultat = "Prédiction indisponible"
            print(f"🏆 {ligue}\n{equipe1} vs {equipe2}\nDate (timestamp) : {date}\n{resultat}\nCotes : {cotes}\n{'-'*40}")
            trouve = True
    if not trouve:
        print(f"Aucun match trouvé pour le pays : {pays}")
    print("\n═════════════════════════════════════════════════════════\n")
    print("Créateur : SOLITAIRE HACK | Télégram : @Roidesombres225 | Canal : https://t.me/SOLITAIREHACK")

if __name__ == "__main__":
    pays = input("Entrez le nom du pays : ")
    # Tu peux changer le code pays ici si besoin (96 = France, 225 = Monde, etc.)
    afficher_resultats_par_pays(pays, country_code=225)
