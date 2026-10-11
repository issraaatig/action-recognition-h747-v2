/* test_blocks.c — Valide les blocs C SUR LE PC contre les vecteurs générés par Python.
 * Le même code (sauf printf -> UART) servira de test sur la carte.
 *
 * Compilation (Git Bash, depuis la racine du projet) :
 *   gcc -O2 -Wall -Ifirmware/app -Ifirmware/test_vectors firmware/host_tests/test_blocks.c \
 *       firmware/app/pose_postproc.c firmware/app/skeleton_norm.c firmware/app/temporal_buffer.c \
 *       -lm -o firmware/host_tests/test_blocks.exe
 *   ./firmware/host_tests/test_blocks.exe
 */
#include <math.h>
#include <stdio.h>

#include "pose_postproc.h"
#include "skeleton_norm.h"
#include "temporal_buffer.h"
#include "tv_normalize.h"
#include "tv_temporal.h"
#include "tv_tinypose.h"

#define TOL 1e-4f

static float max_abs_diff(const float *a, const float *b, int n)
{
  float m = 0.0f;
  for (int i = 0; i < n; i++) { float d = fabsf(a[i] - b[i]); if (d > m) m = d; }
  return m;
}

static int report(const char *name, float err)
{
  int ok = err < TOL;
  printf("%-34s erreur max = %.3e  -> %s\n", name, err, ok ? "OK" : "ECHEC");
  return ok;
}

int main(void)
{
  int ok = 1;

  /* 1. Post-traitement TinyPose : heatmaps int8 attendues -> joints */
  pose_t pose;
  pose_decode_heatmaps(&tv_pose_expected_heatmaps[0][0][0], 32, 128,
                       TV_POSE_OUT_SCALE, TV_POSE_OUT_ZERO_POINT, &pose);
  float joints[15][2], scores[15];
  for (int j = 0; j < 15; j++) { joints[j][0] = pose.x[j]; joints[j][1] = pose.y[j]; scores[j] = pose.score[j]; }
  ok &= report("post-traitement : joints", max_abs_diff(&joints[0][0], &tv_pose_expected_joints[0][0], 30));
  ok &= report("post-traitement : scores", max_abs_diff(scores, tv_pose_expected_scores, 15));

  /* 2. Normalisation : 20 frames, avec les deux cas limites */
  skel_norm_t norm;
  skel_norm_init(&norm, TV_NORM_N_FEATURES == 32, 0.0f);
  tbuf_t buf;
  tbuf_init(&buf, TV_NORM_N_FEATURES);
  float feats[TV_NORM_N_FRAMES][TV_NORM_N_FEATURES];
  for (int t = 0; t < TV_NORM_N_FRAMES; t++) {
    pose_t p;
    for (int j = 0; j < 15; j++) {
      p.x[j] = tv_norm_joints[t][j][0];
      p.y[j] = tv_norm_joints[t][j][1];
      p.score[j] = tv_norm_scores[t][j];
    }
    skel_norm_process(&norm, &p, feats[t]);
    tbuf_push(&buf, feats[t]);
  }
  ok &= report("normalisation (20 frames)", max_abs_diff(&feats[0][0], &tv_norm_expected[0][0],
                                                          TV_NORM_N_FRAMES * TV_NORM_N_FEATURES));

  /* 3. Buffer circulaire : après 20 frames, l'ordre chronologique = les 16 dernières frames */
  float window[TBUF_LEN * TV_NORM_N_FEATURES];
  tbuf_get_chronological(&buf, window);
  ok &= report("buffer -> fenêtre chronologique", max_abs_diff(window, &tv_temp_input[0][0],
                                                                TBUF_LEN * TV_NORM_N_FEATURES));

  printf("\n%s\n", ok ? "TOUS LES BLOCS SONT CONFORMES A PYTHON" : "AU MOINS UN BLOC DIFFERE DE PYTHON");
  return ok ? 0 : 1;
}
