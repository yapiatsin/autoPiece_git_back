###############################################################################
# Auto-Piece — pilotage de la stack Docker
#
#   Sur le VPS :  cd /opt/autopiece && make deploy
#   Aide       :  make            (ou make help)
#
# Memes noms de cibles que le Makefile d'E-Printer Web, pour ne pas avoir a
# changer d'habitudes entre les deux projets. Difference notable : Caddy
# n'appartient pas a cette pile, il est partage avec eprinters — les cibles
# caddy-* agissent donc sur le conteneur eprinters_caddy.
###############################################################################

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE_FILE ?= docker-compose.yml
COMPOSE      := docker compose -f $(COMPOSE_FILE)
WEB          := autopiece-web
DB           := autopiece-db
DJANGO       := $(COMPOSE) exec -T $(WEB) python manage.py
CADDY        ?= eprinters_caddy
HEALTH_URL   ?= http://127.0.0.1:8010/healthz/

.PHONY: help up down restart reload status ps logs logs-web logs-db \
		rebuild rebuild-local pull build deploy \
		connect-web connect-db shell dbshell \
		migrate makemigrations collectstatic superuser check health \
		backup restore import-data fix-perms \
		caddy-validate caddy-reload caddy-logs \
		prune env-check

# =============================================================================
# AIDE
# =============================================================================
help: ## Affiche cette aide
	@echo ""
	@echo "  Auto-Piece — commandes disponibles"
	@echo "  ────────────────────────────────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

# =============================================================================
# DÉPLOIEMENT
# =============================================================================
deploy: ## ⭐ Déploiement complet : git pull + rebuild
	git pull --ff-only
	@$(MAKE) --no-print-directory rebuild

rebuild: ## Récupère la dernière image GHCR et redémarre la stack
	@echo "==> Récupération de la dernière image depuis GHCR..."
	$(COMPOSE) pull $(WEB)
	@echo "==> Recréation des conteneurs..."
	$(COMPOSE) up -d --force-recreate --remove-orphans
	@echo "==> Nettoyage des images obsolètes..."
	-docker image prune -f
	@$(MAKE) --no-print-directory health

rebuild-local: ## Déploiement de secours : build de l'image sur le VPS
	@echo "==> Build local de l'image (3 à 6 minutes)..."
	$(COMPOSE) build --pull $(WEB)
	$(COMPOSE) up -d --force-recreate --remove-orphans
	-docker image prune -f
	@$(MAKE) --no-print-directory health

pull: ## Récupère les images sans redémarrer
	$(COMPOSE) pull

build: ## Construit l'image sans démarrer
	$(COMPOSE) build $(WEB)

# =============================================================================
# CYCLE DE VIE
# =============================================================================
up: ## Démarre la stack (recrée ce dont la config a changé)
	$(COMPOSE) up -d

down: ## Arrête la stack (les volumes sont conservés)
	$(COMPOSE) down

restart: ## Redémarre les conteneurs (NE relit PAS .env — voir 'reload')
	$(COMPOSE) restart

reload: ## Applique les modifications de .env (recrée les conteneurs)
	$(COMPOSE) up -d --force-recreate
	@$(MAKE) --no-print-directory health

status: ## Affiche l'état des conteneurs
	@$(COMPOSE) ps

ps: status ## Alias de status

health: ## Attend que l'application réponde et affiche l'état
	@echo "==> Attente de la sonde applicative..."
	@curl -s --retry 40 --retry-delay 3 --retry-all-errors --retry-connrefused \
		-o /dev/null -w "    healthz [HTTP %{http_code}]\n" $(HEALTH_URL) || true
	@$(COMPOSE) ps

# =============================================================================
# JOURNAUX
# =============================================================================
logs: ## Logs de tous les services (Ctrl-C pour quitter)
	$(COMPOSE) logs -f --tail=100

logs-web: ## Logs de Django uniquement
	$(COMPOSE) logs -f --tail=100 $(WEB)

logs-db: ## Logs de PostgreSQL
	$(COMPOSE) logs -f --tail=100 $(DB)

caddy-logs: ## Logs du reverse proxy (conteneur partagé avec eprinters)
	docker logs -f --tail=100 $(CADDY)

# =============================================================================
# ACCÈS
# =============================================================================
connect-web: ## ⭐ Ouvre un shell dans le conteneur Django
	$(COMPOSE) exec $(WEB) bash

connect-db: ## Ouvre psql dans le conteneur PostgreSQL
	$(COMPOSE) exec $(DB) psql -U $${DB_USER:-autopiece} -d $${DB_NAME:-autopiece}

shell: ## Ouvre le shell Django (python manage.py shell)
	$(COMPOSE) exec $(WEB) python manage.py shell

dbshell: connect-db ## Alias de connect-db

# =============================================================================
# DJANGO
# =============================================================================
migrate: ## Applique les migrations
	$(DJANGO) migrate

makemigrations: ## Génère les migrations manquantes (à commiter ensuite)
	$(DJANGO) makemigrations

collectstatic: ## Recollecte les fichiers statiques
	$(DJANGO) collectstatic --noinput

superuser: ## Crée un compte administrateur (interactif)
	$(COMPOSE) exec $(WEB) python manage.py createsuperuser

check: ## Vérifications de configuration en mode production
	$(DJANGO) check --deploy

# =============================================================================
# DONNÉES
# =============================================================================
backup: ## Sauvegarde base + médias dans ./backups
	bash scripts/backup_db.sh

restore: ## Restaure un dump : make restore DUMP=backups/db-....sql.gz
	@test -n "$(DUMP)" || { echo "Usage : make restore DUMP=backups/db-....sql.gz"; exit 1; }
	bash scripts/restore_db.sh $(DUMP)

import-data: ## Écrase la base avec un export : make import-data FILE=data_export.json
	@test -n "$(FILE)" || { echo "Usage : make import-data FILE=data_export.json"; exit 1; }
	$(COMPOSE) cp $(FILE) $(WEB):/tmp/import.json
	$(COMPOSE) exec $(WEB) python scripts/reset_and_load.py /tmp/import.json
	-$(COMPOSE) exec -T --user root $(WEB) rm -f /tmp/import.json

fix-perms: ## Rétablit les droits du dossier media (à faire après tout scp)
	chown -R 1000:1000 media
	@echo "media appartient de nouveau à l'uid 1000 du conteneur."

# =============================================================================
# REVERSE PROXY (conteneur partagé — prudence)
# =============================================================================
caddy-validate: ## Valide la configuration Caddy SANS l'appliquer
	docker exec $(CADDY) caddy validate --config /etc/caddy/Caddyfile

caddy-reload: ## Valide puis recharge Caddy (refuse de recharger si invalide)
	@docker exec $(CADDY) caddy validate --config /etc/caddy/Caddyfile 2>&1 \
		| grep -q "Valid configuration" \
		|| { echo "Configuration Caddy invalide — rechargement annulé."; exit 1; }
	docker exec $(CADDY) caddy reload --config /etc/caddy/Caddyfile
	@echo "Caddy rechargé."

# =============================================================================
# DIVERS
# =============================================================================
env-check: ## Affiche les clés du .env sans révéler les valeurs
	@sed 's/=.*/=<rempli>/' .env | grep -vE '^\s*(#|$$)'

prune: ## Supprime les images Docker orphelines
	docker image prune -f
