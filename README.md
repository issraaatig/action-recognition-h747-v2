# Reconnaissance d'actions humaines sur STM32H747I-DISCO

Caméra → **TinyPose** (pose 2D, 15 joints) → normalisation → buffer 8 images → **TCN** → action,
le tout en temps réel sur le Cortex-M7.

## Classes du modèle (version finale)

| Classe | Signification |
|---|---|
| **WAVE** | faire signe de la main (un bras levé, va-et-vient) |
| **SIT** | s'asseoir |
| **other** | tout le reste, dont la personne debout immobile |

Les classes **JUMP**, **CLAP** et **STAND** du cahier des charges ont été testées puis retirées :
CLAP se confond avec WAVE (poignets mal détectés), STAND se confond avec SIT (même geste, sens inverse),
et JUMP n'est pas reconnu de façon fiable (la normalisation efface le mouvement vertical du corps).
Les détails et les mesures sont dans [docs/decisions.md](docs/decisions.md) (D17, D18).

Rapport complet : [docs/rapport.md](docs/rapport.md) · Résultats : [docs/results.md](docs/results.md) ·
Figures : [docs/figures/](docs/figures/).

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
| 3. Entraîner TinyPose | `python pc/03_train_tinypose.py --variant A_hm128 --epochs 30` | `pc/models/tinypose/A_hm128/best.keras` |
| 4. Quantifier int8 | `python pc/06_export_tflite.py --variant A_hm128` | `tinypose_int8.tflite` (PCK float vs int8) |
| 5a. Extraire les squelettes | `python pc/04_extract_skeletons.py --variant A_hm128` (`--gt` : annotations) | `pc/data/skeletons_*.npz` |
| 5b. TCN (modèle final) | `python pc/05_train_temporal.py --model tcn --window 8 --steps 4 5 6 --test-step 5 --noisy 1` | `pc/models/temporal/A_hm128_tcn_noisy_w8_board/` |
| 5c. Validation croisée sur la carte | `python pc/08_cv_board.py --classes wave sit other` | `pc/models/temporal/cv_board_*.json` |
| 6. Vecteurs de test | `python pc/07_make_test_vectors.py --pose A_hm128 --temporal A_hm128_tcn_noisy_w8_board` | `firmware/firmware/CM7/Core/Inc/test_vectors/*.h` |

## Blocs C validés sur PC

```bash
gcc -O2 -Wall -Ifirmware/firmware/CM7/Core/Inc -Ifirmware/firmware/CM7/Core/Inc/test_vectors firmware/host_tests/test_blocks.c firmware/firmware/CM7/Core/Src/pose_postproc.c firmware/firmware/CM7/Core/Src/skeleton_norm.c firmware/firmware/CM7/Core/Src/temporal_buffer.c -lm -o firmware/host_tests/test_blocks.exe
./firmware/host_tests/test_blocks.exe
```

## Déploiement sur la carte
Voir [docs/deploiement_x-cube-ai.md](docs/deploiement_x-cube-ai.md) : les deux réseaux dans X-CUBE-AI, appel des API, ordre de validation.
