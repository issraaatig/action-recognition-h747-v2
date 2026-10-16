/* test_blocks.c — Valide les blocs C SUR LE PC contre les vecteurs générés par Python.
 * Le même code (sauf printf -> UART) servira de test sur la carte.
 *
 * Compilation (Git Bash, depuis la racine du projet) :
 *   gcc -O2 -Wall -Ifirmware/firmware/CM7/Core/Inc -Ifirmware/firmware/CM7/Core/Inc/test_vectors \
 *       firmware/host_tests/test_blocks.c firmware/firmware/CM7/Core/Src/pose_postproc.c \
 *       firmware/firmware/CM7/Core/Src/skeleton_norm.c firmware/firmware/CM7/Core/Src/temporal_buffer.c \
 *       firmware/firmware/CM7/Core/Src/preprocess.c \
 *       -lm -o firmware/host_tests/test_blocks.exe
 *   ./firmware/host_tests/test_blocks.exe
 */
#include <math.h>
#include <stdio.h>

#include "pose_postproc.h"
#include "preprocess.h"
#include "skeleton_norm.h"
#include "temporal_buffer.h"
#include "tv_normalize.h"
#include "tv_preprocess.h"
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

  /* 4. Prétraitement caméra : RGB565 320x240 -> 128x128x3 uint8 (doit être identique au bit près) */
  static uint8_t pp_out[PP_OUT * PP_OUT * 3];
  preprocess_camera_to_tinypose(&tv_pp_input[0][0], pp_out);
  const uint8_t *pp_exp = &tv_pp_expected[0][0][0];
  int pp_err = 0, pp_ndiff = 0;
  for (int i = 0; i < PP_OUT * PP_OUT * 3; i++) {
    int d = pp_out[i] > pp_exp[i] ? pp_out[i] - pp_exp[i] : pp_exp[i] - pp_out[i];
    if (d) pp_ndiff++;
    if (d > pp_err) pp_err = d;
  }
  printf("(pretraitement : %d / %d octets differents)\n", pp_ndiff, PP_OUT * PP_OUT * 3);
  ok &= report("pretraitement camera -> 128x128", (float)pp_err);

  printf("\n%s\n", ok ? "TOUS LES BLOCS SONT CONFORMES A PYTHON" : "AU MOINS UN BLOC DIFFERE DE PYTHON");
  return ok ? 0 : 1;
}
