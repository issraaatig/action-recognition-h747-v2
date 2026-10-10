"""Étape 4 — Quantifier TinyPose entraîné en int8 et mesurer la perte de précision float -> int8.

Quantification post-entraînement (PTQ) : chaque tenseur float est remplacé par des entiers 8 bits
    valeur_réelle = scale × (valeur_int8 − zero_point)
Le convertisseur choisit scale/zero_point de chaque tenseur en observant les activations sur un
"jeu de calibration". Celui-ci doit ressembler aux images vues en déploiement : on utilise donc des
crops de personnes (comme à l'entraînement), PAS des images brutes 320×240.

Usage  : python pc/06_export_tflite.py --variant A_hm128
Sortie : pc/models/tinypose/<variante>/tinypose_int8.tflite  (+ float32.tflite pour comparaison)
         PCK float vs int8 ajouté dans results.json
"""
import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow import keras

sys.path.insert(0, str(Path(__file__).parent))
from common.data import build_samples, load_index, make_sample, split_train_val  # noqa: E402
from common.evaluate import pck  # noqa: E402
from common.tinypose import VARIANTS  # noqa: E402


def calibration_set(samples, size, hm, n=300, seed=0):
    rng = random.Random(seed)
    return np.stack([make_sample(*s, size, hm, False, rng)[0] for s in rng.sample(samples, n)])


def tflite_predict_fn(tfl_bytes):
    """Renvoie une fonction images uint8 -> heatmaps float, qui exécute le .tflite comme le ferait la carte."""
    it = tf.lite.Interpreter(model_content=tfl_bytes)
    it.allocate_tensors()
    inp, out = it.get_input_details()[0], it.get_output_details()[0]
    scale, zp = out["quantization"]

    def predict(imgs):
        res = []
        for img in imgs:  # batch de 1, comme sur la carte
            it.set_tensor(inp["index"], img[None].astype(inp["dtype"]))
            it.invoke()
            y = it.get_tensor(out["index"])[0]
            res.append((y.astype(np.float32) - zp) * scale if scale else y)  # déquantification int8 -> float
        return np.stack(res)
    return predict


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="A_hm128")
    ap.add_argument("--n-eval", type=int, default=1000)
    args = ap.parse_args()

    size = VARIANTS[args.variant]["input_size"]
    hm = size // 4
    d = Path(__file__).parent / "models" / "tinypose" / args.variant
    model = keras.models.load_model(str(d / "best.keras"))

    index = load_index()
    train_clips, _ = split_train_val(index)
    s_train = build_samples(train_clips, frame_step=5)  # 1 frame sur 5 suffit pour la calibration
    s_test = build_samples([e for e in index if e["split"] == "test"])
    calib = calibration_set(s_train, size, hm)

    # float32 (référence) et int8 (déploiement)
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    tfl_float = conv.convert()

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = lambda: ([x[None].astype(np.float32)] for x in calib)
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.uint8   # pixels caméra bruts 0..255
    conv.inference_output_type = tf.int8
    tfl_int8 = conv.convert()

    (d / "tinypose_float32.tflite").write_bytes(tfl_float)
    (d / "tinypose_int8.tflite").write_bytes(tfl_int8)
    print(f"tflite float32 : {len(tfl_float) / 1024:.0f} Ko   |   int8 : {len(tfl_int8) / 1024:.0f} Ko")

    # Même échantillon de test (seed fixe) pour les trois mesures
    keras_fn = lambda x: model.predict(x.astype("float32"), verbose=0)  # noqa: E731
    p_keras, _ = pck(keras_fn, s_test, size, hm, max_samples=args.n_eval)
    p_float, _ = pck(tflite_predict_fn(tfl_float), s_test, size, hm, max_samples=args.n_eval)
    p_int8, per_joint = pck(tflite_predict_fn(tfl_int8), s_test, size, hm, max_samples=args.n_eval)
    print(f"PCK@0.2 test ({args.n_eval} frames) : Keras {p_keras:.3f} | tflite float32 {p_float:.3f} | "
          f"tflite int8 {p_int8:.3f}  (perte int8 : {100 * (p_float - p_int8):.1f} points)")

    res_path = d / "results.json"
    res = json.loads(res_path.read_text()) if res_path.exists() else {}
    res.update({"pck_test_keras": p_keras, "pck_test_tflite_float": p_float, "pck_test_tflite_int8": p_int8,
                "pck_test_int8_per_joint": per_joint, "tflite_int8_kb": round(len(tfl_int8) / 1024)})
    res_path.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    tf.get_logger().setLevel("ERROR")
    main()
