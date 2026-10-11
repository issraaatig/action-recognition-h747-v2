/* pose_postproc.c — voir pose_postproc.h.
 *
 * Astuce : la déquantification  réel = scale × (q − zero_point)  est CROISSANTE (scale > 0).
 * L'argmax et les comparaisons entre voisins peuvent donc se faire directement sur les int8 :
 * on ne convertit en float que le pic (pour le score). C'est plus rapide et ça donne le même résultat.
 */
#include "pose_postproc.h"

static float sign_i(int d) { return (d > 0) ? 1.0f : (d < 0) ? -1.0f : 0.0f; }

void pose_decode_heatmaps(const int8_t *hm, int hm_size, int input_size,
                          float scale, int32_t zero_point, pose_t *out)
{
  const float stride = (float)input_size / (float)hm_size;
  const int C = POSE_NUM_JOINTS;
#define HM(v, u, j) hm[((v) * hm_size + (u)) * C + (j)]   /* indexation HWC */

  for (int j = 0; j < C; j++) {
    /* 1. argmax (en cas d'égalité, on garde le PREMIER, comme numpy.argmax) */
    int best_u = 0, best_v = 0;
    int8_t best = HM(0, 0, j);
    for (int v = 0; v < hm_size; v++) {
      for (int u = 0; u < hm_size; u++) {
        if (HM(v, u, j) > best) { best = HM(v, u, j); best_u = u; best_v = v; }
      }
    }
    /* 2. raffinement d'un quart de cellule vers le voisin le plus fort */
    float u = (float)best_u, v = (float)best_v;
    if (best_u > 0 && best_u < hm_size - 1)
      u += 0.25f * sign_i(HM(best_v, best_u + 1, j) - HM(best_v, best_u - 1, j));
    if (best_v > 0 && best_v < hm_size - 1)
      v += 0.25f * sign_i(HM(best_v + 1, best_u, j) - HM(best_v - 1, best_u, j));
    /* 3. cellule -> pixel d'entrée */
    out->x[j] = (u + 0.5f) * stride - 0.5f;
    out->y[j] = (v + 0.5f) * stride - 0.5f;
    out->score[j] = scale * (float)(best - zero_point);
  }
#undef HM
}
