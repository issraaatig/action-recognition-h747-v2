# Reconnaissance d'actions humaines sur STM32H747I-DISCO

Caméra → **TinyPose** (pose 2D, 15 joints) → normalisation → buffer 16 frames → **TCN** → action
(JUMP, CLAP, WAVE, SIT, STAND, other), le tout en temps réel sur le Cortex-M7.

Contexte complet, architecture et règles du projet : [CLAUDE.md](CLAUDE.md).
Choix techniques : [docs/decisions.md](docs/decisions.md) · Résultats : [docs/results.md](docs/results.md).

## Installation (Windows, Git Bash)

```bash
py -3.11 -m venv pc/.venv
source pc/.venv/Scripts/activate
pip install -r pc/requirements.txt
```

## Données JHMDB (non versionnées)

```bash
curl -L -o pc/data/joint_positions.zip https://files.is.tue.mpg.de/jhmdb/joint_positions.zip
curl -L -o pc/data/splits.zip          https://files.is.tue.mpg.de/jhmdb/splits.zip
cd pc/data && unzip -q joint_positions.zip && unzip -q splits.zip && cd ../..
# Images : extraire JHMDB/Frames depuis JHMDB.tar.gz (version "détection", 4,5 Go)
tar -xzf JHMDB.tar.gz -C pc/data JHMDB/Frames JHMDB/JHMDB-GT.pkl
```

## Pipeline PC

| Étape | Commande | Sortie |
|---|---|---|
| 1. Indexer + vérifier les données | `python pc/01_prepare_jhmdb.py` | `pc/data/jhmdb_index.json`, `pc/data/check_joints/` |
| 2. Variantes TinyPose + benchmark | `python pc/02_build_tinypose.py` puis `stedgeai analyze` | `pc/models/bench/` |
