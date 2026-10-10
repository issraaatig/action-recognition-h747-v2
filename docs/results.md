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

## Précision
| Modèle | Données | Métrique | Valeur |
|---|---|---|---|
