#!/usr/bin/env bash
# exit on error
set -o errexit

# Installation de libsndfile pour soundfile / resemblyzer
apt-get update && apt-get install -y libsndfile1 || true

# Installation des dépendances Python
pip install --upgrade pip
pip install -r requirements.txt
