/* temporal_buffer.h — Buffer circulaire des TBUF_LEN dernières frames de features.
 *
 * On écrit chaque nouvelle frame à la place de la plus ancienne (pas de décalage mémoire à chaque frame),
 * puis, avant d'appeler le modèle temporel, on recopie le contenu dans l'ORDRE CHRONOLOGIQUE
 * (plus ancien -> plus récent) : c'est l'ordre dans lequel le TCN a été entraîné.
 * Au démarrage (buffer pas encore plein), la première frame est répétée, comme à l'entraînement.
 */
#ifndef TEMPORAL_BUFFER_H
#define TEMPORAL_BUFFER_H

#define TBUF_LEN 8     /* = fenêtre du TCN retenu (A_hm128_tcn_noisy_w8, decisions.md D16) */
#define TBUF_MAX_FEATURES 32

typedef struct {
  float data[TBUF_LEN][TBUF_MAX_FEATURES];
  int   n_features;
  int   head;    /* indice où sera écrite la PROCHAINE frame */
  int   count;   /* nombre de frames reçues (plafonné à TBUF_LEN) */
} tbuf_t;

void tbuf_init(tbuf_t *b, int n_features);
void tbuf_push(tbuf_t *b, const float *feats);
/* Copie TBUF_LEN × n_features floats dans out, du plus ancien au plus récent. */
void tbuf_get_chronological(const tbuf_t *b, float *out);

#endif /* TEMPORAL_BUFFER_H */
