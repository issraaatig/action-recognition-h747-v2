"""Enregistre les squelettes produits PAR LA CARTE (lignes « SK,... » sur l'UART), avec une étiquette d'action.

But : réentraîner / affiner le TCN sur exactement ce que la carte voit (même caméra, même angle,
même bruit de TinyPose, même FPS), en plus de JHMDB (decisions.md, biais SIT).

Format d'une ligne envoyée par la carte (camera_app.c, record_skeleton) :
    SK,<tick ms>,<15 × 7 chiffres hexa>   par joint : x*2 (2 hexa), y*2 (2 hexa), score*1000 (3 hexa)
    x, y en pixels TinyPose (0..127), donc les mêmes unités que pc/data/skeletons_*.npz.

Usage (FERMER Tera Term avant : un port COM ne peut être ouvert que par un seul programme) :
    py -3.11 tools/record_skeletons.py                 # COM3, prises de 10 s
    py -3.11 tools/record_skeletons.py --port COM3 --seconds 10
Puis taper une étiquette à chaque prise : jump, clap, wave, sit, stand, idle (immobile), other (autre mouvement).
Chaque prise est sauvée dans pc/data/board_recordings/<date>_<étiquette>_<n°>.npz
"""
import argparse
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import serial  # pyserial

LABELS = ["jump", "clap", "wave", "sit", "stand", "idle", "other"]
OUT = Path(__file__).resolve().parent.parent / "pc" / "data" / "board_recordings"
N_JOINTS = 15


def parse_sk(line):
    """'SK,1234,<105 hexa>' -> (tick, joints (15, 2) float32, scores (15,) float32), ou None si la ligne est abîmée."""
    parts = line.strip().split(",")
    if len(parts) != 3 or parts[0] != "SK" or len(parts[2]) != N_JOINTS * 7:
        return None
    try:
        tick = int(parts[1])
        h = parts[2]
        v = [(int(h[k:k + 2], 16), int(h[k + 2:k + 4], 16), int(h[k + 4:k + 7], 16)) for k in range(0, len(h), 7)]
    except ValueError:
        return None
    a = np.array(v, np.float32)
    return tick, a[:, :2] / 2.0, a[:, 2] / 1000.0


def record(ser, seconds):
    """Lit les lignes SK pendant `seconds` secondes. Les autres lignes ([LIVE], ...) sont ignorées."""
    ticks, joints, scores, bad = [], [], [], 0
    ser.reset_input_buffer()                 # on jette ce qui est arrivé pendant la saisie de l'étiquette
    t_end = time.time() + seconds
    while time.time() < t_end:
        raw = ser.readline().decode("ascii", errors="replace")
        if not raw.startswith("SK,"):
            continue
        r = parse_sk(raw)
        if r is None:
            bad += 1
            continue
        ticks.append(r[0]); joints.append(r[1]); scores.append(r[2])
    return np.array(ticks), np.array(joints, np.float32), np.array(scores, np.float32), bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=10.0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    session = datetime.now().strftime("%Y%m%d_%H%M")
    counts = {}

    print(f"Ouverture de {args.port} @ {args.baud} (Tera Term doit être FERMÉ)")
    with serial.Serial(args.port, args.baud, timeout=1) as ser:
        while True:
            answer = input(f"\nÉtiquette ({', '.join(LABELS)}) [durée en s, optionnelle] ou q : ").strip().lower().split()
            if not answer:
                continue
            if answer[0] == "q":
                break
            lab = answer[0]
            if lab not in LABELS:
                print("  étiquette inconnue")
                continue
            seconds = float(answer[1]) if len(answer) > 1 else args.seconds   # ex. « sit 4 »
            for k in (3, 2, 1):                       # le temps de se mettre en place
                print(f"  départ dans {k}...", flush=True)
                time.sleep(1)
            print(f"  >>> ENREGISTREMENT « {lab} » pendant {seconds:.0f} s : fais l'action en continu", flush=True)
            ticks, J, S, bad = record(ser, seconds)
            if len(ticks) < 2:
                print("  aucune ligne SK reçue : la carte tourne-t-elle avec RECORD_SKELETONS = 1 ?")
                continue
            fps = (len(ticks) - 1) / ((ticks[-1] - ticks[0]) / 1000.0)
            visible = float((S >= 0.3).mean())
            counts[lab] = counts.get(lab, 0) + 1
            f = OUT / f"{session}_{lab}_{counts[lab]:02d}.npz"
            np.savez(f, joints=J, scores=S, ticks=ticks, label=lab)
            print(f"  {len(ticks)} images ({fps:.1f} img/s), joints sûrs (score >= 0,3) : {100 * visible:.0f} %, "
                  f"lignes abîmées : {bad} -> {f.name}")
            if visible < 0.5:
                print("  ATTENTION : moins de la moitié des joints sont sûrs. Es-tu en entier dans l'image ?")
    print("\nPrises enregistrées :", counts or "aucune")


if __name__ == "__main__":
    main()
