"""Étape 6 — Vecteurs de test PC -> carte (règle d'or, CLAUDE.md §9).

Pour chaque bloc, on exporte une ENTRÉE et la SORTIE ATTENDUE calculée en Python, en tableaux C.
Sur la carte, on exécute le bloc sur l'entrée, on compare à la sortie attendue et on affiche l'erreur max par UART.

Fichiers générés (firmware/test_vectors/, à inclure dans le projet CM7) :
  tv_tinypose.h  : image 128×128×3 uint8 (HWC, RGB) -> heatmaps int8 attendues + joints/scores décodés
  tv_normalize.h : 20 frames de joints/scores -> features normalisées attendues
                   (inclut volontairement un joint à score faible et une frame à échelle nulle,
                    pour tester les deux chemins « valeur précédente » du code C)
  tv_temporal.h  : fenêtre 16×F float -> 6 probabilités attendues

Usage : python pc/07_make_test_vectors.py --pose A_hm128 --temporal A_hm128_tcn
"""
import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import tensorflow as tf

sys.path.insert(0, str(Path(__file__).parent))
from common.data import build_samples, load_index, make_sample  # noqa: E402
from common.heatmap import decode_heatmaps  # noqa: E402
from common.normalize import SkeletonNormalizer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "firmware" / "test_vectors"


def c_array(ctype, name, arr, per_line=16):
    """Tableau numpy -> déclaration C avec accolades imbriquées (une paire par dimension)."""
    arr = np.asarray(arr)
    fmt = (lambda v: f"{v:.8e}f") if ctype == "float" else (lambda v: str(int(v)))

    def nest(a, indent):
        if a.ndim == 1:
            items = [fmt(v) for v in a]
            rows = [", ".join(items[i:i + per_line]) for i in range(0, len(items), per_line)]
            return "{" + (",\n" + indent + " ").join(rows) + "}"
        return "{\n" + ",\n".join(indent + "  " + nest(x, indent + "  ") for x in a) + "\n" + indent + "}"

    dims = "".join(f"[{d}]" for d in arr.shape)
    return f"static const {ctype} {name}{dims} = " + nest(arr, "") + ";\n"


def header(name, body, doc):
    guard = name.upper().replace(".", "_")
    return (f"/* {name} — GÉNÉRÉ par pc/07_make_test_vectors.py, ne pas modifier à la main.\n * {doc}\n */\n"
            f"#ifndef {guard}\n#define {guard}\n\n#include <stdint.h>\n\n{body}\n#endif /* {guard} */\n")


def tflite_run(path, x):
    it = tf.lite.Interpreter(str(path))
    it.allocate_tensors()
    i, o = it.get_input_details()[0], it.get_output_details()[0]
    it.set_tensor(i["index"], x[None].astype(i["dtype"]))
    it.invoke()
    return it.get_tensor(o["index"])[0], o["quantization"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", default="A_hm128")
    ap.add_argument("--temporal", default="A_hm128_tcn")  # modèle retenu (decisions.md D9)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    models = Path(__file__).parent / "models"

    # ---------- 1. TinyPose : une frame de test (crop déterministe) ----------
    test = [e for e in load_index() if e["split"] == "test" and e["class"] == "wave"]
    sample = build_samples(test[:1])[10]
    img, _, _, _ = make_sample(*sample, 128, 32, False, random.Random(0))
    y_int8, (scale, zp) = tflite_run(models / "tinypose" / args.pose / "tinypose_int8.tflite", img)
    joints, scores = decode_heatmaps((y_int8.astype(np.float32) - zp) * scale, 128)
    body = (f"#define TV_POSE_OUT_SCALE {scale:.10e}f\n#define TV_POSE_OUT_ZERO_POINT {zp}\n\n"
            + c_array("uint8_t", "tv_pose_input", img)
            + c_array("int8_t", "tv_pose_expected_heatmaps", y_int8)
            + c_array("float", "tv_pose_expected_joints", joints)
            + c_array("float", "tv_pose_expected_scores", scores))
    (OUT / "tv_tinypose.h").write_text(header("tv_tinypose.h", body,
        f"Clip {sample[0]} ; entrée HWC RGB uint8 ; sortie int8 (32,32,15) ; joints en pixels 128x128."), encoding="utf-8")

    # ---------- 2. Normalisation : 20 frames d'un clip, avec 2 cas limites injectés ----------
    cfg = json.loads((models / "temporal" / args.temporal / "results.json").read_text())
    root_motion = cfg["n_features"] == 32
    d = np.load(Path(__file__).parent / "data" / f"skeletons_{args.pose}.npz", allow_pickle=True)
    meta = json.loads(str(d["meta"]))
    k = next(i for i, m in enumerate(meta) if m["split"] == "test" and m["class"] == "jump")
    J = d["joints"][k][:20].astype(np.float32).copy()
    S = d["scores"][k][:20].astype(np.float32).copy()
    S[5, 11] = 0.05            # frame 5 : poignet droit peu sûr -> doit reprendre la valeur de la frame 4
    J[8, 0] = J[8, 1]          # frame 8 : neck == belly -> échelle nulle -> doit reprendre l'échelle précédente
    S[8, 0] = S[8, 1] = 1.0
    norm = SkeletonNormalizer(root_motion, cfg.get("smooth", 0.0))  # mêmes réglages que le modèle choisi
    feats = np.stack([norm(j, s) for j, s in zip(J, S)])
    body = (f"#define TV_NORM_N_FRAMES {len(J)}\n#define TV_NORM_N_FEATURES {feats.shape[1]}\n\n"
            + c_array("float", "tv_norm_joints", J) + c_array("float", "tv_norm_scores", S)
            + c_array("float", "tv_norm_expected", feats))
    (OUT / "tv_normalize.h").write_text(header("tv_normalize.h", body,
        "Frame 5 : joint 11 score 0.05 (fallback valeur précédente). Frame 8 : neck==belly (fallback échelle)."),
        encoding="utf-8")

    # ---------- 3. Modèle temporel : la dernière fenêtre de 16 frames ci-dessus ----------
    window = feats[-16:]
    probs, _ = tflite_run(models / "temporal" / args.temporal / "model_float32.tflite", window)
    body = (f"#define TV_TEMP_WINDOW 16\n#define TV_TEMP_N_FEATURES {window.shape[1]}\n\n"
            + c_array("float", "tv_temp_input", window) + c_array("float", "tv_temp_expected_probs", probs))
    (OUT / "tv_temporal.h").write_text(header("tv_temporal.h", body,
        f"Modèle {args.temporal} ; classes jump, clap, wave, sit, stand, other ; ordre chronologique."),
        encoding="utf-8")

    for f in sorted(OUT.glob("*.h")):
        print(f"{f.name:16s} {f.stat().st_size / 1024:7.1f} Ko")
    print("Probabilités attendues (TCN) :", np.round(probs, 3))


if __name__ == "__main__":
    tf.get_logger().setLevel("ERROR")
    main()
