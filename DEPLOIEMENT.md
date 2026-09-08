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
   Internet ──443──▶ eprinters_caddy ──▶ autopiece-web:8000 (gunicorn + WhiteNoise)
                     (conteneur, deja                    │
                      en place sur le VPS)               └──▶ autopiece-db (PostgreSQL 16)

  Caddy joint l'application par son nom de conteneur, sur un reseau Docker
  partage : il ne peut pas passer par 127.0.0.1, qui designerait Caddy lui-meme.
```

---

## 1. Fichiers ajoutés

| Fichier | Rôle |
|---|---|
| `Dockerfile` | Image de production en deux étapes (build des dépendances, puis exécution) |
| `docker/entrypoint.sh` | Attente de la base, migrations, `collectstatic`, `compilemessages`, gunicorn |
| `docker-compose.yml` | Pile `autopiece-web` + `autopiece-db`, greffee sur le reseau de Caddy |
| `.dockerignore` | Exclut `env/`, `.env`, `db.sqlite3`, `media/`, `staticfiles/` de l'image |
| `.github/workflows/deploy.yml` | Vérifications, build, push GHCR, déploiement SSH |
| `.env.prod.example` | Modèle de configuration à copier en `.env` sur le VPS |
| `deploy/Caddyfile.example` | Bloc à ajouter à la configuration Caddy existante |
| `scripts/export_local_data.sh` | Exporte la base SQLite locale en JSON |
| `scripts/reset_and_load.py` | Vide la base cible puis y charge l'export |
| `scripts/clean_orphan_fks.py` | Diagnostic des clés étrangères orphelines |
| `scripts/backup_db.sh`, `scripts/restore_db.sh` | Sauvegarde et restauration |
| `Makefile` | Raccourcis d'exploitation (`make deploy`, `make logs-web`, ...) |

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
- Caddy déjà en service. Sur ce VPS il tourne dans le conteneur
  `eprinters_caddy`, qui detient les ports 80/443 et importe
  `/etc/caddy/sites/*.caddy` (dossier hote `/opt/caddy-sites`).

---

## 4. Préparer le VPS

```bash
cd /opt && git clone https://github.com/yapiatsin/autoPiece_git_back.git autopiece && cd autopiece && mkdir -p media backups && chown -R 1000:1000 media && cp .env.prod.example .env
```

Le `chown` n'est pas optionnel : le conteneur tourne en utilisateur non
privilégié `uid 1000`, et un bind mount conserve les permissions de l'hôte.
Sans lui, l'application ne peut pas enregistrer les images téléversées.

Générer une clé secrète **différente de celle du poste de développement** :

```bash
docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Relever le nom du reseau Docker de Caddy, indispensable pour que le proxy
puisse joindre l'application :

```bash
docker inspect eprinters_caddy --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"
"}}{{end}}'
```

Puis éditer `/opt/autopiece/.env` : y reporter cette clé secrète, ce nom de
réseau dans `CADDY_NETWORK`, le domaine réel dans `DJANGO_ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS` et `PUBLIC_BASE_URL`, un mot de passe PostgreSQL solide,
et les identifiants e-mail, Pusher et GeniusPay.

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
cd /opt/autopiece && docker compose cp data_export.json autopiece-web:/tmp/data_export.json && docker compose exec autopiece-web python scripts/reset_and_load.py /tmp/data_export.json
```

Le script vide la base cible, charge l'export, puis relance `migrate` pour
reconstruire les types de contenu et les permissions. Il demande confirmation
avant d'effacer quoi que ce soit.

Vérifier ensuite que les comptes, le catalogue et les commandes sont bien là,
puis supprimer `data_export.json` du VPS.

## 8. Activer le domaine et le HTTPS

Déposer le bloc de site dans le dossier importé par Caddy, en y mettant le
domaine réel :

```bash
cd /opt/autopiece && cp deploy/Caddyfile.example /opt/caddy-sites/10-autopiece.caddy && sed -i 's/autopiece.example.com/LE-DOMAINE-REEL/g' /opt/caddy-sites/10-autopiece.caddy
```

Valider la configuration **avant** de recharger : une erreur de syntaxe ferait
échouer tout le Caddyfile, y compris le site `eprinters` déjà en production.

```bash
docker exec eprinters_caddy caddy validate --config /etc/caddy/Caddyfile
```

Puis seulement :

```bash
docker exec eprinters_caddy caddy reload --config /etc/caddy/Caddyfile
```

Le bloc ne doit contenir aucune section globale entre accolades : les options
globales (adresse ACME, `trusted_proxies`) sont déjà définies dans le Caddyfile
principal, et une seconde ferait échouer le chargement complet.

Une fois le HTTPS confirmé stable, passer `SECURE_HSTS_SECONDS=31536000` dans le
`.env` du VPS et relancer `docker compose up -d autopiece-web`.

---

## 8 bis. Workflow quotidien après une modification

Un `Makefile` reprend les mêmes noms de cibles que celui d'E-Printer Web.
`make` seul affiche la liste complète.

**Tant que les secrets GitHub ne sont pas créés**, l'image est construite sur le
VPS. Depuis le poste de développement :

```bash
git add -A && git commit -m "..." && git push
```

Puis en SSH sur le VPS :

```bash
cd /opt/autopiece && make deploy
```

`make deploy` fait `git pull --ff-only` puis `make rebuild`, qui récupère
l'image depuis GHCR. Tant que GitHub Actions ne publie pas encore d'image,
utiliser à la place :

```bash
cd /opt/autopiece && git pull --ff-only && make rebuild-local
```

**Une fois les secrets créés** (§5), il n'y a plus rien à faire sur le VPS : le
`git push` déclenche le build sur GitHub puis le déploiement par SSH.

Quelques cibles utiles au quotidien :

| Commande | Effet |
|---|---|
| `make status` | état des conteneurs |
| `make logs-web` | journaux Django en continu |
| `make reload` | applique une modification du `.env` |
| `make connect-web` | shell dans le conteneur |
| `make backup` | sauvegarde base + médias |
| `make fix-perms` | rétablit les droits de `media/` après un `scp` |
| `make caddy-reload` | valide **puis** recharge Caddy (refuse si invalide) |

`make restart` ne relit pas le `.env` — c'est `make reload` qu'il faut dans ce
cas, car seul un `up --force-recreate` réinjecte les variables d'environnement.

---

## 9. Exploitation

Journaux applicatifs en continu :

```bash
cd /opt/autopiece && docker compose logs -f autopiece-web
```

Console Django et console PostgreSQL :

```bash
cd /opt/autopiece && docker compose exec autopiece-web python manage.py shell
```

```bash
cd /opt/autopiece && docker compose exec autopiece-db psql -U autopiece -d autopiece
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
cd /opt/autopiece && docker compose up -d autopiece-web
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

**Pas d'underscore dans un nom de service.** Django valide l'en-tête `Host`
avec le motif `^([a-z0-9.-]+|...)(:[0-9]+)?$`, qui exclut les underscores
(RFC 1123). Un service nommé `autopiece_web` fait donc répondre 400 à toute
requête portant ce `Host`, avant même la consultation de `ALLOWED_HOSTS` — la
sonde active de Caddy échoue en permanence et le proxy sert des 502. D'où les
tirets dans `autopiece-web` et `autopiece-db`. Le nom interne doit par ailleurs
figurer dans `DJANGO_ALLOWED_HOSTS`, comme `127.0.0.1` pour le `HEALTHCHECK`
Docker.

**Le fichier `.env` n'est jamais versionné.** Il est créé à la main sur le VPS
et lu par `docker compose` au démarrage. Après l'avoir modifié, relancer
`docker compose up -d autopiece-web` pour que les nouvelles valeurs soient prises en compte.

**`DEBUG` vaut `False` par défaut.** Un `.env` incomplet fait donc échouer le
démarrage plutôt que d'exposer les traces d'erreur en production.
