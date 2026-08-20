#################MAGASIN_PIECE#################

DESCRIPTION & DEPENDANCES

DESCRIPTION
Ce dépot contient le code source de magasin piece 

DEPENDANCES
Voir le fichier requierements.txt à la racine du projet
> Python version >=3.10
> django version >=5.0.6
> djangorestframework >= 3.15.2

DEMARRER :
#Cloner le projet

git clone ...

Aller à la racine du projet et Installer les dependances dans le requirements.txt avec :

pip install -r requirements.txt


Activate the environment using source

DEPLOIEMENT


configuration des hosts
> Se rendre dans le fichier .env

configuration de la bd

Se rendre dans le fichier .env
NOMMEE ET RENSEIGNER LES VARIBALES DE CONNEXION DE LA BD.
Ces vaiables sont :

DATABASE_NAME
DATABASE_USERNAME
DATABASE_PASSWORD
HOST
PORT

LES MIGRATIONS DES TABLES DANS LA BD
> python3 manage.py makemigrations
> python3 manage.py migrate
CREATION D'ACCES  : saisir la commande suivante dans le terminal et renseigner les informations demandées

python3 manage.py runserver
