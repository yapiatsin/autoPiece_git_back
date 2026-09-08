# syntax=docker/dockerfile:1.7

###############################################################################
# Etape 1 : construction des dependances Python dans un venv isole            #
###############################################################################
FROM python:3.13-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# pycairo / rlPyCairo compilent depuis les sources : ils exigent cairo + pkg-config.
# lxml et reportlab prennent des roues pre-compilees, build-essential ne sert que
# de filet de securite si une roue manque pour cette version de Python.
RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        pkg-config \
        libcairo2-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt


###############################################################################
# Etape 2 : image d'execution, sans chaine de compilation                     #
###############################################################################
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=magazin_piece.settings \
    PATH="/opt/venv/bin:$PATH"

# libcairo2 : rendu PDF (xhtml2pdf / svglib). fonts-dejavu-core : polices des recus.
# libgettextpo / gettext : compilation des catalogues de traduction .po -> .mo.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libcairo2 \
        fonts-dejavu-core \
        gettext \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

# Utilisateur non privilegie : un conteneur web ne doit jamais tourner en root.
RUN useradd --create-home --uid 1000 autopiece
WORKDIR /app

COPY --chown=autopiece:autopiece . /app

# Points de montage des donnees mutables (volumes en production).
RUN mkdir -p /app/staticfiles /app/media \
    && chown -R autopiece:autopiece /app/staticfiles /app/media \
    && chmod +x /app/docker/entrypoint.sh

USER autopiece

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz/ || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "magazin_piece.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--threads", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
