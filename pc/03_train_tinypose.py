"""Étape 3 — Entraîner TinyPose (modèle float32) sur JHMDB.

  - données : frames des clips "train" (split 1), dont 10 % des clips en validation ;
  - cible   : heatmaps gaussiennes 32×32×15 (joints hors du carré -> heatmap nulle) ; perte MSE ;
  - optim.  : Adam, taux d'apprentissage en cosinus (1e-3 -> 0), backbone pré-entraîné ImageNet ;
  - sortie  : pc/models/tinypose/<variante>/best.keras (meilleure val_loss) + log CSV + results.json ;
  - à la fin : PCK@0.2 sur la validation et sur le test officiel (utilisé UNE fois, pour le rapport).

Usage :
    python pc/03_train_tinypose.py --variant A_hm128 --steps 20 --epochs 1   # test rapide / chronométrage
    python pc/03_train_tinypose.py --variant A_hm128 --epochs 40             # entraînement complet
"""
import argparse
import json
import sys
import time
from pathlib import Path

import tensorflow as tf
from tensorflow import keras

sys.path.insert(0, str(Path(__file__).parent))
from common.data import PoseSequence, build_samples, load_index, split_train_val  # noqa: E402
from common.evaluate import pck  # noqa: E402
from common.tinypose import VARIANTS, build_tinypose  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="A_hm128", choices=[k for k, v in VARIANTS.items() if v["head"] == "heatmap"])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--steps", type=int, default=None, help="limiter le nb de batches/epoch (test rapide)")
    ap.add_argument("--workers", type=int, default=6, help="threads de chargement des images")
    args = ap.parse_args()

    cfg = VARIANTS[args.variant]
    size = cfg["input_size"]
    hm = size // 4
    out_dir = Path(__file__).parent / "models" / "tinypose" / args.variant
    out_dir.mkdir(parents=True, exist_ok=True)

    index = load_index()
    train_clips, val_clips = split_train_val(index)
    test_clips = [e for e in index if e["split"] == "test"]
    s_train, s_val, s_test = build_samples(train_clips), build_samples(val_clips), build_samples(test_clips)
    print(f"frames : train {len(s_train)}, val {len(s_val)}, test {len(s_test)}")

    train_seq = PoseSequence(s_train, size, hm, args.batch, train=True)
    val_seq = PoseSequence(s_val, size, hm, args.batch, train=False)

    model = build_tinypose(**cfg)
    steps = args.steps or len(train_seq)
    lr = keras.optimizers.schedules.CosineDecay(args.lr, decay_steps=steps * args.epochs)
    model.compile(optimizer=keras.optimizers.Adam(lr), loss="mse")

    callbacks = [
        keras.callbacks.ModelCheckpoint(str(out_dir / "best.keras"), monitor="val_loss", save_best_only=True),
        keras.callbacks.CSVLogger(str(out_dir / "train_log.csv")),
    ]
    t0 = time.time()
    model.fit(train_seq, validation_data=val_seq, epochs=args.epochs, steps_per_epoch=args.steps,
              validation_steps=args.steps, callbacks=callbacks, verbose=2,
              workers=args.workers, use_multiprocessing=False)
    train_time = time.time() - t0
    print(f"Durée d'entraînement : {train_time / 60:.1f} min ({train_time / args.epochs:.0f} s/epoch)")

    # ---- Évaluation du meilleur modèle (float32)
    best = keras.models.load_model(str(out_dir / "best.keras"))
    predict = lambda x: best.predict(x.astype("float32"), verbose=0)  # noqa: E731
    n_eval = 200 if args.steps else 2000
    pck_val, _ = pck(predict, s_val, size, hm, max_samples=n_eval)
    pck_test, per_joint = pck(predict, s_test, size, hm, max_samples=n_eval)
    print(f"PCK@0.2  val {pck_val:.3f}  |  test {pck_test:.3f}")
    print("PCK test par joint :", per_joint)

    (out_dir / "results.json").write_text(json.dumps({
        "variant": args.variant, "epochs": args.epochs, "batch": args.batch, "lr": args.lr,
        "train_minutes": round(train_time / 60, 1),
        "pck_val": pck_val, "pck_test": pck_test, "pck_test_per_joint": per_joint,
    }, indent=1))


if __name__ == "__main__":
    tf.get_logger().setLevel("ERROR")
    main()
