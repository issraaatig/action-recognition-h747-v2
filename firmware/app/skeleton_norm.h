/* skeleton_norm.h — Normalisation du squelette, copie EXACTE de pc/common/normalize.py.
 * Toute modification d'un côté doit être reportée de l'autre, puis revalidée avec tv_normalize.h.
 */
#ifndef SKELETON_NORM_H
#define SKELETON_NORM_H

#include "pose_postproc.h"

#define NORM_NECK        0
#define NORM_BELLY       1
#define NORM_SCORE_THR   0.3f
#define NORM_MIN_SCALE   1.0f    /* pixels */
#define NORM_DEFAULT_SCALE 20.0f
#define NORM_MAX_FEATURES 32

typedef struct {
  int   root_motion;     /* 0 : 30 features ; 1 : 32 features (+ déplacement du belly) */
  float smooth;          /* 0 = pas de lissage */
  int   has_prev;        /* 0 tant qu'aucune frame n'a été traitée */
  float prev_x[POSE_NUM_JOINTS], prev_y[POSE_NUM_JOINTS];
  float prev_scale;
} skel_norm_t;

void skel_norm_init(skel_norm_t *n, int root_motion, float smooth);
int  skel_norm_n_features(const skel_norm_t *n);
/* Traite UNE frame ; écrit skel_norm_n_features() floats dans feats. */
void skel_norm_process(skel_norm_t *n, const pose_t *pose, float *feats);

#endif /* SKELETON_NORM_H */
