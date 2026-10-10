"""Étape 1 — Indexer JHMDB et vérifier la cohérence images ↔ joints.

Ce script :
  1. parcourt les 21 classes et lit chaque joint_positions.mat (pos_img : 2 x 15 x T) ;
  2. compte les images .png du clip correspondant et vérifie que T == nombre d'images ;
  3. lit le split officiel n°1 (train=1 / test=2) ;
  4. écrit pc/data/jhmdb_index.json (une entrée par clip) ;
  5. dessine les 15 joints sur quelques frames -> pc/data/check_joints/*.png (vérification visuelle).

Les joints de TOUS les clips (21 classes) servent à entraîner TinyPose : plus de données de pose.
Le choix des 5 classes + "other" ne concerne que le modèle temporel (étape TCN).

Usage (venv activé, depuis la racine du projet) :
    python pc/01_prepare_jhmdb.py
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import scipy.io as sio

DATA = Path(__file__).parent / "data"
JOINTS_DIR = DATA / "joint_positions"   # joint_positions/<classe>/<clip>/joint_positions.mat
FRAMES_DIR = DATA / "JHMDB" / "Frames"  # JHMDB/Frames/<classe>/<clip>/00001.png
SPLITS_DIR = DATA / "splits"            # splits/<classe>_test_split<k>.txt
SPLIT_ID = 1

# Ordre officiel (README, indices MATLAB 1..15 -> Python 0..14)
JOINT_NAMES = ["neck", "belly", "face", "R_shoulder", "L_shoulder", "R_hip", "L_hip",
               "R_elbow", "L_elbow", "R_knee", "L_knee", "R_wrist", "L_wrist", "R_ankle", "L_ankle"]
# Segments du squelette (pour le dessin)
BONES = [(2, 0), (0, 1), (0, 3), (0, 4), (3, 7), (7, 11), (4, 8), (8, 12),
         (1, 5), (1, 6), (5, 9), (9, 13), (6, 10), (10, 14)]


def read_split(cls):
    """Renvoie {nom_clip: 'train'|'test'} pour une classe. Les lignes sont 'video.avi 1|2'."""
    out = {}
    for line in (SPLITS_DIR / f"{cls}_test_split{SPLIT_ID}.txt").read_text().split("\n"):
        parts = line.split()
        if len(parts) == 2:
            name = parts[0].removesuffix(".avi")  # le .avi n'existe pas dans les noms de dossiers
            out[name] = "train" if parts[1] == "1" else "test"
    return out


def load_joints(mat_path):
    """pos_img (2, 15, T) -> tableau (T, 15, 2) en pixels : frame, joint, (x, y)."""
    pos = sio.loadmat(mat_path)["pos_img"]
    return np.transpose(pos, (2, 1, 0)).astype(np.float32)


def draw_skeleton(img, joints):
    """Dessine os + joints ; côté droit de la personne en rouge, gauche en bleu, centre en vert."""
    for a, b in BONES:
        pa, pb = tuple(map(int, joints[a])), tuple(map(int, joints[b]))
        cv2.line(img, pa, pb, (200, 200, 200), 1)
    for j, (x, y) in enumerate(joints):
        name = JOINT_NAMES[j]
        color = (0, 0, 255) if name.startswith("R_") else (255, 0, 0) if name.startswith("L_") else (0, 200, 0)
        cv2.circle(img, (int(x), int(y)), 3, color, -1)
    return img


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # accents corrects dans la console Windows
    classes = sorted(p.name for p in JOINTS_DIR.iterdir() if p.is_dir() and p.name != "joint_positions" and not p.name.startswith("."))
    index, problems = [], []

    for cls in classes:
        split = read_split(cls)
        for clip_dir in sorted(p for p in (JOINTS_DIR / cls).iterdir() if p.is_dir() and not p.name.startswith(".")):
            clip = clip_dir.name
            joints = load_joints(clip_dir / "joint_positions.mat")
            frames = sorted((FRAMES_DIR / cls / clip).glob("*.png"))
            h, w = cv2.imread(str(frames[0])).shape[:2] if frames else (0, 0)

            if len(frames) != len(joints):
                problems.append(f"{cls}/{clip}: {len(frames)} images mais {len(joints)} frames de joints")
            if clip not in split:
                problems.append(f"{cls}/{clip}: absent du split {SPLIT_ID}")

            index.append({
                "class": cls, "clip": clip,
                "split": split.get(clip, "unknown"),
                "n_frames": int(min(len(frames), len(joints))),
                # images/joints en nombre différent : on ne sait pas quelle frame correspond à quel squelette
                # -> clip exclu plutôt que de risquer des joints décalés
                "valid": len(frames) == len(joints),
                "width": int(w), "height": int(h),
                # fraction de joints hors image : ce sont les joints "neutres" non annotés (cf. README)
                "out_of_image": float(np.mean((joints[..., 0] < 0) | (joints[..., 0] >= w) |
                                              (joints[..., 1] < 0) | (joints[..., 1] >= h))) if w else 1.0,
            })

    (DATA / "jhmdb_index.json").write_text(json.dumps(index, indent=1))

    # ---- Résumé
    n_train = sum(e["split"] == "train" for e in index)
    n_test = sum(e["split"] == "test" for e in index)
    print(f"{len(classes)} classes, {len(index)} clips (train {n_train} / test {n_test}), "
          f"{sum(e['n_frames'] for e in index)} frames annotées")
    print(f"Tailles d'image rencontrées : {sorted({(e['width'], e['height']) for e in index})}")
    print(f"Joints hors image en moyenne : {100 * np.mean([e['out_of_image'] for e in index]):.1f} %")
    print(f"{len(problems)} problème(s) -> clip(s) marqué(s) valid=false")
    for p in problems[:20]:
        print("  -", p)

    # ---- Vérification visuelle : 1re, milieu et dernière frame d'un clip par classe cible
    out_dir = DATA / "check_joints"
    out_dir.mkdir(exist_ok=True)
    for cls in ["jump", "clap", "wave", "sit", "stand"]:
        e = next(e for e in index if e["class"] == cls)
        joints = load_joints(JOINTS_DIR / cls / e["clip"] / "joint_positions.mat")
        tiles = []
        for t in [0, e["n_frames"] // 2, e["n_frames"] - 1]:
            img = cv2.imread(str(FRAMES_DIR / cls / e["clip"] / f"{t + 1:05d}.png"))  # fichiers numérotés à partir de 1
            tiles.append(draw_skeleton(img, joints[t]))
        cv2.imwrite(str(out_dir / f"{cls}.png"), np.hstack(tiles))
    print(f"Images de vérification écrites dans {out_dir}")


if __name__ == "__main__":
    main()
