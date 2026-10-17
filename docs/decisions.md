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

## D9 — Le goulot d'étranglement est la qualité de TinyPose, pas le TCN
- Sur squelettes TinyPose, toutes les variantes temporelles plafonnent à ~0.50 (clip) contre 0.80 sur annotations.
- Un TCN entraîné sur annotations parfaites tombe aussi à 0.51 sur squelettes TinyPose → le modèle temporel n'est pas en cause.
- Testé sans gain : bruit d'entraînement artificiel, lissage temporel (0.5 / 0.7), root motion.
- Pistes, par ordre de gain attendu : (1) TinyPose plus précis (variante E α=0.5, plus d'epochs, distillation MoveNet) ;
  (2) cross-fitting (squelettes d'entraînement extraits par un TinyPose qui ne les a jamais vus) ;
  (3) conditions de démo plus faciles que JHMDB (une personne, face caméra, bonne lumière) → mesurer sur la carte.
- Modèle temporel retenu pour l'instant : **TCN 30 features** (spec CLAUDE.md, meilleur score mesuré, différences dans le bruit ±5 pts).

## D10 — On garde TinyPose A pour le déploiement (pour l'instant)
- E est meilleur en float (+3 points PCK) mais perd 2,8 points à la quantification int8 (A : 0,6) → en int8 : 0.763 vs 0.755.
- Le gain d'action est dans le bruit (0.50–0.53 au clip) pour +50 % de calcul.
- Piste pour récupérer l'avantage de E : quantization-aware training (QAT) au lieu de la quantification post-entraînement.

## D11 — Les deux modèles passent par X-CUBE-AI
- TinyPose : `pc/models/tinypose/A_hm128/tinypose_int8.tflite` (int8) → réseau X-CUBE-AI `tinypose`.
- TCN : `pc/models/temporal/A_hm128_tcn/model_float32.tflite` (float32) → réseau X-CUBE-AI `tcn`.
  Analyze (X-CUBE-AI 9.0, stm32h7) : entrée f32 1×16×30, sortie f32 1×6, 24,3 Ko de poids, 1,9 Ko d'activations, 72 480 MACC.
  Float plutôt qu'int8 : 25 Ko seulement, aucune perte de quantification, et entrée/sortie directement en float.
- Le TCN écrit à la main en C (CLAUDE.md §8) devient un exercice optionnel pour plus tard ; `tv_temporal.h` sert aux deux versions.

## D12 — MPU : configuration par défaut de ST activée (phase 0)
- Question CubeMX à la création du projet : « préconfigurer la MPU pour la lecture spéculative du Cortex-M7 » → **Yes**.
- Effet : une région de fond interdit l'accès aux zones de mémoire **externe** non configurées, pour que les lectures
  spéculatives du M7 ne partent pas vers une adresse où rien ne répond (blocage du bus / faute imprévisible).
  Les mémoires internes (flash, DTCM, ITCM, AXI SRAM, SRAM1-4) restent accessibles.
- ⚠️ Conséquence phase 3 : avant d'utiliser la **SDRAM externe** (frames caméra), il faudra **ajouter une région MPU**
  qui l'autorise (et choisir ses attributs de cache). Sinon : MemManage / HardFault au premier accès.

## D13 — Passage à X-CUBE-AI 10.2.1 (ST Edge AI Core 2.2.0)
- CubeMX 6.17 charge le plugin X-CUBE-AI 9.0.0 mais n'affiche pas le panneau des réseaux (« no parameters to be configured »).
- X-CUBE-AI 10.x sépare le plugin CubeMX (20 Mo) du moteur `stedgeai` (zip `stedgeai-windows-10.2.0.zip`, ~3 Go décompressé).
- L'installation automatique du moteur par CubeMX a échoué (bug de chemin local « unknown protocol: c ») et le disque C: était
  plein → packs déplacés vers `D:\STM32Cube\STM32Cube\Repository`, zip décompressé dans `.../X-CUBE-AI/10.2.1/`.
- Vérification avec ST Edge AI Core 2.2.0 : TinyPose int8 = 114,4 Ko poids, 224,5 Ko activations, 21,2 M MACC ;
  TCN float = 24,3 Ko poids, 4,0 Ko activations, 72 480 MACC → identiques à la 9.0 (le TCN compte maintenant ses E/S).
- ⚠️ En 10.x, entrées et sorties sont placées **dans le buffer d'activations** par défaut : il faut **copier** l'image dans
  `in[0].data` (et lire `out[0].data`) au lieu de remplacer ces pointeurs.

## D14 — FPS mesuré et pas temporel du TCN (à reprendre)
- Calcul par image mesuré sur la carte : TinyPose 111,9 ms + TCN 1,1 ms ≈ 113 ms → ~8,8 images/s au maximum (avant caméra/écran).
- JHMDB est à ~30 images/s : à ~8 images/s sur la carte, une image traitée ≈ 4 images JHMDB. Le TCN a été entraîné avec des pas {1, 2, 3}.
- À faire quand le FPS réel avec caméra sera mesuré : réentraîner le TCN avec des pas autour de ce FPS (ex. {3, 4, 5}) — D7.

## D15 — SDRAM externe : région MPU 1 non cacheable (pour l'instant)
- Région 1 : 0xD0000000, 32 Mo, accès complet, **non cacheable**, non bufferable (l'exemple ST utilise cacheable write-through).
- Avantage : aucun problème de cohérence cache/DMA quand la caméra (DCMI+DMA) écrira dans la SDRAM.
- Coût : accès CPU plus lents (test 32 Mo écriture + relecture ≈ 0,9 s). À reconsidérer en phase 9 (cacheable + maintenance de cache).

## D16 — Fenêtre du TCN adaptée au FPS réel de la carte (remplace D14)
- FPS mesuré avec caméra : **5,6 img/s** → une image traitée ≈ 30 / 5,6 ≈ **5 images JHMDB**.
- Les clips JHMDB font **au plus 40 images (1,3 s)** : une fenêtre de 16 images au pas 5 (75 images) n'existe pas dans le dataset
  (elle serait surtout remplie par la 1re image répétée). → fenêtre de **8 images**, pas d'entraînement {4, 5, 6}, test au pas 5
  (8 × 5 = 40 images ≈ 1,3 s, la même durée sur PC et sur la carte).
- Résultats (test officiel, clip ; variabilité ± 5 points, 266 clips) :

| Modèle | Fenêtre / pas test | Précision clip |
|---|---|---|
| A_hm128_tcn (ancien, D9) | 16 / pas 2 | 0.504 |
| A_hm128_tcn (ancien) évalué comme la carte | 16 / pas 5 | 0.474 |
| A_hm128_tcn_w8 | 8 / pas 5 | 0.436 |
| A_hm128_tcn_rm_w8 | 8 / pas 5 | 0.500 |
| **A_hm128_tcn_noisy_w8 (retenu)** | 8 / pas 5 | **0.504** |
| A_hm128_tcn_rm_noisy_w8 | 8 / pas 5 | 0.459 |
| A_hm128_gru_rm_w8 | 8 / pas 5 | 0.436 |

- Retenu : **TCN 30 features (sans root motion), bruit d'entraînement ×3, fenêtre 8** : même précision que la référence, même
  normalisation que le code C déjà validé, buffer 2× plus court. Côté C : `TBUF_LEN = 8` ; TCN à régénérer dans CubeMX
  depuis `pc/models/temporal/A_hm128_tcn_noisy_w8/model_float32.tflite` (un `_Static_assert` empêche la compilation sinon).
