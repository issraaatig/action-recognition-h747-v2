/* pose_live.h — live pose estimation on one camera frame (implemented in X-CUBE-AI/App/app_x-cube-ai.c,
 * where the TinyPose network and its input/output buffers live).
 */
#ifndef POSE_LIVE_H
#define POSE_LIVE_H

#include <stdint.h>
#include "pose_postproc.h"

/* frame565: camera frame 320x240 RGB565. pose: 15 joints in TinyPose pixels (0..127) + scores.
   us_pre / us_net: measured time of the preprocessing and of TinyPose, in microseconds.
   Returns 0 if OK, -1 if the network failed. */
int pose_estimate(const uint16_t *frame565, pose_t *pose, uint32_t *us_pre, uint32_t *us_net);

#endif /* POSE_LIVE_H */
