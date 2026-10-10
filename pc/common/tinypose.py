"""Architecture TinyPose — partagée par 02_build_tinypose.py (benchmark) et 03_train_tinypose.py (entraînement).

Schéma (entrée 128×128) :
  image uint8 [0..255] → Rescaling vers [-1, 1] (prétraitement MobileNetV2, inclus DANS le modèle :
  la carte enverra directement les pixels bruts, pas de normalisation à coder en C)
  → MobileNetV2 α=0.35 coupé à stride 16  → 8×8×192
  → [Upsample ×2 → conv dépthwise-séparable → BN → ReLU] ×2 → 32×32×C
  → conv 1×1 → 32×32×15 heatmaps   (ou, variante "reg" : GlobalAvgPool → Dense(30) → (x, y) dans [0, 1])
"""
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

NUM_JOINTS = 15

# Dernière couche de MobileNetV2 encore à stride 16 (juste avant le bloc 13 qui passe à stride 32).
CUT_LAYER = "block_13_expand_relu"

# Variantes benchmarkées (docs/results.md) : nom -> paramètres de build_tinypose
VARIANTS = {
    #  nom            : paramètres de build_tinypose
    "A_hm128":       dict(input_size=128, head="heatmap", decoder_channels=(64, 32)),
    "B_hm96":        dict(input_size=96,  head="heatmap", decoder_channels=(64, 32)),
    "C_reg128":      dict(input_size=128, head="reg"),
    "D_hm128_light": dict(input_size=128, head="heatmap", decoder_channels=(32, 32)),
    # Variantes plus larges (backbone plus "épais") : plus précises mais plus lourdes
    "E_hm128_a050":  dict(input_size=128, head="heatmap", decoder_channels=(64, 32), alpha=0.5),
    "F_hm128_a075":  dict(input_size=128, head="heatmap", decoder_channels=(64, 32), alpha=0.75),
}


def _up_block(x, channels, name):
    # UpSampling "nearest" : opérateur simple, bien supporté par X-CUBE-AI en int8.
    x = layers.UpSampling2D(2, interpolation="nearest", name=f"{name}_up")(x)
    # Conv séparable = depthwise 3×3 + pointwise 1×1 : ~8× moins de calculs qu'une conv 3×3 classique.
    x = layers.SeparableConv2D(channels, 3, padding="same", use_bias=False, name=f"{name}_conv")(x)
    x = layers.BatchNormalization(name=f"{name}_bn")(x)
    return layers.ReLU(6.0, name=f"{name}_relu")(x)  # ReLU6 : plage bornée → meilleure quantification int8


def build_tinypose(input_size=128, head="heatmap", decoder_channels=(64, 32), alpha=0.35, weights="imagenet"):
    """Construit TinyPose.

    input_size       : 128 ou 96 (images carrées)
    head             : "heatmap" → sortie (S/4, S/4, 15) ; "reg" → sortie (30,) = 15 × (x, y) normalisés
    decoder_channels : canaux des 2 blocs de suréchantillonnage
    weights          : "imagenet" (pré-entraîné) ou None
    """
    inp = keras.Input((input_size, input_size, 3), name="image")
    x = layers.Rescaling(1 / 127.5, offset=-1.0, name="to_minus1_1")(inp)

    backbone = keras.applications.MobileNetV2(
        input_shape=(input_size, input_size, 3), alpha=alpha, include_top=False, weights=weights)
    features = keras.Model(backbone.input, backbone.get_layer(CUT_LAYER).output, name="mobilenetv2_cut")
    x = features(x)  # (S/16, S/16, 192)

    if head == "heatmap":
        for i, c in enumerate(decoder_channels):
            x = _up_block(x, c, name=f"dec{i}")
        # Pas d'activation finale : la cible est une gaussienne dans [0, 1], perte MSE.
        out = layers.Conv2D(NUM_JOINTS, 1, name="heatmaps")(x)
    elif head == "reg":
        x = layers.GlobalAveragePooling2D(name="gap")(x)
        out = layers.Dense(NUM_JOINTS * 2, activation="sigmoid", name="coords")(x)
    else:
        raise ValueError(head)

    return keras.Model(inp, out, name=f"tinypose_{head}{input_size}")
