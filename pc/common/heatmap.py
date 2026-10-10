"""Encodage (joints -> heatmaps cibles) et décodage (heatmaps -> joints).

decode_heatmaps() est la RÉFÉRENCE du post-traitement qui sera écrit en C sur la carte :
le code C doit reproduire exactement les mêmes formules (même convention de pixel, même raffinement).

Convention de coordonnées (importante pour ne pas avoir un décalage de 1,5 pixel) :
  - un pixel d'entrée d'indice x a son centre en x (x = 0 .. 127) ;
  - la cellule de heatmap d'indice u couvre les pixels [4u, 4u+4[, son centre est en 4u + 1.5 ;
  - donc  u = (x + 0.5) / stride - 0.5   et   x = (u + 0.5) * stride - 0.5.
"""
import numpy as np

SIGMA = 1.5  # écart-type de la gaussienne, en cellules de heatmap


def encode_heatmaps(joints, visible, input_size, hm_size, sigma=SIGMA):
    """joints (15, 2) en pixels de l'image d'entrée, visible (15,) bool -> heatmaps (hm, hm, 15) float32.

    Joint non visible -> heatmap entièrement nulle : on apprend au modèle « ce joint n'est pas dans l'image ».
    """
    stride = input_size / hm_size
    grid = np.arange(hm_size, dtype=np.float32)
    hms = np.zeros((hm_size, hm_size, len(joints)), np.float32)
    for j, ((x, y), vis) in enumerate(zip(joints, visible)):
        if not vis:
            continue
        u = (x + 0.5) / stride - 0.5
        v = (y + 0.5) / stride - 0.5
        gx = np.exp(-((grid - u) ** 2) / (2 * sigma ** 2))
        gy = np.exp(-((grid - v) ** 2) / (2 * sigma ** 2))
        hms[:, :, j] = gy[:, None] * gx[None, :]  # gaussienne 2D séparable, pic = 1 au joint
    return hms


def decode_heatmaps(hms, input_size):
    """heatmaps (hm, hm, 15) -> joints (15, 2) en pixels d'entrée, scores (15,).

    Algorithme (identique en C) :
      1. argmax de chaque heatmap -> cellule (iu, iv) ; score = valeur du pic ;
      2. raffinement d'un quart de cellule vers le voisin le plus fort (gain de précision gratuit) ;
      3. conversion cellule -> pixel d'entrée.
    """
    hm_size = hms.shape[0]
    stride = input_size / hm_size
    joints = np.zeros((hms.shape[2], 2), np.float32)
    scores = np.zeros(hms.shape[2], np.float32)
    for j in range(hms.shape[2]):
        h = hms[:, :, j]
        iv, iu = np.unravel_index(np.argmax(h), h.shape)  # argmax renvoie (ligne, colonne) = (y, x)
        u, v = float(iu), float(iv)
        if 0 < iu < hm_size - 1:
            u += 0.25 * np.sign(h[iv, iu + 1] - h[iv, iu - 1])
        if 0 < iv < hm_size - 1:
            v += 0.25 * np.sign(h[iv + 1, iu] - h[iv - 1, iu])
        joints[j] = ((u + 0.5) * stride - 0.5, (v + 0.5) * stride - 0.5)
        scores[j] = h[iv, iu]
    return joints, scores
