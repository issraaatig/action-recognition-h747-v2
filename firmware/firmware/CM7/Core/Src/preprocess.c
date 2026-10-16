/* preprocess.c — see preprocess.h. Same integer arithmetic as pc/common/preprocess.py (bit-exact). */
#include "preprocess.h"

#define PP_CROP    PP_CAM_H                     /* square side: 240 */
#define PP_CROP_X0 ((PP_CAM_W - PP_CROP) / 2)   /* first column of the square: 40 */

/* Source index and weight (Q8, 0..255) for each output pixel, along one axis.
   s = (d + 0.5) * 240 / 128 - 0.5, computed exactly in integers (same as source_coords() in Python). */
static uint8_t  idx0[PP_OUT], idx1[PP_OUT], frac[PP_OUT];
static int      tables_ready = 0;

static void build_tables(void)
{
  for (int d = 0; d < PP_OUT; d++) {
    int s256 = ((2 * d + 1) * PP_CROP * 256) / (2 * PP_OUT) - 128;   /* always >= 0 for 240 -> 128 */
    int i0 = s256 >> 8;
    idx0[d] = (uint8_t)i0;
    idx1[d] = (uint8_t)(i0 + 1 < PP_CROP ? i0 + 1 : PP_CROP - 1);
    frac[d] = (uint8_t)(s256 & 0xFF);
  }
  tables_ready = 1;
}

/* One RGB565 pixel -> 8-bit R, G, B (high bits copied into low bits: 31 -> 255) */
static inline void rgb565_to_888(uint16_t p, uint32_t c[3])
{
  uint32_t r5 = (p >> 11) & 0x1F, g6 = (p >> 5) & 0x3F, b5 = p & 0x1F;
  c[0] = (r5 << 3) | (r5 >> 2);
  c[1] = (g6 << 2) | (g6 >> 4);
  c[2] = (b5 << 3) | (b5 >> 2);
}

void preprocess_camera_to_tinypose(const uint16_t *frame565, uint8_t *out)
{
  if (!tables_ready) build_tables();

  for (int y = 0; y < PP_OUT; y++) {
    const uint16_t *row0 = frame565 + idx0[y] * PP_CAM_W + PP_CROP_X0;   /* upper source line */
    const uint16_t *row1 = frame565 + idx1[y] * PP_CAM_W + PP_CROP_X0;   /* lower source line */
    uint32_t fy = frac[y];

    for (int x = 0; x < PP_OUT; x++) {
      uint32_t fx = frac[x];
      uint32_t a[3], b[3], c[3], d[3];
      rgb565_to_888(row0[idx0[x]], a);  rgb565_to_888(row0[idx1[x]], b);   /* top-left, top-right */
      rgb565_to_888(row1[idx0[x]], c);  rgb565_to_888(row1[idx1[x]], d);   /* bottom-left, bottom-right */

      for (int k = 0; k < 3; k++) {
        uint32_t top = a[k] * (256 - fx) + b[k] * fx;          /* horizontal, x256 */
        uint32_t bot = c[k] * (256 - fx) + d[k] * fx;
        /* vertical (x256 again) + 0.5 then / 65536: max 255*65536 fits easily in 32 bits */
        *out++ = (uint8_t)((top * (256 - fy) + bot * fy + 32768) >> 16);
      }
    }
  }
}
