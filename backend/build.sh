#!/usr/bin/env bash
# exit on error
set -o errexit

# Installation de libsndfile pour soundfile / resemblyzer
apt-get update && apt-get install -y libsndfile1

# Installation de PyTorch version CPU (allégée pour Render)
pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Installation des autres dépendances Python
pip install -r requirements.txt
