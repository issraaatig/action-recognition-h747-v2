/* preprocess.h — camera image -> TinyPose input. Python reference: pc/common/preprocess.py (must stay identical).
 *
 * Input : camera frame 320x240 RGB565 (one uint16_t per pixel: 5 bits red, 6 green, 5 blue).
 * Output: 128x128x3 uint8, HWC order, channels R, G, B (the [-1, 1] scaling is done inside the model).
 * Steps : centre square crop 240x240 -> RGB565 to RGB888 -> bilinear resize to 128x128, integers only.
 */
#ifndef PREPROCESS_H
#define PREPROCESS_H

#include <stdint.h>

#define PP_CAM_W 320
#define PP_CAM_H 240
#define PP_OUT   128

void preprocess_camera_to_tinypose(const uint16_t *frame565, uint8_t *out);

#endif /* PREPROCESS_H */
