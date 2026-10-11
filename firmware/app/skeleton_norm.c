/* skeleton_norm.c — voir skeleton_norm.h. Les numéros d'étapes sont ceux de normalize.py. */
#include "skeleton_norm.h"
#include <math.h>

void skel_norm_init(skel_norm_t *n, int root_motion, float smooth)
{
  n->root_motion = root_motion;
  n->smooth = smooth;
  n->has_prev = 0;
  n->prev_scale = NORM_DEFAULT_SCALE;
}

int skel_norm_n_features(const skel_norm_t *n) { return n->root_motion ? 32 : 30; }

void skel_norm_process(skel_norm_t *n, const pose_t *pose, float *feats)
{
  float x[POSE_NUM_JOINTS], y[POSE_NUM_JOINTS];

  for (int j = 0; j < POSE_NUM_JOINTS; j++) {
    x[j] = pose->x[j];
    y[j] = pose->y[j];
    if (n->has_prev) {
      /* 1. joint peu sûr -> position de la frame précédente */
      if (pose->score[j] < NORM_SCORE_THR) { x[j] = n->prev_x[j]; y[j] = n->prev_y[j]; }
      /* lissage temporel */
      x[j] = n->smooth * n->prev_x[j] + (1.0f - n->smooth) * x[j];
      y[j] = n->smooth * n->prev_y[j] + (1.0f - n->smooth) * y[j];
    }
  }

  /* 3. échelle = distance neck–belly, jamais ~0 */
  float scale = hypotf(x[NORM_NECK] - x[NORM_BELLY], y[NORM_NECK] - y[NORM_BELLY]);
  if (scale < NORM_MIN_SCALE)
    scale = n->prev_scale;
  else if (n->has_prev)
    scale = n->smooth * n->prev_scale + (1.0f - n->smooth) * scale;

  /* 2. + 4. origine belly, division par l'échelle, aplati [x0, y0, x1, y1, ...] */
  for (int j = 0; j < POSE_NUM_JOINTS; j++) {
    feats[2 * j]     = (x[j] - x[NORM_BELLY]) / scale;
    feats[2 * j + 1] = (y[j] - y[NORM_BELLY]) / scale;
  }

  /* 5. déplacement du belly depuis la frame précédente */
  if (n->root_motion) {
    feats[30] = n->has_prev ? (x[NORM_BELLY] - n->prev_x[NORM_BELLY]) / scale : 0.0f;
    feats[31] = n->has_prev ? (y[NORM_BELLY] - n->prev_y[NORM_BELLY]) / scale : 0.0f;
  }

  for (int j = 0; j < POSE_NUM_JOINTS; j++) { n->prev_x[j] = x[j]; n->prev_y[j] = y[j]; }
  n->prev_scale = scale;
  n->has_prev = 1;
}
