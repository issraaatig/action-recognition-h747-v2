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
