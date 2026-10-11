"""Étape 5b — Entraîner le modèle temporel (TCN, comparé au GRU) sur les squelettes de TinyPose.

Données : squelettes extraits par 04_extract_skeletons.py (même bruit que sur la carte).
Classes : jump, clap, wave, sit, stand + other (= les 16 autres classes JHMDB, pour apprendre à « refuser »).

Fenêtres : 16 frames prises toutes les `step` frames. Sur la carte, une frame sur N est traitée
(N dépend du FPS réel, à mesurer). Les clips JHMDB sont courts (~34 frames) : on entraîne avec
step ∈ {1, 2, 3} tiré au hasard -> le modèle devient robuste à la vitesse (≈ FPS) de la carte.
Fenêtre plus longue que le clip -> la 1re frame est répétée au début (comme un buffer qui se remplit).
JAMAIS d'inversion temporelle : sit (s'asseoir) et stand (se lever) sont des mouvements inverses.

Usage :
    python pc/05_train_temporal.py --model tcn            # TCN, 30 features (spec CLAUDE.md)
    python pc/05_train_temporal.py --model tcn --root-motion   # + mouvement global du bassin (32 features)
    python pc/05_train_temporal.py --model gru [--root-motion]
"""
import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

sys.path.insert(0, str(Path(__file__).parent))
from common.normalize import mirror_features, normalize_sequence  # noqa: E402

CLASSES = ["jump", "clap", "wave", "sit", "stand", "other"]
WINDOW = 16
TEST_STEP = 2  # pas utilisé pour l'évaluation (≈ 15 FPS) ; à ajuster quand le FPS de la carte sera mesuré


def label_of(cls):
    return CLASSES.index(cls) if cls in CLASSES else CLASSES.index("other")


def windows_from_clip(feats, step, stride=2):
    """feats (T, F) -> fenêtres (N, 16, F) de 16 frames espacées de `step`, décalées de `stride` frames."""
    T = len(feats)
    span = (WINDOW - 1) * step
    starts = range(0, max(T - span, 1), stride)
    out = []
    for s in starts:
        idx = s + step * np.arange(WINDOW) - max(0, span - (T - 1))  # recule si le clip est trop court
        out.append(feats[np.clip(idx, 0, T - 1)])               # indices < 0 -> 1re frame répétée
    return np.stack(out)


def corrupt_skeleton(J, S, rng, p_err=0.15, p_low=0.08, jitter=2.0):
    """Ajoute aux squelettes d'entraînement le bruit que TinyPose produit sur des images jamais vues :
    TinyPose a vu les clips d'entraînement (PCK 0.91) mais pas ceux du test (PCK 0.74).
      - p_err  : joint "raté" -> déplacé loin (écart-type 30 % de la taille de la personne) ;
      - p_low  : score qui tombe sous le seuil -> la normalisation reprendra la valeur précédente ;
      - jitter : tremblement de quelques pixels sur tous les joints."""
    J, S = J.copy(), S.copy()
    size = max(float(np.ptp(J.reshape(-1, 2), 0).max()), 10.0)
    err = rng.random(S.shape) < p_err
    J[err] += rng.normal(0, 0.3 * size, (err.sum(), 2))
    J += rng.normal(0, jitter, J.shape)
    S[rng.random(S.shape) < p_low] = 0.0
    return J.astype(np.float32), S


def make_dataset(clips, root_motion, steps, augment, rng, n_noisy=0, smooth=0.0):
    X, y, clip_id = [], [], []
    for k, (J, S, m) in enumerate(clips):
        for step in steps:
            # la normalisation est refaite pour chaque pas : sur la carte, la "frame précédente"
            # est la précédente TRAITÉE, donc dépend du pas
            sub = slice(0, None, step)
            f = normalize_sequence(J[sub], S[sub], root_motion, smooth)
            w = windows_from_clip(f, 1)  # f est déjà sous-échantillonné
            variants = [w]
            for _ in range(n_noisy):  # copies bruitées (bruit appliqué AVANT la normalisation, comme en vrai)
                Jn, Sn = corrupt_skeleton(J[sub], S[sub], rng)
                variants.append(windows_from_clip(normalize_sequence(Jn, Sn, root_motion, smooth), 1))
            if augment:
                variants.append(mirror_features(w))                                   # miroir G/D
                variants.append(w * rng.uniform(0.9, 1.1) + rng.normal(0, 0.03, w.shape))  # échelle + bruit
            for v in variants:
                X.append(v)
                y += [label_of(m["class"])] * len(v)
                clip_id += [k] * len(v)
    return np.concatenate(X).astype(np.float32), np.array(y), np.array(clip_id)


def build_model(kind, n_feat):
    inp = keras.Input((WINDOW, n_feat), name="skeleton_window")
    if kind == "tcn":
        x = layers.Conv1D(32, 3, activation="relu", name="conv1")(inp)                  # 16 -> 14
        x = layers.Conv1D(32, 3, dilation_rate=2, activation="relu", name="conv2")(x)   # 14 -> 10
        x = layers.GlobalAveragePooling1D(name="gap")(x)
    else:
        x = layers.GRU(32, unroll=True, name="gru")(inp)  # 16 pas fixes -> boucle déroulée (convertible)
    x = layers.Dropout(0.3)(x)
    out = layers.Dense(len(CLASSES), activation="softmax", name="probs")(x)
    return keras.Model(inp, out, name=kind)


def export_tflite(model, Xtr, out_dir, kind):
    """TCN -> .tflite float32 et int8 (calcul int8, entrée/sortie float : la carte donne directement
    les 16×30 features normalisées et lit 6 probabilités). Le GRU n'est exporté qu'en float32 :
    les couches récurrentes se quantifient mal en int8 post-entraînement.
    X-CUBE-AI 9.0 refuse le GRU déroulé en .tflite (SPLIT_V avec taille -1) -> pour le GRU on exporte
    AUSSI un .h5 Keras (GRU non déroulé, mêmes poids), que X-CUBE-AI importe directement."""
    if kind == "gru":
        inp = keras.Input(model.input_shape[1:])
        x = layers.GRU(32, name="gru")(inp)
        m2 = keras.Model(inp, layers.Dense(len(CLASSES), activation="softmax", name="probs")(x))
        for n in ("gru", "probs"):
            m2.get_layer(n).set_weights(model.get_layer(n).get_weights())
        m2.save(str(out_dir / "model.h5"))
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    (out_dir / "model_float32.tflite").write_bytes(conv.convert())
    if kind == "tcn":
        calib = Xtr[np.random.default_rng(1).choice(len(Xtr), 500, replace=False)]
        conv = tf.lite.TFLiteConverter.from_keras_model(model)
        conv.optimizations = [tf.lite.Optimize.DEFAULT]
        conv.representative_dataset = lambda: ([x[None]] for x in calib)
        (out_dir / "model_int8.tflite").write_bytes(conv.convert())


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["tcn", "gru"], default="tcn")
    ap.add_argument("--root-motion", action="store_true")
    ap.add_argument("--variant", default="A_hm128", help="variante TinyPose ayant produit les squelettes")
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--noisy", type=int, default=0, help="nb de copies bruitées par clip (bruit type TinyPose)")
    ap.add_argument("--smooth", type=float, default=0.0, help="lissage exponentiel des joints (0 = aucun, 0.6 = fort)")
    args = ap.parse_args()
    rng = np.random.default_rng(0)
    tf.random.set_seed(0)

    d = np.load(Path(__file__).parent / "data" / f"skeletons_{args.variant}.npz", allow_pickle=True)
    clips = list(zip(d["joints"], d["scores"], json.loads(str(d["meta"]))))
    train = [c for c in clips if c[2]["split"] == "train"]
    test = [c for c in clips if c[2]["split"] == "test"]
    random.Random(0).shuffle(train)
    n_val = len(train) // 10
    val, train = train[:n_val], train[n_val:]

    Xtr, ytr, _ = make_dataset(train, args.root_motion, [1, 2, 3], True, rng, n_noisy=args.noisy, smooth=args.smooth)
    Xva, yva, _ = make_dataset(val, args.root_motion, [TEST_STEP], False, rng, smooth=args.smooth)
    Xte, yte, cte = make_dataset(test, args.root_motion, [TEST_STEP], False, rng, smooth=args.smooth)
    print(f"fenêtres : train {len(Xtr)}, val {len(Xva)}, test {len(Xte)} ; features {Xtr.shape[-1]}")

    # "other" regroupe 16 classes -> beaucoup plus d'exemples : on rééquilibre par des poids de classe
    counts = np.bincount(ytr, minlength=len(CLASSES))
    class_weight = {i: len(ytr) / (len(CLASSES) * c) for i, c in enumerate(counts)}
    print("fenêtres d'entraînement par classe :", dict(zip(CLASSES, counts.tolist())))

    model = build_model(args.model, Xtr.shape[-1])
    model.summary(print_fn=lambda s: None)
    model.compile(keras.optimizers.Adam(1e-3), "sparse_categorical_crossentropy", metrics=["accuracy"])
    name = f"{args.variant}_{args.model}{'_rm' if args.root_motion else ''}{'_noisy' if args.noisy else ''}{f'_s{args.smooth:g}' if args.smooth else ''}"
    out_dir = Path(__file__).parent / "models" / "temporal" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    model.fit(Xtr, ytr, validation_data=(Xva, yva), epochs=args.epochs, batch_size=256, verbose=0,
              class_weight=class_weight,
              callbacks=[keras.callbacks.EarlyStopping("val_loss", patience=20, restore_best_weights=True),
                         keras.callbacks.CSVLogger(str(out_dir / "train_log.csv"))])
    model.save(str(out_dir / "model.keras"))
    export_tflite(model, Xtr, out_dir, args.model)

    # ---- Évaluation sur le test officiel : par fenêtre, et par clip (moyenne des fenêtres du clip)
    p = model.predict(Xte, verbose=0)
    win_acc = float(np.mean(p.argmax(1) == yte))
    clip_pred = {k: p[cte == k].mean(0).argmax() for k in np.unique(cte)}
    clip_true = {k: yte[cte == k][0] for k in np.unique(cte)}
    clip_acc = float(np.mean([clip_pred[k] == clip_true[k] for k in clip_pred]))
    conf = np.zeros((len(CLASSES),) * 2, int)
    for t, q in zip(yte, p.argmax(1)):
        conf[t, q] += 1

    print(f"\n{name}: {model.count_params()} paramètres | test : précision fenêtre {win_acc:.3f}, clip {clip_acc:.3f}")
    print("Matrice de confusion (lignes = vérité, colonnes = prédiction) :")
    print("        " + " ".join(f"{c[:5]:>6s}" for c in CLASSES))
    for c, row in zip(CLASSES, conf):
        print(f"{c:>7s} " + " ".join(f"{v:6d}" for v in row))
    (out_dir / "results.json").write_text(json.dumps({
        "model": name, "params": int(model.count_params()), "n_features": int(Xtr.shape[-1]), "smooth": args.smooth,
        "test_window_acc": win_acc, "test_clip_acc": clip_acc, "confusion": conf.tolist(), "classes": CLASSES,
    }, indent=1))


if __name__ == "__main__":
    tf.get_logger().setLevel("ERROR")
    main()
