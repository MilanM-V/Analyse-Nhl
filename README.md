# Analyse-Nhl

[![GitHub stars](https://img.shields.io/github/stars/MilanM-V/Analyse-Nhl?style=social)](https://github.com/MilanM-V/Analyse-Nhl)

**Analyse-Nhl** est un bot de pari sur la LNH qui prédit les buteurs, calcule les scores QS et récupère les cotes en temps réel. Il combine des modèles de machine‑learning (XGBoost, scikit‑learn) avec les données officielles de l’API NHL et les cotes des bookmakers, pour envoyer des notifications automatisées sur Telegram et proposer un tableau de bord interactif avec Streamlit.

---

## Fonctionnalités

- **Moteur prédictif V18.3** : Filtres optimisés sur +2800 joueurs (Buteurs, Passeurs, Pointeurs).
- **Mode Playoff 🏆** : Bascule intelligente entre Saison Régulière et Playoffs avec continuité des statistiques "Last 10".
- **Tracking Avancé** : Suivi séparé du ROI Saison vs Playoff en base de données SQLite.
- **Scraping des cotes en direct** : Intégration Flashscore et BettingPros pour identifier la "Value".
- **Tableau de bord V18** : Interface Streamlit avec filtres par mode, courbes de profit et simulation Kelly Criterion.
- **Alertes Telegram** : Notifications automatiques des meilleurs picks et combinés (Duo Booster, Double Buteur, etc.).

---

## Performances Attendues (Probabilités V18 Optimisées)

Le système V18 a été calibré sur un historique massif pour maximiser le Winrate tout en gardant un ROI positif :

| Marché | Winrate Estimé | ROI Attendu |
| :--- | :--- | :--- |
| **Buteurs** | 44.7% | +43.0% |
| **Passeurs** | 58.5% | +13.6% |
| **Pointeurs** | 69.6% | +4.3% (Simple) / +13.8% (Combo) |

*Note : Les performances en mode Playoff peuvent varier en fonction de l'intensité défensive, mais conservent la même sélectivité de haut niveau.*

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
