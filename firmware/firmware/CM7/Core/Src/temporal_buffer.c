/* temporal_buffer.c — voir temporal_buffer.h */
#include "temporal_buffer.h"
#include <string.h>

void tbuf_init(tbuf_t *b, int n_features)
{
  memset(b, 0, sizeof(*b));
  b->n_features = n_features;
}

void tbuf_push(tbuf_t *b, const float *feats)
{
  memcpy(b->data[b->head], feats, (size_t)b->n_features * sizeof(float));
  b->head = (b->head + 1) % TBUF_LEN;
  if (b->count < TBUF_LEN) b->count++;
}

void tbuf_get_chronological(const tbuf_t *b, float *out)
{
  /* Buffer plein : la plus ancienne frame est à b->head.
   * Buffer partiel : les frames reçues sont aux indices 0..count-1 ; on répète la frame 0 au début. */
  const int missing = TBUF_LEN - b->count;
  const int oldest = (b->count == TBUF_LEN) ? b->head : 0;
  for (int k = 0; k < TBUF_LEN; k++) {
    int src = (k < missing) ? oldest : (oldest + k - missing) % TBUF_LEN;
    memcpy(out + k * b->n_features, b->data[src], (size_t)b->n_features * sizeof(float));
  }
}
