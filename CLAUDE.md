# CLAUDE.md — Reconnaissance d'actions humaines sur STM32H747I-DISCO

> Ce fichier donne à Claude Code tout le contexte du projet. Il est lu au début de chaque session.
> Langue de travail : **français** (code et commentaires peuvent être en anglais).

---

## 1. Qui je suis et ce que je veux apprendre

- Étudiant ingénieur en systèmes embarqués (ENET'Com Sfax). Je connais déjà STM32CubeMX et STM32CubeIDE.
- **Mon point faible : le debug bas niveau** (run/debug, ST-LINK, HardFault, registres, mémoire, cache, DMA, timing, hardware).
- **Objectif double** : (1) réaliser le projet, (2) **apprendre le debug** en le réalisant.

### Règles pédagogiques pour Claude Code (IMPORTANT)

1. **Explique avant de coder** : pour chaque étape, dis ce qu'on va faire, pourquoi, et ce qui peut mal tourner.
2. **Côté firmware/hardware, ne corrige pas un bug à ma place sans m'expliquer** :
   donne des hypothèses classées par probabilité, et les étapes de debug pour que **je** trouve la cause
   (breakpoint où ? quel registre lire ? quelle variable surveiller ?).
3. Quand un bug est résolu, ajoute une entrée dans `docs/debug_journal.md`
   (symptôme → hypothèses → méthode de debug → cause réelle → correction → leçon).
4. Côté Python/entraînement, tu peux écrire le code directement, mais commente-le clairement.
5. Avance **par petites étapes testables**. Jamais 500 lignes d'un coup.
6. Ne prétends jamais qu'un code a marché sur la carte : tu ne vois pas la carte. Demande-moi le résultat
   (sortie UART, écran, valeur dans le debugger).

---

## 2. Le projet en une phrase

Une caméra filme une personne ; la carte STM32H747I-DISCO reconnaît en temps réel son action parmi
**JUMP, CLAP, WAVE, SIT, STAND** (+ **other**), en utilisant **deux modèles** :
un modèle de pose (**TinyPose**) puis un modèle temporel (**TCN**, comparé à un GRU).

---

## 3. Architecture

```
Vidéo caméra = suite d'images (frames)
   │
   ▼  (une image à la fois)
[Modèle 1 : TinyPose]  image 128×128×3  →  15 heatmaps 32×32  →  15 points (x, y, score)
   │
   ▼
Normalisation du squelette  →  30 nombres par image
   │
   ▼
Buffer circulaire des 16 dernières images  →  tableau 16 × 30
   │
   ▼
[Modèle 2 : TCN]  16×30  →  6 probabilités (JUMP, CLAP, WAVE, SIT, STAND, other)
   │
   ▼
Lissage (moyenne des 5 dernières prédictions) + seuil (0.6)  →  action affichée
```

### Pourquoi deux modèles
- Une seule image ne suffit pas (SIT et STAND se ressemblent sur une photo ; seul l'ordre temporel les distingue).
- Un modèle vidéo (16 images d'un coup) est trop lourd pour un microcontrôleur.
- Donc : modèle 1 lourd mais **une image à la fois** ; modèle 2 minuscule qui travaille sur **les positions dans le temps**.

### Pourquoi pas MoveNet directement
MoveNet (ST Model Zoo) n'est **pas supporté sur STM32H7** : ~2,3 Mo de poids et ~900 Ko d'activations
(version ST 192×192), conçu pour STM32N6 (NPU). On conçoit donc **TinyPose**, un modèle de pose sur mesure.
MoveNet sert uniquement **sur PC** : (a) benchmark de référence pour le rapport, (b) professeur pour la distillation.

---

## 4. Matériel (à vérifier dans le manuel UM2411 / datasheet si doute)

- **STM32H747I-DISCO** : STM32H747XI, Cortex-M7 + Cortex-M4. **Sur cette carte (SMPS direct) : M7 @ 400 MHz max, M4 @ 200 MHz** (voir docs/decisions.md D1).
- Flash interne 2 Mo ; RAM interne ~1 Mo répartie (DTCM 128 Ko, ITCM 64 Ko, AXI SRAM 512 Ko, SRAM1-3, SRAM4).
- SDRAM externe 32 Mo (FMC), QSPI flash externe.
- Écran DSI 800×480, caméra via connecteur DCMI (module **B-CAMS-OMV**).
- ST-LINK V3 intégré ; port COM virtuel sur **USART1** (pour printf).
- **Pièges connus H7** : cohérence D-Cache/DMA, configuration MPU, dual-core (boot M4, connect under reset).

### Budget cible pour TinyPose (à vérifier par benchmark)
| Ressource | Objectif |
|---|---|
| Poids (flash) | < 1,5 Mo → flash interne |
| Activations (RAM) | < 400 Ko → AXI SRAM |
| Latence | < 150 ms / image (→ ≥ 6 FPS) |

Placement mémoire prévu : poids en flash interne, activations en AXI SRAM, frames caméra en SDRAM,
buffer temporel + modèle 2 en DTCM.

---

## 5. Données : JHMDB

- ~900 clips, 21 actions, frames ~320×240, **15 articulations 2D annotées par frame** (`joint_positions/.../joint_positions.mat`),
  3 splits officiels train/test. **Vérifier le format exact dans le README du dataset avant de coder le loader.**
- Classes gardées : `jump, clap, wave, sit, stand` ; classe `other` = quelques autres classes JHMDB.
- Ordre des 15 joints (à confirmer dans le README) :
  `0 neck, 1 belly, 2 face, 3 R_shoulder, 4 L_shoulder, 5 R_hip, 6 L_hip, 7 R_elbow, 8 L_elbow,
   9 R_knee, 10 L_knee, 11 R_wrist, 12 L_wrist, 13 R_ankle, 14 L_ankle`
- **Toujours utiliser les splits officiels** (séparation par vidéo, pas de fuite entre train et test).
- Attention : `sit` = s'asseoir, `stand` = se lever → ce sont des mouvements inverses.
  **Jamais d'augmentation par inversion temporelle.**
- Augmentations autorisées : miroir horizontal **avec échange gauche/droite des joints**, petite rotation,
  échelle, translation, bruit sur les coordonnées.

---

## 6. Modèle 1 : TinyPose

- Entrée : image RGB 128×128 (variante 96×96 à comparer), uint8/int8.
- Backbone : MobileNetV2 α=0.35 (pré-entraîné ImageNet, Keras), coupé vers stride 16 (8×8).
- Décodeur : 2 suréchantillonnages → 32×32.
- Tête : conv 1×1 → **32×32×15 heatmaps**.
- Vérité terrain : gaussienne (σ ≈ 1–2 pixels de heatmap) centrée sur chaque joint. Perte : MSE.
- Variante à comparer : tête de **régression directe** (30 sorties).
- Distillation optionnelle : MoveNet Thunder sur PC génère des pseudo-labels sur images supplémentaires.
- Post-traitement (écrit en C sur la carte) : argmax par heatmap → (x, y) × 4, score = valeur du pic.
- Export : `.tflite` int8 (quantification post-training avec un jeu de calibration représentatif).
- **Avant d'entraîner** : construire 3–4 variantes et vérifier qu'elles tiennent (X-CUBE-AI « Analyze »
  ou ST Edge AI Developer Cloud, cible STM32H747I-DISCO).

## 7. Pont entre les modèles : normalisation

1. Origine = `belly` (joint 1).
2. Échelle = distance `neck`–`belly` (si ≈ 0 → garder l'échelle précédente, **jamais diviser par zéro**).
3. Joint avec score < 0.3 → reprendre la valeur de la frame précédente.
4. Aplatir → vecteur de 30 floats.
5. Buffer circulaire 16×30 ; **remettre dans l'ordre chronologique** (plus ancien → plus récent) avant le modèle 2.
- **Le code Python et le code C de normalisation doivent être strictement identiques.**

## 8. Modèle 2 : TCN (et GRU pour comparaison)

- Entrée 16×30 → Conv1D(32, k=3) → ReLU → Conv1D(32, k=3, dilation=2) → ReLU → GlobalAvgPool → Dense(6) → Softmax.
- ~6 000 paramètres. GRU(32) → Dense(6) comme comparaison.
- **Entraîné sur les squelettes produits par TinyPose** (pas sur les annotations parfaites), pour avoir le même bruit qu'en déploiement.
- Fenêtres de 16 frames échantillonnées **au FPS réel de la carte** (mesurer d'abord ; ex. 8 FPS → pas de ~4 frames à 30 FPS).
- Le TCN est **généré par X-CUBE-AI** à partir de `model_float32.tflite` (décision D11). Version écrite à la main en C : exercice optionnel, plus tard, validé contre la même sortie Python.

---

## 9. Règle d'or de validation PC ↔ carte

Pour chaque bloc (prétraitement, TinyPose, post-traitement, normalisation, TCN) :
1. Python génère des **vecteurs de test** (entrée + sortie attendue) exportés en `.h` dans `firmware/Core/Inc/test_vectors/`.
2. La carte exécute le bloc sur l'entrée et compare à la sortie attendue ; affiche l'erreur max par UART.
3. On ne passe au bloc suivant que si l'erreur est acceptable.

---

## 10. Arborescence

```
action-recognition-h747/
├── CLAUDE.md
├── docs/
│   ├── debug_journal.md       # journal des bugs (voir règle 3)
│   ├── decisions.md           # choix techniques et résultats de benchmark
│   └── results.md             # précisions, latences, tableaux de comparaison
├── pc/
│   ├── requirements.txt
│   ├── data/                  # JHMDB (non versionné)
│   ├── 01_prepare_jhmdb.py    # sélection classes, splits, lecture des joints
│   ├── 02_build_tinypose.py   # variantes + export pour benchmark
│   ├── 03_train_tinypose.py
│   ├── 04_extract_skeletons.py
│   ├── 05_train_temporal.py   # TCN + GRU
│   ├── 06_export_tflite.py    # quantification int8
│   ├── 07_make_test_vectors.py
│   └── common/normalize.py    # normalisation (référence pour le C)
├── firmware/                  # projet STM32CubeIDE (généré par CubeMX)
└── tools/
    ├── uart_monitor.py        # lecture du port série
    └── frame_dump_viewer.py   # reconstruire une image envoyée par UART
```

---

## 11. Phases et compétences de debug associées

| Phase | Travail | Debug à apprendre |
|---|---|---|
| 0 | Bring-up : horloges 400 MHz, LED, printf USART1 | Chaîne build → ST-LINK → SWD → flash ; breakpoints ; step ; vue registres ; MCO |
| 1 | PC : préparation JHMDB, visualiser les joints sur les frames | Vérification visuelle des données |
| 2 | PC : variantes TinyPose + benchmark | Lecture des rapports X-CUBE-AI (RAM/flash/MACC) |
| 3 | Carte : caméra DCMI+DMA → SDRAM → écran | **Bug cache/DMA**, dump d'une frame vers PC |
| 4 | PC : entraînement TinyPose, export int8 | Comparer float vs int8 |
| 5 | Carte : TinyPose sur image fixe (test vector) | Validation sur cible ; HardFault (CFSR/HFSR/BFAR, PC empilé) ; fichier `.map` |
| 6 | Carte : TinyPose sur flux + squelette dessiné à l'écran | Prétraitement (RGB/BGR, échelle, zero-point) |
| 7 | PC : squelettes JHMDB + TCN/GRU | Matrice de confusion |
| 8 | Carte : normalisation + buffer + TCN en C | Watchpoints ; index hors limites ; division par zéro |
| 9 | Optimisation : placement mémoire, ROI tracking, dual-core M7/M4 | DWT->CYCCNT, toggle GPIO + analyseur logique, HSEM, cache inter-cœurs |
| 10 | Plan B / baseline : Motion History Image + petit CNN | — |

**Phase actuelle : 0** (partie PC terminée — phases 1, 2, 4, 7 — ; on commence le firmware : bring-up de la carte, voir docs/decisions.md D3).

---

## 12. Commandes et environnement (à compléter)

- OS : Windows 11 Pro
- Python : 3.11 (`py -3.11`), dans un venv `pc/.venv`. GPU : aucun (entraînement CPU ou Google Colab). STM32Cube FW_H7 V1.13.0 installé.
- STM32CubeIDE version : 2.1.1  /  STM32CubeMX 6.17  /  X-CUBE-AI version : 10.2.1 (ST Edge AI Core 2.2.0) — voir decisions.md D13
- Packs STM32Cube : `D:\STM32Cube\STM32Cube\Repository` (déplacés de C:, disque plein)
- Port série de la carte : COM3 (115200 8N1) — vérifié dans le Gestionnaire de périphériques (« STLink Virtual COM Port »)