# Déploiement Auto-Pièce — GitHub → Docker → VPS

Chaîne de livraison : un `git push` sur `main` déclenche GitHub Actions, qui
construit l'image Docker, la publie sur GHCR, puis se connecte en SSH au VPS
pour la déployer. Caddy, déjà présent sur le VPS, termine le TLS.

```
  poste de dev ──push──▶ GitHub ──build──▶ ghcr.io/yapiatsin/autopiece_git_back
                            │                          │
                            └────── ssh ───────────────┼──▶ VPS /opt/autopiece
                                                       │     docker compose pull && up -d
                                                       │
   Internet ──443──▶ Caddy ──▶ 127.0.0.1:8010 ──▶ conteneur web (gunicorn)
                       │                                 │
                       └── /static/ et /media/ servis    └──▶ conteneur db (PostgreSQL 16)
                           directement depuis le disque
```

---

## 1. Fichiers ajoutés

| Fichier | Rôle |
|---|---|
| `Dockerfile` | Image de production en deux étapes (build des dépendances, puis exécution) |
| `docker/entrypoint.sh` | Attente de la base, migrations, `collectstatic`, `compilemessages`, gunicorn |
| `docker-compose.yml` | Pile `web` + `db` pour le VPS |
| `.dockerignore` | Exclut `env/`, `.env`, `db.sqlite3`, `media/`, `staticfiles/` de l'image |
| `.github/workflows/deploy.yml` | Vérifications, build, push GHCR, déploiement SSH |
| `.env.prod.example` | Modèle de configuration à copier en `.env` sur le VPS |
| `deploy/Caddyfile.example` | Bloc à ajouter à la configuration Caddy existante |
| `scripts/export_local_data.sh` | Exporte la base SQLite locale en JSON |
| `scripts/reset_and_load.py` | Vide la base cible puis y charge l'export |
| `scripts/clean_orphan_fks.py` | Diagnostic des clés étrangères orphelines |
| `scripts/backup_db.sh`, `scripts/restore_db.sh` | Sauvegarde et restauration |

## 2. Modifications du code applicatif

- **`magazin_piece/settings.py`** — `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`
  et le moteur de base de données (`DB_ENGINE=sqlite|postgresql`) viennent
  désormais du `.env`. Ajout de WhiteNoise, des en-têtes de sécurité, de
  `SECURE_PROXY_SSL_HEADER` pour Caddy et d'une journalisation sur stdout.
- **`magazin_piece/health.py`** et la route `/healthz/` — sonde lue par le
  `HEALTHCHECK` Docker, par Caddy et par le workflow de déploiement.
- **`stock/migrations/0002_categorie_actif.py`** — migration neutralisée. Elle
  ajoutait `Categorie.actif`, champ déjà créé par `0001_initial` ; sur une base
  vierge `migrate` échouait avec `column "actif" ... already exists`. Le fichier
  est conservé sans opération car il est déjà marqué appliqué dans la base
  existante.
- **`Userauths/signals.py`** — le handler `post_save` ignore maintenant
  `raw=True`. Sans ce garde-fou, `loaddata` créait un `ProfilUser` pour chaque
  utilisateur importé, puis échouait sur la contrainte d'unicité en chargeant
  les profils du fichier.
- **`requirements.txt`** — ajout de `gunicorn` et `whitenoise`.
- **`.env` local** — ajout de `DEBUG=True`, `DB_ENGINE=sqlite`,
  `DJANGO_ALLOWED_HOSTS=*`, `SECURE_COOKIES=False` pour que le poste de
  développement conserve son comportement actuel.

## 3. Prérequis

- Un enregistrement DNS `A` pointant le domaine vers l'IP du VPS.
- Docker et le plugin Compose installés sur le VPS (`docker compose version`).
- Caddy déjà en service (le dossier `/opt/caddy-sites` existe).

---

## 4. Préparer le VPS

```bash
cd /opt && git clone https://github.com/yapiatsin/autoPiece_git_back.git autopiece && cd autopiece && mkdir -p media staticfiles backups && cp .env.prod.example .env
```

Générer une clé secrète **différente de celle du poste de développement** :

```bash
docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Puis éditer `/opt/autopiece/.env` : y reporter cette clé, le domaine réel dans
`DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` et `PUBLIC_BASE_URL`, un mot de
passe PostgreSQL solide, et les identifiants e-mail, Pusher et GeniusPay.

## 5. Secrets GitHub

Dépôt → *Settings* → *Secrets and variables* → *Actions* :

| Secret | Valeur |
|---|---|
| `VPS_HOST` | IP ou nom d'hôte du VPS |
| `VPS_USER` | utilisateur SSH (`root`) |
| `VPS_SSH_KEY` | clé privée SSH complète, en-têtes `-----BEGIN ...` compris |
| `VPS_PORT` | port SSH si différent de 22 (facultatif) |
| `VPS_APP_DIR` | `/opt/autopiece` |
| `GHCR_USERNAME` | `yapiatsin` |
| `GHCR_TOKEN` | jeton personnel GitHub avec la portée `read:packages` |

Générer la paire de clés dédiée au déploiement, depuis le poste de développement :

```bash
ssh-keygen -t ed25519 -C "github-actions-autopiece" -f deploy_key -N ""
```

Copier `deploy_key.pub` dans `/root/.ssh/authorized_keys` sur le VPS, et le
contenu de `deploy_key` dans le secret `VPS_SSH_KEY`. Supprimer ensuite les deux
fichiers du poste.

## 6. Premier déploiement

```bash
git add -A && git commit -m "Ajout de l'architecture de deploiement Docker" && git push origin main
```

Suivre l'exécution dans l'onglet *Actions*. Les trois travaux s'enchaînent :
vérifications Django, build et publication de l'image, puis déploiement SSH.

Si le paquet GHCR est privé (cas par défaut), le VPS a besoin de `GHCR_TOKEN`
pour le télécharger. Alternative : rendre le paquet public dans
*Packages* → *Package settings* → *Change visibility*.

Vérifier sur le VPS :

```bash
cd /opt/autopiece && docker compose ps && curl -s http://127.0.0.1:8010/healthz/
```

## 7. Migrer les données existantes

À faire **une seule fois**, après le premier déploiement réussi. Depuis le poste
de développement :

```bash
./scripts/clean_orphan_fks.py
```

```bash
./scripts/export_local_data.sh
```

```bash
scp data_export.json root@<IP_VPS>:/opt/autopiece/ && scp -r media/. root@<IP_VPS>:/opt/autopiece/media/
```

Puis sur le VPS :

```bash
cd /opt/autopiece && docker compose cp data_export.json web:/tmp/data_export.json && docker compose exec web python scripts/reset_and_load.py /tmp/data_export.json
```

Le script vide la base cible, charge l'export, puis relance `migrate` pour
reconstruire les types de contenu et les permissions. Il demande confirmation
avant d'effacer quoi que ce soit.

Vérifier ensuite que les comptes, le catalogue et les commandes sont bien là,
puis supprimer `data_export.json` du VPS.

## 8. Activer le domaine et le HTTPS

Copier `deploy/Caddyfile.example` dans la configuration Caddy du VPS (par
exemple `/opt/caddy-sites/autopiece.caddy`), remplacer `autopiece.example.com`
par le domaine réel, puis recharger Caddy :

```bash
caddy reload --config /etc/caddy/Caddyfile
```

Si Caddy tourne lui-même dans un conteneur, voir la note en fin de
`deploy/Caddyfile.example` : `127.0.0.1` y désigne le conteneur Caddy, pas l'hôte.

Une fois le HTTPS confirmé stable, passer `SECURE_HSTS_SECONDS=31536000` dans le
`.env` du VPS et relancer `docker compose up -d web`.

---

## 9. Exploitation

Journaux applicatifs en continu :

```bash
cd /opt/autopiece && docker compose logs -f web
```

Console Django et console PostgreSQL :

```bash
cd /opt/autopiece && docker compose exec web python manage.py shell
```

```bash
cd /opt/autopiece && docker compose exec db psql -U autopiece -d autopiece
```

**Sauvegardes** — base et médias, avec rotation sur 14 exemplaires :

```bash
cd /opt/autopiece && ./scripts/backup_db.sh
```

Automatisation quotidienne à 2 h, à ajouter dans `crontab -e` :

```
0 2 * * * cd /opt/autopiece && ./scripts/backup_db.sh >> backups/cron.log 2>&1
```

**Restauration** :

```bash
cd /opt/autopiece && ./scripts/restore_db.sh backups/db-20260908-020000.sql.gz
```

**Retour arrière** — chaque image est étiquetée avec le SHA du commit. Remettre
l'ancien SHA dans `WEB_IMAGE` puis :

```bash
cd /opt/autopiece && docker compose up -d web
```

---

## 10. Points d'attention

**Impression thermique USB.** `stock/printer_service.py` pilote l'imprimante
Epson TM-T20III en USB depuis le processus Django. Cela fonctionnait parce que
le serveur tournait sur le poste de caisse ; sur le VPS il n'y a aucun
périphérique USB et `HAS_USB` sera faux. Le code retombe déjà sur la génération
d'un PDF (`stock/receipt_ticket_pdf.py`), que le caissier imprime depuis son
navigateur. Si l'impression directe reste indispensable, il faudra un petit
agent local sur le poste de caisse, appelé par le navigateur — c'est un chantier
à part entière, non couvert ici.

**Collision de `sid`.** `Categorie.cid` et `SousCategorie.sid` utilisent
`ShortUUIDField(length=6, alphabet="abcd1234")`, soit 8⁶ = 262 144 valeurs
possibles. Lors des essais, un `IntegrityError` sur
`stock_souscategorie_sid_key` s'est produit pendant l'insertion des 20
sous-catégories par défaut. Le tirage est bien aléatoire, mais l'espace est
étroit : la probabilité de collision atteint 50 % vers 600 lignes. Allonger le
champ (`length=12`) ou élargir l'alphabet supprimerait ce risque ; cela demande
une migration et n'a pas été fait ici pour rester dans le périmètre du
déploiement.

**Le fichier `.env` n'est jamais versionné.** Il est créé à la main sur le VPS
et lu par `docker compose` au démarrage. Après l'avoir modifié, relancer
`docker compose up -d web` pour que les nouvelles valeurs soient prises en compte.

**`DEBUG` vaut `False` par défaut.** Un `.env` incomplet fait donc échouer le
démarrage plutôt que d'exposer les traces d'erreur en production.
