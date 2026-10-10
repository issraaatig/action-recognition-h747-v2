# Décisions techniques

## D1 — Fréquence du Cortex-M7 : 400 MHz (et non 480 MHz)
- Sur la STM32H747I-DISCO, le régulateur interne est alimenté en mode **SMPS direct** (câblage de la carte).
- En SMPS direct, le mode de tension **VOS0** (nécessaire pour 480 MHz) n'est pas autorisé → maximum **VOS1 = 400 MHz**.
- Les exemples ST pour cette carte tournent à 400 MHz (M7) / 200 MHz (M4, bus AXI/AHB).
- À vérifier : RM0399 (section *Power control*, tableau des combinaisons d'alimentation) et UM2411.
- Conséquence : toutes les latences du projet sont mesurées à 400 MHz.

## D2 — Python 3.11 pour la partie PC
- Python 3.10 n'est pas installé sur la machine ; 3.11 est compatible avec TensorFlow 2.15 et les outils ST.

## D3 — Ordre de travail : modèles d'abord, firmware ensuite
- On réalise d'abord la partie PC : données → TinyPose → TCN → `.tflite` int8.
- Exception : dès qu'une architecture TinyPose est construite (même non entraînée), on la passe dans X-CUBE-AI « Analyze »
  pour vérifier flash/RAM/MACC **avant** de lancer un entraînement long.
- Le bring-up de la carte (phase 0) se fera au moment d'intégrer le premier modèle.

## D4 — Données JHMDB (résultat de pc/01_prepare_jhmdb.py, split 1)
- 21 classes, 928 clips (train 660 / test 268), 31 838 frames annotées, toutes en 320×240.
- Format vérifié : `pos_img` = (2, 15, T) en pixels → transposé en (T, 15, 2). Ordre des joints conforme au README.
- 3 clips ont un nombre d'images ≠ nombre de frames de joints (2 clap, 1 stand) → exclus (`valid=false`).
- 14,2 % des joints sont hors de l'image (joints « neutres » non annotés, pas de flag de visibilité) :
  ils seront ignorés dans la perte de TinyPose (heatmap cible à zéro + masque).
- TinyPose est entraîné sur les 21 classes ; la sélection 5 classes + other ne concerne que le TCN.

## D5 — Choix de la variante TinyPose (après benchmark X-CUBE-AI, voir results.md)
- Toutes les variantes α≤0.5 tiennent largement (poids < 200 Ko, RAM < 290 Ko).
- F (α=0.75) dépasse le budget activations (406 Ko > 400 Ko) → écartée.
- Candidates à entraîner : **A_hm128** (référence) et **E_hm128_a050** (plus précise, même RAM, +50 % MACC).
  Choix final selon précision PCK sur le split test et latence mesurée sur la carte.

## D6 — Ajout du « root motion » (32 features au lieu de 30)
- Avec l'origine sur `belly`, le déplacement global du corps disparaît (saut = tout le corps monte).
- Ajout de 2 features : déplacement du belly depuis la frame précédente, divisé par l'échelle.
- Gain mesuré sur squelettes parfaits : TCN +3 à +10 points, GRU +6 points ; confusion sit/stand réduite.
- Conséquence firmware : le buffer est 16×32 et la normalisation C doit garder le belly précédent.

## D7 — Fenêtres temporelles
- Clips JHMDB courts (~34 frames) : un pas de 4 (8 FPS) donnerait des fenêtres de 61 frames → impossible.
- Entraînement avec pas aléatoire ∈ {1, 2, 3} (robuste au FPS), évaluation au pas 2. Fenêtre plus longue que le clip :
  la première frame est répétée (comme un buffer qui se remplit au démarrage).
- À revoir quand le FPS réel de la carte sera mesuré.

## D8 — Export du modèle temporel
- TCN : `.tflite` int8 (entrée/sortie float, calcul int8) et float32. Les deux passent dans X-CUBE-AI 9.0.
  Le TCN fait 25 Ko en float : la version float est un choix raisonnable (pas de perte de quantification).
- GRU : X-CUBE-AI 9.0 refuse le GRU déroulé en `.tflite` (`Invalid size_splits [32 32 -1]`) → export `.h5` Keras.
