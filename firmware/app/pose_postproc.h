/* pose_postproc.h — Heatmaps TinyPose (int8) -> 15 joints (x, y) + scores.
 * Copie exacte de pc/common/heatmap.py::decode_heatmaps (voir la convention de pixel là-bas).
 */
#ifndef POSE_POSTPROC_H
#define POSE_POSTPROC_H

#include <stdint.h>

#define POSE_NUM_JOINTS 15

typedef struct {
  float x[POSE_NUM_JOINTS];      /* pixels de l'image d'entrée TinyPose (0..input_size-1) */
  float y[POSE_NUM_JOINTS];
  float score[POSE_NUM_JOINTS];  /* valeur du pic, déquantifiée (≈ 0..1) */
} pose_t;

/* hm : sortie int8 du réseau, disposition HWC (hm_size × hm_size × 15), comme dans le .tflite.
 * scale / zero_point : paramètres de quantification de la sortie (rapport X-CUBE-AI ou .tflite). */
void pose_decode_heatmaps(const int8_t *hm, int hm_size, int input_size,
                          float scale, int32_t zero_point, pose_t *out);

#endif /* POSE_POSTPROC_H */
