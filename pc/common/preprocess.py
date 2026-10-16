"""Prétraitement caméra -> entrée TinyPose. RÉFÉRENCE du code C (firmware .../Core/Src/preprocess.c).

Image caméra : 320×240 en RGB565 (un uint16 par pixel : 5 bits rouge, 6 bits vert, 5 bits bleu).
Entrée TinyPose : 128×128×3 uint8, ordre HWC, canaux R, G, B (la normalisation [-1, 1] est DANS le modèle).

Étapes (identiques au bit près en C, d'où le calcul en ENTIERS uniquement) :
  1. recadrage carré au centre : colonnes 40..279, toutes les lignes -> 240×240 ;
  2. RGB565 -> RGB888 : chaque canal étendu à 8 bits en recopiant ses bits forts (31 -> 255, pas 248) ;
  3. réduction 240 -> 128 par interpolation BILINÉAIRE en virgule fixe (poids sur 8 bits, /256),
     convention « centre de pixel » comme cv2.INTER_LINEAR (utilisé à l'entraînement).
"""
import numpy as np

CAM_W, CAM_H = 320, 240
CROP = CAM_H                    # côté du carré recadré (240)
CROP_X0 = (CAM_W - CROP) // 2   # 40
OUT = 128


def rgb888_to_rgb565(img):
    """(H, W, 3) uint8 -> (H, W) uint16, comme le capteur (bits faibles perdus). Sert à fabriquer l'entrée de test."""
    r, g, b = (img[..., c].astype(np.uint16) for c in range(3))
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def rgb565_to_rgb888(p):
    """(H, W) uint16 -> (H, W, 3) int64 0..255."""
    p = p.astype(np.int64)
    r5, g6, b5 = (p >> 11) & 0x1F, (p >> 5) & 0x3F, p & 0x1F
    return np.stack([(r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2)], axis=-1)


def source_coords(n_src, n_dst):
    """Pour chaque pixel de sortie : indice source i0, i1 et poids f (0..255) de i1, en virgule fixe Q8.
    s = (d + 0.5) * n_src / n_dst - 0.5, calculé exactement en entiers : ((2d+1)*n_src*256) // (2*n_dst) - 128."""
    d = np.arange(n_dst, dtype=np.int64)
    s256 = ((2 * d + 1) * n_src * 256) // (2 * n_dst) - 128   # toujours >= 0 ici (240 -> 128)
    i0 = s256 >> 8
    f = s256 & 0xFF
    i1 = np.minimum(i0 + 1, n_src - 1)
    return i0, i1, f


def camera_to_tinypose(frame565):
    """(240, 320) uint16 RGB565 -> (128, 128, 3) uint8 RGB : exactement ce que fait preprocess.c."""
    assert frame565.shape == (CAM_H, CAM_W)
    rgb = rgb565_to_rgb888(frame565[:, CROP_X0:CROP_X0 + CROP])       # (240, 240, 3)
    y0, y1, fy = source_coords(CROP, OUT)
    x0, x1, fx = source_coords(CROP, OUT)
    fx, fy = fx[None, :, None], fy[:, None, None]
    a, b = rgb[y0][:, x0], rgb[y0][:, x1]      # ligne du haut : gauche, droite
    c, d = rgb[y1][:, x0], rgb[y1][:, x1]      # ligne du bas
    top = a * (256 - fx) + b * fx              # interpolation horizontale (x256)
    bot = c * (256 - fx) + d * fx
    out = (top * (256 - fy) + bot * fy + 32768) >> 16   # verticale (x256 encore), +0.5 puis /65536 : arrondi
    return out.astype(np.uint8)
