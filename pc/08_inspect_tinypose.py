"""Voir où TinyPose se trompe : précision par joint + galerie d'exemples de test.

Produit dans pc/models/tinypose/<variante>/ :
  - pck_par_joint.png : barre par joint = % de joints bien placés (PCK@0.2, modèle int8, images de test)
  - erreurs_poignets.png : images de test ; vert = vraie position, rouge = TinyPose,
                           trait jaune = erreur (dessiné pour les poignets et les coudes)

Usage : python pc/08_inspect_tinypose.py --variant A_hm128
"""
import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import matplotlib
import numpy as np
import tensorflow as tf

matplotlib.use("Agg")  # pas de fenêtre : on écrit directement un fichier .png
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from common.data import build_samples, load_index, make_sample  # noqa: E402
from common.evaluate import JOINT_NAMES  # noqa: E402
from common.heatmap import decode_heatmaps  # noqa: E402

ARMS = [7, 8, 11, 12]  # R_elbow, L_elbow, R_wrist, L_wrist


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="A_hm128")
    args = ap.parse_args()
    d = Path(__file__).parent / "models" / "tinypose" / args.variant

    # ---- 1. Barres : PCK par joint (calculé par 06_export_tflite.py, modèle int8)
    res = json.loads((d / "results.json").read_text())
    per_joint = res.get("pck_test_int8_per_joint", res["pck_test_per_joint"])
    names, vals = list(per_joint), [100 * v for v in per_joint.values()]
    colors = ["#E24B4A" if i in ARMS else "#378ADD" for i in range(15)]  # bras en rouge
    plt.figure(figsize=(10, 4))
    plt.bar(names, vals, color=colors)
    plt.axhline(100 * res.get("pck_test_tflite_int8", res["pck_test"]), color="gray", ls="--", label="moyenne")
    plt.ylabel("% de joints bien placés (PCK@0.2)")
    plt.ylim(0, 100)
    plt.xticks(rotation=45, ha="right")
    plt.title(f"TinyPose {args.variant} (int8) sur les vidéos de test — rouge = coudes et poignets")
    plt.legend()
    plt.tight_layout()
    plt.savefig(d / "pck_par_joint.png", dpi=110)

    # ---- 2. Galerie : 8 images de test, vérité (vert) vs TinyPose (rouge), erreurs des bras en jaune
    it = tf.lite.Interpreter(str(d / "tinypose_int8.tflite"))
    it.allocate_tensors()
    inp, out = it.get_input_details()[0], it.get_output_details()[0]
    scale, zp = out["quantization"]
    rng = random.Random(3)
    test = [e for e in load_index() if e["split"] == "test" and e["class"] in ("clap", "wave", "jump", "sit")]
    tiles = []
    for e in rng.sample(test, 8):
        s = build_samples([e])
        img, _, gt, vis = make_sample(*s[len(s) // 2], 128, 32, False, rng)
        it.set_tensor(inp["index"], img[None])
        it.invoke()
        pred, _ = decode_heatmaps((it.get_tensor(out["index"])[0].astype(np.float32) - zp) * scale, 128)
        im = cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2BGR), (256, 256))
        for j in range(15):
            g, p = tuple((gt[j] * 2).astype(int)), tuple((pred[j] * 2).astype(int))
            if vis[j] and j in ARMS:
                cv2.line(im, g, p, (0, 220, 255), 2)               # trait jaune = erreur
            if vis[j]:
                cv2.circle(im, g, 4, (0, 200, 0), -1)               # vert = vérité
            cv2.circle(im, p, 4, (0, 0, 255), -1)                   # rouge = TinyPose
        cv2.putText(im, e["class"], (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        tiles.append(im)
    cv2.imwrite(str(d / "erreurs_poignets.png"), np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])]))
    print(f"Écrit : {d / 'pck_par_joint.png'}\n        {d / 'erreurs_poignets.png'}")


if __name__ == "__main__":
    tf.get_logger().setLevel("ERROR")
    main()
