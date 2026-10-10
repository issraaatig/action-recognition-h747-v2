"""Étape 5a — Extraire les squelettes de TOUS les clips avec TinyPose int8 (pas les annotations parfaites).

Pourquoi : le TCN doit apprendre sur le même bruit que celui qu'il verra sur la carte
(joints qui tremblent, joints ratés, scores faibles). On utilise donc le .tflite int8, celui qui sera déployé.

Cadrage : sur la carte, la caméra est fixe et on découpe TOUJOURS le même carré dans l'image.
Pour imiter ça, on utilise ici UN carré fixe par clip (englobant la personne sur tout le clip),
et non un carré qui suit la personne frame par frame — sinon le mouvement global (saut, assise) serait effacé.

Usage  : python pc/04_extract_skeletons.py --variant A_hm128
         python pc/04_extract_skeletons.py --gt   # annotations parfaites (borne supérieure / test du pipeline)
Sortie : pc/data/skeletons_<variante>.npz  (joints (T,15,2) en pixels 128×128, scores (T,15), classe, split)
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from common.data import FRAMES_DIR, load_index, load_joints  # noqa: E402
from common.heatmap import decode_heatmaps  # noqa: E402
from common.tinypose import VARIANTS  # noqa: E402

MARGIN = 1.3


def clip_crop_matrix(joints, w, h, size):
    """Carré fixe pour tout le clip : boîte de tous les joints visibles, toutes frames confondues."""
    pts = joints.reshape(-1, 2)
    vis = (pts[:, 0] >= 0) & (pts[:, 0] < w) & (pts[:, 1] >= 0) & (pts[:, 1] < h)
    pts = pts[vis]
    (x0, y0), (x1, y1) = pts.min(0), pts.max(0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    side = max(x1 - x0, y1 - y0, 40.0) * MARGIN
    s = size / side
    return np.array([[s, 0, size / 2 - s * cx], [0, s, size / 2 - s * cy]], np.float32)


def extract_gt(size):
    all_joints, all_scores, meta = [], [], []
    for e in load_index():
        J = load_joints(e)[:e["n_frames"]]
        M = clip_crop_matrix(J, e["width"], e["height"], size)
        Jc = J @ M[:, :2].T + M[:, 2]
        inside = (J[..., 0] >= 0) & (J[..., 0] < e["width"]) & (J[..., 1] >= 0) & (J[..., 1] < e["height"])
        all_joints.append(Jc.astype(np.float32))
        all_scores.append(inside.astype(np.float32))  # joint hors image = score 0 (comme un joint raté)
        meta.append({"class": e["class"], "clip": e["clip"], "split": e["split"]})
    path = Path(__file__).parent / "data" / "skeletons_GT.npz"
    np.savez_compressed(path, joints=np.array(all_joints, dtype=object), scores=np.array(all_scores, dtype=object),
                        meta=json.dumps(meta))
    print(f"{len(meta)} clips (annotations) -> {path}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="A_hm128")
    ap.add_argument("--gt", action="store_true", help="squelettes = annotations JHMDB (score 1, joints hors carré : 0)")
    args = ap.parse_args()
    size = VARIANTS[args.variant]["input_size"]
    if args.gt:
        return extract_gt(size)

    it = tf.lite.Interpreter(str(Path(__file__).parent / "models" / "tinypose" / args.variant / "tinypose_int8.tflite"))
    it.allocate_tensors()
    inp, out = it.get_input_details()[0], it.get_output_details()[0]
    scale, zp = out["quantization"]

    clips = load_index()
    all_joints, all_scores, meta = [], [], []
    for e in tqdm(clips, desc="clips"):
        M = clip_crop_matrix(load_joints(e)[:e["n_frames"]], e["width"], e["height"], size)
        J = np.zeros((e["n_frames"], 15, 2), np.float32)
        S = np.zeros((e["n_frames"], 15), np.float32)
        for t in range(e["n_frames"]):
            rgb = cv2.cvtColor(cv2.imread(str(FRAMES_DIR / e["class"] / e["clip"] / f"{t + 1:05d}.png")), cv2.COLOR_BGR2RGB)
            crop = cv2.warpAffine(rgb, M, (size, size), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0))
            it.set_tensor(inp["index"], crop[None])
            it.invoke()
            hm = (it.get_tensor(out["index"])[0].astype(np.float32) - zp) * scale
            J[t], S[t] = decode_heatmaps(hm, size)
        all_joints.append(J)
        all_scores.append(S)
        meta.append({"class": e["class"], "clip": e["clip"], "split": e["split"]})

    path = Path(__file__).parent / "data" / f"skeletons_{args.variant}.npz"
    np.savez_compressed(path, joints=np.array(all_joints, dtype=object), scores=np.array(all_scores, dtype=object),
                        meta=json.dumps(meta))
    s = np.concatenate([x.reshape(-1) for x in all_scores])
    print(f"{len(meta)} clips -> {path}")
    print(f"Scores des joints : médiane {np.median(s):.2f}, {100 * np.mean(s < 0.3):.1f} % sous le seuil 0.3")


if __name__ == "__main__":
    tf.get_logger().setLevel("ERROR")
    main()
