"""Évaluation PCK@0.2 de TinyPose — utilisée pour le modèle float (étape 3) ET int8 (étape 4).

PCK@0.2 (métrique standard sur JHMDB) : un joint est "correct" si la distance prédiction–vérité est
inférieure à 0.2 × la plus grande dimension de la boîte englobante de la personne.
Seuls les joints visibles dans le carré sont comptés.
"""
import random

import numpy as np

from .data import make_sample
from .heatmap import decode_heatmaps

JOINT_NAMES = ["neck", "belly", "face", "R_shoulder", "L_shoulder", "R_hip", "L_hip",
               "R_elbow", "L_elbow", "R_knee", "L_knee", "R_wrist", "L_wrist", "R_ankle", "L_ankle"]


def pck(predict_fn, samples, input_size, hm_size, max_samples=2000, batch=64, thr=0.2, seed=0):
    """predict_fn : images uint8 (N, S, S, 3) -> heatmaps float (N, hm, hm, 15).

    Renvoie (PCK moyen, PCK par joint). Échantillon fixe (seed) pour comparer float et int8 sur les mêmes images.
    """
    rng = random.Random(seed)
    chosen = rng.sample(samples, min(max_samples, len(samples)))
    hits = np.zeros(15)
    counts = np.zeros(15)
    for i in range(0, len(chosen), batch):
        items = [make_sample(*s, input_size, hm_size, False, rng) for s in chosen[i:i + batch]]
        imgs = np.stack([it[0] for it in items])
        hms = predict_fn(imgs)
        for (_, _, gt, vis), hm in zip(items, hms):
            if vis.sum() < 2:
                continue
            pred, _ = decode_heatmaps(hm, input_size)
            box = gt[vis].max(0) - gt[vis].min(0)
            ok = np.linalg.norm(pred - gt, axis=1) < thr * max(box.max(), 1.0)
            hits += ok & vis
            counts += vis
    per_joint = hits / np.maximum(counts, 1)
    return float(hits.sum() / counts.sum()), dict(zip(JOINT_NAMES, per_joint.round(3).tolist()))
