"""Étape 2 — Construire des variantes de TinyPose (NON entraînées) et les exporter en .tflite int8
pour vérifier dans X-CUBE-AI (Analyze) qu'elles tiennent dans la STM32H747 AVANT d'entraîner.

Pourquoi un modèle non entraîné suffit : la taille des poids, la RAM d'activations et le nombre
d'opérations (MACC) ne dépendent que de l'architecture, pas des valeurs des poids.

Pourquoi int8 : c'est le format qu'on déploiera (4× plus petit que float32, calcul entier rapide sur M7).
La quantification a besoin d'un "jeu de calibration" (vraies images) pour mesurer la plage des activations.

Usage :  python pc/02_build_tinypose.py
Sortie : pc/models/bench/<variante>_int8.tflite  +  tableau récapitulatif
"""
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf

sys.path.insert(0, str(Path(__file__).parent))
from common.tinypose import VARIANTS, build_tinypose  # noqa: E402

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "models" / "bench"



def calibration_images(size, n=100, seed=0):
    """n vraies frames JHMDB (train uniquement), redimensionnées en size×size, RGB uint8."""
    index = [e for e in json.loads((DATA / "jhmdb_index.json").read_text()) if e["split"] == "train" and e["valid"]]
    rng = random.Random(seed)
    imgs = []
    for e in rng.sample(index, n):
        t = rng.randrange(e["n_frames"])
        bgr = cv2.imread(str(DATA / "JHMDB" / "Frames" / e["class"] / e["clip"] / f"{t + 1:05d}.png"))
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)  # OpenCV lit en BGR, le modèle attend du RGB
        imgs.append(cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA))
    return np.stack(imgs)


def to_int8_tflite(model, calib):
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    # Le générateur fournit des images une par une ; le convertisseur en déduit min/max de chaque tenseur.
    conv.representative_dataset = lambda: ([img[None].astype(np.float32)] for img in calib)
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]  # tout en int8, sinon erreur
    conv.inference_input_type = tf.uint8   # la carte donnera les pixels bruts 0..255
    conv.inference_output_type = tf.int8
    return conv.convert()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    only = sys.argv[1:]  # ex. : python pc/02_build_tinypose.py E_hm128_a050  (sinon toutes les variantes)
    for name, cfg in VARIANTS.items():
        if only and name not in only:
            continue
        model = build_tinypose(**cfg)
        calib = calibration_images(cfg["input_size"])
        tfl = to_int8_tflite(model, calib)
        path = OUT / f"{name}_int8.tflite"
        path.write_bytes(tfl)
        rows.append((name, model.input_shape[1:], model.output_shape[1:], model.count_params(), len(tfl)))
        print(f"OK {name} -> {path}")

    print(f"\n{'Variante':15s} {'Entrée':15s} {'Sortie':15s} {'Paramètres':>11s} {'.tflite (Ko)':>13s}")
    for name, i, o, p, b in rows:
        print(f"{name:15s} {str(i):15s} {str(o):15s} {p:11,d} {b / 1024:13.0f}")


if __name__ == "__main__":
    main()
