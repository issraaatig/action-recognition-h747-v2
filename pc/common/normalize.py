"""Normalisation du squelette : pont entre TinyPose et le TCN.

!!! RÉFÉRENCE DU CODE C : la version C (firmware) doit faire EXACTEMENT les mêmes opérations,
!!! dans le même ordre, avec les mêmes constantes. Toute modification ici doit être reportée en C.

Pour chaque frame (joints en pixels de l'image TinyPose 128×128, scores = pic des heatmaps) :
  1. joint avec score < SCORE_THR -> on reprend la position (en pixels) de la frame précédente ;
  2. origine = belly (joint 1) ;
  3. échelle = distance neck–belly ; si < MIN_SCALE -> échelle précédente (jamais de division par ~0) ;
  4. features = ((joint - belly) / échelle) aplatis : [x0, y0, x1, y1, ..., x14, y14] -> 30 floats ;
  5. (option root_motion) + déplacement du belly depuis la frame précédente / échelle -> 2 floats de plus.
     Sans cette option, un saut (tout le corps monte) est invisible : seule la forme du corps reste.

Option smooth (0 = désactivé) : entre 1. et 2., lissage exponentiel des joints
     j_lissé = smooth × j_lissé_précédent + (1 − smooth) × j
  Raison : TinyPose « tremble » d'environ 1 px d'une frame à l'autre (pas de la heatmap), soit ~0.06 en unités
  normalisées — autant que le vrai mouvement d'un poignet entre deux frames. L'échelle est lissée de la même façon.
"""
import numpy as np

NECK, BELLY = 0, 1
SCORE_THR = 0.3
MIN_SCALE = 1.0       # pixels (dans l'image 128×128) ; en dessous, l'échelle est considérée nulle
DEFAULT_SCALE = 20.0  # échelle utilisée si la toute première frame a une échelle nulle
LR_PAIRS = [(3, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14)]


class SkeletonNormalizer:
    """Version « avec état » : traite les frames une par une, exactement comme la carte."""

    def __init__(self, root_motion=False, smooth=0.0):
        self.root_motion = root_motion
        self.smooth = smooth
        self.reset()

    @property
    def n_features(self):
        return 32 if self.root_motion else 30

    def reset(self):
        self.prev_joints = None   # (15, 2) pixels, après remplacement des joints peu sûrs
        self.prev_scale = DEFAULT_SCALE

    def __call__(self, joints, scores):
        j = np.asarray(joints, np.float32).copy()
        # 1. joints peu sûrs -> valeur précédente (rien à reprendre pour la toute première frame)
        if self.prev_joints is not None:
            low = np.asarray(scores) < SCORE_THR
            j[low] = self.prev_joints[low]
            # lissage temporel (sur les positions déjà corrigées)
            j = self.smooth * self.prev_joints + (1 - self.smooth) * j
        # 3. échelle
        scale = float(np.hypot(*(j[NECK] - j[BELLY])))
        if scale < MIN_SCALE:
            scale = self.prev_scale
        elif self.prev_joints is not None:
            scale = self.smooth * self.prev_scale + (1 - self.smooth) * scale
        # 2. + 4. recentrage et mise à l'échelle
        feats = ((j - j[BELLY]) / scale).reshape(-1)
        # 5. mouvement global du bassin
        if self.root_motion:
            d = (j[BELLY] - self.prev_joints[BELLY]) / scale if self.prev_joints is not None else np.zeros(2)
            feats = np.concatenate([feats, d.astype(np.float32)])
        self.prev_joints, self.prev_scale = j, scale
        return feats.astype(np.float32)


def normalize_sequence(joints, scores, root_motion=False, smooth=0.0):
    """(T, 15, 2), (T, 15) -> (T, 30 ou 32), en appliquant le normaliseur frame par frame."""
    norm = SkeletonNormalizer(root_motion, smooth)
    return np.stack([norm(j, s) for j, s in zip(joints, scores)])


def mirror_features(feats):
    """Miroir horizontal de features déjà normalisées (augmentation du TCN) :
    x -> -x (l'origine est le belly, donc pas besoin de la largeur d'image) + échange gauche/droite."""
    f = feats.copy()
    body = f[..., :30].reshape(*f.shape[:-1], 15, 2)
    body[..., 0] *= -1
    for r, l in LR_PAIRS:
        body[..., [r, l], :] = body[..., [l, r], :]
    f[..., :30] = body.reshape(*f.shape[:-1], 30)
    if f.shape[-1] == 32:
        f[..., 30] *= -1  # déplacement horizontal du bassin inversé aussi
    return f
