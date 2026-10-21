# Rapport : reconnaissance d'actions humaines sur STM32H747I-DISCO

## 1. Objectif

Une caméra filme une personne ; la carte STM32H747I-DISCO (Cortex-M7 à 400 MHz) reconnaît en temps réel l'action de cette personne. Le projet est organisé en deux modèles de réseaux de neurones, avec un traitement intermédiaire :

```
Image caméra 320×240
  → TinyPose (pose 2D, 15 articulations)
  → normalisation du squelette (30 nombres par image)
  → buffer circulaire de 8 images (8 × 30)
  → TCN (réseau temporel, 3 probabilités)
  → lissage (moyenne des 5 dernières prédictions) + seuil 0,6
  → action affichée à l'écran
```

Le modèle de pose est nécessaire parce qu'une seule image ne suffit pas à distinguer certaines actions (s'asseoir et se lever ont la même posture). Le modèle temporel analyse donc la suite des postures.

## 2. Matériel et environnement

- Carte STM32H747I-DISCO : Cortex-M7 à 400 MHz et Cortex-M4 à 200 MHz, SDRAM externe de 32 Mo, écran 800×480.
- Caméra OV5640 (module B-CAMS-OMV) reliée par le connecteur DCMI.
- Outils : STM32CubeIDE 2.1.1, STM32CubeMX 6.17, X-CUBE-AI 10.2.1.
- Entraînement sur PC (Windows 11, Python 3.11, TensorFlow/Keras, CPU).

## 3. Données

- **JHMDB** (dataset public) : vidéos d'humains annotés avec 15 articulations par image. On utilise les splits officiels train et test, qui séparent les vidéos pour éviter toute fuite entre l'entraînement et le test.
- **Prises de la carte** : enregistrées avec la caméra de la carte, par `tools/record_skeletons.py`. Chaque prise dure 10 secondes et porte une étiquette. Elles sont obtenues **après** TinyPose, donc elles contiennent le même bruit que le déploiement.

## 4. Modèle de pose : TinyPose

- Architecture : MobileNetV2 réduit (α = 0,35), entrée 128×128, sortie en cartes de chaleur 32×32 pour 15 articulations.
- Mesure de précision : PCK@0,2 (part des articulations placées à moins de 20 % de la taille de la personne).
  - **0,755** sur le modèle quantifié int8, recadré sur la personne ;
  - **0,608** avec le recadrage au centre utilisé sur la carte (la personne n'est pas toujours centrée).
  - La quantification int8 coûte 0,6 point par rapport au modèle en virgule flottante.
- Taille : 114 Ko de poids en flash, 225 Ko d'activations en RAM (rapport X-CUBE-AI).
- Latence sur la carte : **112 ms** par image.

Le prétraitement (recadrage 240×240, conversion RGB565 vers RGB888, redimensionnement à 128×128) est écrit en entier, pour être reproductible entre le PC et la carte. Il a été validé en **zéro différence** sur les 49 152 octets de l'image de test.

## 5. Normalisation et buffer

Le squelette est normalisé ainsi : origine au ventre, échelle égale à la distance cou-ventre, une articulation de score inférieur à 0,3 reprend la valeur de l'image précédente. Le buffer garde les 8 dernières images dans l'ordre chronologique. Le code C et le code Python sont identiques, validés à **zéro différence** par vecteurs de test.

## 6. Modèle temporel : TCN

- Architecture : deux convolutions 1D (32 filtres chacune), une moyenne globale, une couche de sortie à softmax. Environ 6 000 paramètres.
- Entraînement : `pc/05_train_temporal.py`, voir la section 9.
- Sur la carte : 24 Ko de poids, 2 Ko d'activations, **0,37 ms** par inférence. Généré par X-CUBE-AI à partir du modèle float32.

## 7. Parcours de développement

Le projet a suivi les phases suivantes (détail dans [docs/results.md](results.md)) :

| Phase | Contenu | Résultat |
|---|---|---|
| 0 | Démarrage de la carte, UART | OK |
| 3 | Caméra, SDRAM, écran | image en direct, 0 erreur DCMI sur ~80 s |
| 4 | TinyPose entraîné et quantifié | PCK 0,755 (int8) |
| 5 | TinyPose sur la carte, vecteur de test | erreur 0 |
| 6 | Squelette dessiné en direct | 3,7 puis 5,6 img/s |
| 7 | TCN sur PC | précision JHMDB 0,50 (30 features, fenêtre 16 puis 8) |
| 8 | Normalisation, buffer, TCN en C | erreur 0 sur les vecteurs de test |
| 3.6 | Chaîne complète en direct | 5,6 img/s, action affichée |

## 8. Problèmes rencontrés et solutions

Les bugs résolus sont décrits dans [docs/debug_journal.md](debug_journal.md). Les principaux :

- **Caméra qui ne livre pas d'image** : la configuration CubeMX écrasait la fonction d'initialisation de la caméra fournie par le BSP. Corrigé en retirant la génération de cette fonction.
- **Overruns DCMI** : le bus SDRAM était saturé par l'écran, la copie et la caméra. Corrigé en suspendant la caméra pendant les écritures.
- **Biais vers SIT** : quand une personne était debout immobile, la carte affichait SIT. Cause : les données d'entraînement (JHMDB) ne ressemblaient pas aux images de la carte. Corrigé en ajoutant les prises de la carte à l'entraînement.
- **Étiquettes silencieusement fausses** : le chargeur de données mettait en « other » toute étiquette inconnue. Corrigé : les étiquettes hors classes sont ignorées.
- **Vecteur de test périmé** : après un changement de modèle, le test de la carte comparait au mauvais modèle. Corrigé par régénération : chaque modèle a ses propres vecteurs de test, et le test est relancé après chaque import.

Un problème reste ouvert : des erreurs DCMI apparaissent en optimisation `-O2` (aucune en `-O0`). Le projet reste en `-O0`.

## 9. Choix des classes et entraînement

### 9.1 Classes testées et retenues

Les classes du cahier des charges étaient JUMP, CLAP, WAVE, SIT, STAND et other. Les essais ont montré que notre chaîne ne peut pas séparer certaines de ces paires :

| Classe | Problème constaté | Décision |
|---|---|---|
| CLAP | confondu avec WAVE : les deux gestes se reconnaissent surtout aux poignets, le joint le moins bien détecté par TinyPose | retirée |
| STAND | même geste que SIT, mouvement inverse ; difficile à enregistrer sans mélanger les étiquettes | retirée |
| JUMP | la normalisation efface le mouvement vertical du corps ; il reste les genoux pliés, comme pour s'asseoir | testée, non retenue (voir 9.2) |

Le modèle final reconnaît donc **WAVE, SIT et other**, où `other` regroupe les mouvements quelconques et la personne immobile.

### 9.2 Test de JUMP

- Avec `--root-motion` (32 features, réintroduction du mouvement du corps) : JUMP est bien reconnu, mais WAVE tombe à 1 fenêtre sur 24 sur la carte. Rejeté.
- Sans `--root-motion` : validation croisée à 0,61 (score moyen), contre 0,77 à 0,79 sans JUMP. `other` passe de 0,75 à 0,57 de rappel, car une partie des mouvements est prise pour un saut. Non retenu.

### 9.3 Entraînement du modèle final

Commande : `python pc/05_train_temporal.py --model tcn --window 8 --steps 4 5 6 --test-step 5 --noisy 1`

- **Entraînement** : clips JHMDB « train » officiels (90 %) et prises de la carte (une prise de chaque classe est mise de côté pour le test).
- **Validation** : 10 % des clips JHMDB « train » (65 fenêtres), pour l'arrêt anticipé.
- **Époques** : maximum 150, arrêt anticipé si la perte de validation ne baisse plus pendant 20 époques. Le modèle final s'arrête à 45 époques ; les poids retenus sont ceux de la meilleure époque (25).
- **Réglages** : Adam (pas 1e-3), taille de lot 256, dropout 0,3, poids par classe.
- **Fenêtres** : 8 images, pas d'échantillonnage 4, 5 ou 6 à l'entraînement et 5 au test (pour simuler le FPS de la carte).

Les courbes d'entraînement sont dans [docs/figures/courbes_entrainement_final.png](figures/courbes_entrainement_final.png).

### 9.4 Validation croisée

Pour éviter qu'un seul choix de prise de test fausse la mesure, `pc/08_cv_board.py` fait un tour par prise : chaque prise de la carte sert de test à tour de rôle, avec 30 époques fixes et sans arrêt anticipé. Résultats :

| Configuration | Score moyen | wave | sit | other | jump |
|---|---|---|---|---|---|
| 3 classes (retenue) | 0,77 à 0,79 | 0,61 à 0,73 | 0,67 à 0,71 | 0,75 à 0,78 | – |
| 4 classes avec JUMP | 0,61 | 0,80 | 0,73 | 0,57 | 0,65 |

Le détail des tours est dans [docs/figures/validation_croisee.png](figures/validation_croisee.png).

## 10. Résultats finaux

| Mesure | Valeur |
|---|---|
| Validation croisée sur la carte (3 classes) | score moyen 0,77 à 0,79 |
| Test JHMDB (modèle final) | précision 0,823 (0,688 avant l'ajout des prises de la carte ; écart de ±5 points entre entraînements) |
| Test carte (3 prises tenues) | 100 % (trop peu de prises pour conclure) |
| Vecteur de test TCN sur la carte | erreur 0 e-6 |
| Essai en direct (WAVE, SIT, immobile, marche) | immobile → `...` (80 à 97 %) ; assis → SIT (88 à 99 %, environ 20 s) ; WAVE 49 à 94 %, instable |
| Fréquence de la chaîne complète | 5,6 img/s |

Matrices de confusion : [docs/figures/matrices_confusion_final.png](figures/matrices_confusion_final.png).

## 11. Limites

- **Une seule personne** pour toutes les prises : le modèle peut ne pas généraliser à d'autres personnes, tailles ou vêtements.
- **Peu de prises** : entre 5 et 15 par classe, dont une seule par classe est gardée pour le test. La validation croisée est la mesure la plus fiable, et elle reste sur peu d'exemples.
- **Cadrage** : TinyPose ne voit que le carré central 240×240 de l'image. Un bras levé ou les pieds hors du carré font perdre des articulations.
- **FPS** : 5,6 img/s seulement. Un mouvement rapide (saut, applaudissement) ne dure que quelques images.
- **Biais SIT** : les personnes debout qui bougent un peu peuvent encore être prises pour SIT dans une partie des fenêtres.
- **WAVE** : la reconnaissance oscille entre 50 et 75 % en direct, le lissage ne la stabilise pas toujours.

## 12. Perspectives

1. **Plus de personnes et plus de prises** pour généraliser, et refaire les prises `other` et `idle` bien cadrées.
2. **Améliorer JUMP** en changeant la normalisation (et non en ajoutant le déplacement brut), sans dégrader WAVE.
3. **Double buffer DMA** (phase 9) : passer d'environ 5,6 à 8 img/s, pour mieux capter les mouvements rapides.
4. **Modèle de pose plus précis** pour les poignets, qui limitent CLAP et WAVE.
5. **Comparaison TCN / GRU** sur la carte, demandée par le cahier des charges, pour le rapport final.
6. **Lissage et seuil** : tester d'autres valeurs (fenêtre de lissage, seuil de 0,6) en direct.

## 13. Reproduction

Les commandes complètes sont dans le [README](../README.md). Les mesures sont sauvegardées dans `pc/models/temporal/` (`results.json`, `train_log.csv`, `cv_board_*.json`).
