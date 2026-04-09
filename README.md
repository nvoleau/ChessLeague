# Lichess Tournament Manager

Application web statique pour gérer des tournois d'échecs sur Lichess.
Hébergée sur GitHub Pages, 100% gratuite.

---

## Architecture

```
ChessLeague/
├── index.html                  → site web (dashboard joueurs + interface admin)
├── data/
│   └── tournaments.json        → base de données (fichier texte dans le repo)
├── scripts/
│   └── check_games.py          → script qui détecte les parties jouées
└── .github/workflows/
    └── check_games.yml         → automatisation toutes les 30 minutes
```

---

## Configuration — à faire une seule fois

### Étape 1 — Créer le repo GitHub

1. Aller sur **github.com → New repository**
2. Nom : `chess-league` (ou ce que vous voulez), visibilité **Public**
3. Laisser vide (ne pas initialiser avec README)
4. Cliquer **Create repository**

Puis pousser ce code dedans :
```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/VOTRE_PSEUDO/chess-league.git
git push -u origin main
```

---

### Étape 2 — Activer GitHub Pages

1. Dans votre repo → onglet **Settings**
2. Menu gauche → **Pages**
3. Source : **Deploy from a branch**
4. Branch : `main` / `/ (root)`
5. Cliquer **Save**

Votre site sera disponible à l'adresse :
`https://VOTRE_PSEUDO.github.io/chess-league/`

---

### Étape 3 — Token Lichess (pour le scanner automatique)

Ce token permet au script Python de lire les parties jouées sur Lichess.

1. Aller sur **https://lichess.org/account/oauth/token**
2. Cliquer **New personal API token**
3. Description : `chess-league-scanner`
4. Permissions à cocher : **uniquement** `game:read`
5. Cliquer **Create** → copier le token affiché (commence par `lip_...`)

Puis l'ajouter dans GitHub :

1. Votre repo → **Settings**
2. Menu gauche → **Secrets and variables → Actions**
3. Bouton **New repository secret**
4. Nom : `LICHESS_TOKEN`
5. Valeur : coller votre token Lichess
6. Cliquer **Add secret**

> ✅ Ce token est bien stocké dans les Secrets GitHub — il est chiffré,
> jamais visible, et utilisé uniquement par le script automatique.

---

### Étape 4 — Token GitHub (pour sauvegarder depuis l'interface admin)

Ce token permet à l'interface web de committer directement dans votre repo
quand vous créez un tournoi, ajoutez une ronde, etc.

> ⚠️ **Pourquoi ce token ne peut pas être dans les Secrets GitHub ?**
> Les Secrets GitHub ne sont accessibles que par les scripts GitHub Actions
> (côté serveur). L'interface web tourne dans votre navigateur (côté client),
> elle n'a pas accès aux secrets. Ce token est donc stocké uniquement dans
> le `localStorage` de votre navigateur — il ne quitte jamais votre appareil
> (sauf pour appeler l'API GitHub directement, comme n'importe quelle appli web).

**Créer le token :**

1. Aller sur **https://github.com/settings/tokens/new**
2. Note : `chess-league-admin`
3. Expiration : `No expiration` (ou 1 an)
4. Scopes à cocher : **`public_repo`** (si repo public) ou **`repo`** (si repo privé)
5. Cliquer **Generate token** → copier le token (commence par `ghp_...`)

**Configurer dans l'interface :**

1. Ouvrir votre site `https://VOTRE_PSEUDO.github.io/chess-league/`
2. Onglet **Admin** → mot de passe par défaut : `chess2024`
3. Section **Synchronisation GitHub** :
   - Propriétaire du repo : `VOTRE_PSEUDO`
   - Nom du repo : `chess-league`
   - Personal Access Token : coller votre token `ghp_...`
4. Cliquer **Enregistrer et tester**
5. Si vous voyez "✓ Connexion GitHub réussie" — c'est bon !

À partir de là, chaque action admin (créer un tournoi, ajouter une ronde...)
committera automatiquement dans le repo. Les joueurs voient les changements
en quelques secondes.

---

## Utilisation au quotidien

### Créer un tournoi

1. Admin → **Créer un tournoi**
2. Remplir : nom, cadence (`10+5`, `3+2`...), liste des pseudos Lichess, nombre de rondes
3. Cliquer **Générer le tournoi**
4. Les appariements sont créés automatiquement avec tirage aléatoire des couleurs

### Ce que voient les joueurs

- **Dashboard** : liste des matchs de la ronde en cours, avec statut (en attente / jouée)
- Boutons **Jouer Blancs / Jouer Noirs** : ouvrent directement Lichess avec le bon adversaire,
  la bonne cadence et la bonne couleur
- **Classement** : tableau des scores mis à jour en temps réel

### Comment les résultats sont détectés

Le script Python `check_games.py` tourne **toutes les 30 minutes** via GitHub Actions.
Il interroge l'API Lichess pour chaque match "en attente" et vérifie si une partie
a été jouée entre les deux joueurs depuis la création de la ronde.

Si une partie est trouvée :
- Le résultat (`1-0`, `0-1`, `0.5-0.5`) est enregistré
- Le lien vers la partie Lichess est ajouté
- Le classement est recalculé
- Le fichier `tournaments.json` est commité automatiquement

Vous pouvez aussi déclencher le scan manuellement :
**repo → onglet Actions → "Check Lichess Games" → Run workflow**

---

## Résumé des deux tokens

| Token | Où le stocker | À quoi il sert |
|---|---|---|
| `LICHESS_TOKEN` | GitHub Secrets (Settings → Actions) | Script Python qui lit l'API Lichess |
| GitHub PAT (`ghp_...`) | Interface Admin → Synchronisation GitHub | Écriture dans le repo depuis le navigateur |

---

## Changer le mot de passe admin

Admin → **Configuration** → entrer le nouveau mot de passe → Sauvegarder

Le mot de passe par défaut est `chess2024`.
