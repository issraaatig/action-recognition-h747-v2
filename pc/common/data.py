"""Chargement JHMDB pour TinyPose : découpage carré autour de la personne + augmentations.

Une seule transformation affine (cv2.warpAffine) fait à la fois : recentrage, mise à l'échelle,
rotation et translation. On applique EXACTEMENT la même matrice aux joints -> les labels restent alignés.
"""
import json
import math
import random
from pathlib import Path

import cv2
import numpy as np
import scipy.io as sio
from tensorflow import keras

from .heatmap import encode_heatmaps

DATA = Path(__file__).resolve().parent.parent / "data"
FRAMES_DIR = DATA / "JHMDB" / "Frames"
JOINTS_DIR = DATA / "joint_positions"

# Paires (droite, gauche) à échanger lors d'un miroir horizontal :
# épaules, hanches, coudes, genoux, poignets, chevilles
LR_PAIRS = [(3, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14)]


def load_index():
    return [e for e in json.loads((DATA / "jhmdb_index.json").read_text()) if e["valid"]]


def split_train_val(index, val_ratio=0.1, seed=0):
    """Validation = 10 % des CLIPS d'entraînement (jamais des frames d'un même clip des deux côtés).
    Le split test officiel n'est utilisé qu'une fois, à la fin, pour le chiffre du rapport."""
    train = [e for e in index if e["split"] == "train"]
    rng = random.Random(seed)
    rng.shuffle(train)
    n_val = int(len(train) * val_ratio)
    return train[n_val:], train[:n_val]


def load_joints(e):
    pos = sio.loadmat(JOINTS_DIR / e["class"] / e["clip"] / "joint_positions.mat")["pos_img"]
    return np.transpose(pos, (2, 1, 0)).astype(np.float32)  # (T, 15, 2)


def build_samples(clips, frame_step=1):
    """Liste de (chemin_image, joints (15,2), visible (15,)) pour chaque frame utilisable."""
    samples = []
    for e in clips:
        joints = load_joints(e)
        w, h = e["width"], e["height"]
        for t in range(0, e["n_frames"], frame_step):
            j = joints[t]
            vis = (j[:, 0] >= 0) & (j[:, 0] < w) & (j[:, 1] >= 0) & (j[:, 1] < h)
            if vis.sum() < 4:  # trop peu de joints dans l'image : impossible de cadrer la personne
                continue
            samples.append((str(FRAMES_DIR / e["class"] / e["clip"] / f"{t + 1:05d}.png"), j, vis))
    return samples


def crop_transform(joints, vis, out_size, train, rng):
    """Matrice affine 2×3 : image originale -> carré out_size×out_size centré sur la personne."""
    pts = joints[vis]
    x0, y0 = pts.min(0)
    x1, y1 = pts.max(0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    side = max(x1 - x0, y1 - y0, 40.0)  # 40 px minimum : évite un zoom énorme sur 4 joints serrés
    if train:
        side *= rng.uniform(1.3, 1.7)                  # marge variable -> robustesse à la taille
        cx += rng.uniform(-0.1, 0.1) * side            # personne pas toujours parfaitement centrée
        cy += rng.uniform(-0.1, 0.1) * side
        angle = rng.uniform(-20, 20)                   # petite rotation (caméra pas tout à fait droite)
    else:
        side *= 1.5
        angle = 0.0
    M = cv2.getRotationMatrix2D((cx, cy), angle, out_size / side)  # rotation+échelle autour du centre
    M[:, 2] += (out_size / 2 - cx, out_size / 2 - cy)               # puis centre -> milieu du carré
    return M


def make_sample(path, joints, vis, input_size, hm_size, train, rng):
    """Renvoie (image RGB uint8, heatmaps cibles, joints dans le carré, visibilité dans le carré)."""
    img = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
    M = crop_transform(joints, vis, input_size, train, rng)
    # Bords hors image remplis en noir (comme le serait un recadrage hors champ)
    crop = cv2.warpAffine(img, M, (input_size, input_size), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0))
    j = joints @ M[:, :2].T + M[:, 2]
    v = vis & (j[:, 0] >= 0) & (j[:, 0] < input_size) & (j[:, 1] >= 0) & (j[:, 1] < input_size)

    if train:
        if rng.random() < 0.5:  # miroir : x -> (S-1-x) ET échange gauche/droite
            crop = crop[:, ::-1].copy()
            j[:, 0] = input_size - 1 - j[:, 0]
            for r, l in LR_PAIRS:
                j[[r, l]] = j[[l, r]]
                v[[r, l]] = v[[l, r]]
        # Luminosité/contraste : la caméra de la carte n'aura pas les couleurs des films JHMDB
        alpha, beta = rng.uniform(0.7, 1.3), rng.uniform(-30, 30)
        crop = np.clip(crop.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)

    return crop, encode_heatmaps(j, v, input_size, hm_size), j, v


class PoseSequence(keras.utils.Sequence):
    """Fournit les batches à model.fit(). Images chargées à la volée (pas de cache de plusieurs Go)."""

    def __init__(self, samples, input_size, hm_size, batch_size, train, seed=0):
        super().__init__()
        self.samples, self.input_size, self.hm_size = samples, input_size, hm_size
        self.batch_size, self.train = batch_size, train
        self.rng = random.Random(seed)
        self.order = list(range(len(samples)))
        if train:
            self.rng.shuffle(self.order)

    def __len__(self):
        return math.ceil(len(self.samples) / self.batch_size)

    def __getitem__(self, i):
        ids = self.order[i * self.batch_size:(i + 1) * self.batch_size]
        # graine dérivée de l'indice : reproductible même avec plusieurs threads
        rng = random.Random(self.rng.random() if self.train else i)
        xs, ys = zip(*(make_sample(*self.samples[k], self.input_size, self.hm_size, self.train, rng)[:2]
                       for k in ids))
        return np.stack(xs).astype(np.float32), np.stack(ys)

    def on_epoch_end(self):
        if self.train:
            self.rng.shuffle(self.order)
