# Analyse-Nhl

[![GitHub stars](https://img.shields.io/github/stars/MilanM-V/Analyse-Nhl?style=social)](https://github.com/MilanM-V/Analyse-Nhl)

**Analyse-Nhl** est un bot de pari sur la LNH qui prédit les buteurs, calcule les scores QS et récupère les cotes en temps réel. Il combine des modèles de machine‑learning (XGBoost, scikit‑learn) avec les données officielles de l’API NHL et les cotes des bookmakers, pour envoyer des notifications automatisées sur Telegram et proposer un tableau de bord interactif avec Streamlit.

---

## Fonctionnalités

- **Moteur prédictif** : Score QS v10 avec des seuils calibrés (ELITE ≥ 10.5, SAFE ≥ 9.5, JOUABLE ≥ 7.5).
- **Scraping des cotes en direct** : Scraper asynchrone pour Flashscore et BettingPros utilisant Selenium (Brave) et aiohttp.
- **Tableau de bord dynamique** : Interface Streamlit avec courbes de profit filtrables par période et filtres joueurs.
- **Rapports Telegram** : Notifications par match, incluant un message lorsqu’aucun joueur ne passe les filtres.
- **Pipeline de données robuste** : Ingestion asynchrone, back‑testing et ré‑entraînement automatisé du modèle.

---

## Installation

```bash
# Cloner le dépôt
git clone https://github.com/MilanM-V/Analyse-Nhl.git
cd Analyse-Nhl

# Créer un environnement virtuel (recommandé)
python -m venv venv
# Sous Windows
venv\Scripts\activate
# Sous macOS / Linux
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

> **Note** : Le projet nécessite Python 3.12 et le navigateur Brave pour Selenium.

---

## Utilisation

```bash
# Lancer le tableau de bord Streamlit
streamlit run dashboard.py
```

Le tableau de bord sera accessible à l’adresse `http://localhost:8501`. Utilisez la barre latérale pour choisir la période (7 jours, 30 jours, saison en cours) et visualiser les courbes de profit en temps réel.

Pour démarrer le bot complet :

```bash
python main_bot.py   # lance le pipeline complet (scraping, prédiction, alertes Telegram)
```

---

## Contribuer

Les contributions sont les bienvenues ! Voici comment procéder :

1. Forker le dépôt.
2. Créer une branche de fonctionnalité (`git checkout -b feature/ma-super-fonction`).
3. Vérifier que tous les tests passent (`pytest`).
4. Soumettre une pull request avec une description claire des changements.

---

## Licence

Ce projet est sous licence MIT – voir le fichier [LICENSE](LICENSE) pour plus de détails.

---

## Remerciements

- API NHL pour les données officielles.
- Flashscore & BettingPros pour les cotes.
- Scikit‑learn & XGBoost pour les modèles de machine‑learning.
- Streamlit pour le tableau de bord interactif.
