# Résultats

## Benchmarks TinyPose (X-CUBE-AI, cible STM32H747I-DISCO)
Modèles NON entraînés, int8, `stedgeai analyze --target stm32h7` (X-CUBE-AI 9.0.0). RAM totale = activations + entrée + sortie.

| Variante | Entrée | Sortie | Poids (Ko) | Activations (Ko) | RAM totale (Ko) | MACC (M) | Latence (ms) |
|---|---|---|---|---|---|---|---|
| A_hm128 (α=0.35) | 128×128 | 32×32×15 | 114 | 225 | 288 | 21.2 | à mesurer |
| B_hm96 (α=0.35) | 96×96 | 24×24×15 | 114 | 127 | 162 | 11.9 | à mesurer |
| C_reg128 (α=0.35) | 128×128 | 30 | 102 | 225 | 273 | 14.4 | à mesurer |
| D_hm128_light (α=0.35) | 128×128 | 32×32×15 | 107 | 225 | 288 | 18.3 | à mesurer |
| E_hm128_a050 (α=0.5) | 128×128 | 32×32×15 | 196 | 225 | 288 | 31.9 | à mesurer |
| F_hm128_a075 (α=0.75) | 128×128 | 32×32×15 | 396 | 406 | 469 | 63.6 | à mesurer |

## TinyPose entraîné — A_hm128 (α=0.35, 128×128)
30 epochs, batch 32, Adam 1e-3 cosinus, CPU : 55 min. Crop autour de la personne (marge 1.5) au test.

| Mesure | Valeur |
|---|---|
| PCK@0.2 validation (10 % des clips train) | 0.874 |
| PCK@0.2 test — Keras float | 0.761 |
| PCK@0.2 test — tflite float32 | 0.761 |
| PCK@0.2 test — **tflite int8 (déployé)** | **0.755** (perte int8 : 0,6 point) |
| X-CUBE-AI (entraîné, int8) | 114 Ko poids, 288 Ko RAM, 21,2 M MACC |

PCK test par joint (float) : face 0.93, neck 0.92, belly 0.87, hanches 0.85, épaules 0.79, genoux 0.76,
chevilles 0.74, coudes 0.62, poignets 0.62 → les extrémités qui bougent vite (poignets, coudes) sont les plus difficiles.

Écart val (0.87) / test (0.76) : la validation contient des clips issus des MÊMES vidéos sources que l'entraînement
(ex. `..._0`, `..._1` d'un même film), donc elle est optimiste. Le chiffre de référence est celui du test.
Exemples visuels : `pc/models/tinypose/A_hm128/pred_examples.png` (vert = vérité, rouge = prédiction, gris = score < 0.3).

## Modèle temporel — squelettes PARFAITS (annotations JHMDB, borne supérieure)
Split 1, test officiel, fenêtres de 16 frames au pas 2. « Clip » = moyenne des fenêtres d'un clip.
Variabilité observée d'un entraînement à l'autre : ± 5 points (petit jeu de test : ~266 clips).

| Modèle | Features | Paramètres | Précision fenêtre | Précision clip | Poids / RAM X-CUBE-AI |
|---|---|---|---|---|---|
| TCN | 30 (spec) | 6 214 | 0.826 | 0.797 | — |
| **TCN + root motion** | 32 | 6 406 | **0.861** | **0.838** | int8 : 15,5 Ko / 8,8 Ko ; float : 25 Ko / 3,9 Ko |
| GRU | 30 | 6 342 | 0.759 | 0.759 | — |
| GRU + root motion | 32 | 6 534 | 0.822 | 0.823 | float (.h5) : 25,5 Ko / 2,9 Ko |

## Modèle temporel — squelettes produits par TinyPose A_hm128 int8 (conditions réelles)
| Modèle | Précision fenêtre | Précision clip |
|---|---|---|
| TCN (30) | 0.542 | **0.504** |
| TCN + root motion | 0.507 | 0.474 |
| GRU | 0.495 | 0.455 |
| GRU + root motion | 0.507 | 0.489 |
| TCN + bruit d'entraînement (×3) | 0.540 | 0.492 |
| TCN + lissage 0.7 | 0.523 | 0.492 |

### Diagnostic de la chute 0.80 → 0.50 (voir decisions.md D9)
| TCN entraîné sur → testé sur | Clip | 5 classes cibles | other |
|---|---|---|---|
| parfaits → parfaits | 0.797 | 0.759 | 0.808 |
| parfaits → TinyPose | 0.511 | 0.362 | 0.553 |
| TinyPose → parfaits | 0.677 | 0.379 | 0.760 |
| TinyPose → TinyPose | 0.504 | 0.431 | 0.524 |

Qualité des squelettes extraits : PCK@0.2 = 0.908 sur les clips train (vus par TinyPose), 0.737 sur les clips test.
Tremblement frame→frame (médiane, unités normalisées) : annotations neck 0.001 / poignet 0.029 ; TinyPose neck 0.056 / poignet 0.084.

## Validation C ↔ Python (sur PC, gcc MinGW)
`firmware/host_tests/test_blocks.c` : post-traitement (joints, scores), normalisation 20 frames (avec les 2 cas limites),
buffer circulaire → fenêtre chronologique : **erreur max = 0** pour les 4 blocs. Test contrôlé : un lissage faussé est bien détecté (erreur 7.0).

## TinyPose E_hm128_a050 (α=0.5) — comparaison avec A
| Mesure | A (α=0.35) | E (α=0.5) |
|---|---|---|
| PCK@0.2 test float | 0.761 | **0.790** |
| PCK@0.2 test **int8** | 0.755 (−0.6) | 0.763 (**−2.8**) |
| X-CUBE-AI poids / RAM / MACC | 114 Ko / 288 Ko / 21,2 M | 196 Ko / 288 Ko / 31,9 M |
| TCN (30) sur ses squelettes, clip | 0.504 | 0.504 |
| TCN + root motion, clip | 0.474 | 0.526 |
