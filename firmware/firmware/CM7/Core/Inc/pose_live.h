/* pose_live.h — live pose estimation on camera frames (implemented in X-CUBE-AI/App/app_x-cube-ai.c,
 * where the TinyPose network and its input/output buffers live).
 *
 * Two steps, so that the camera can capture the next frame while TinyPose runs:
 *   1. pose_preprocess(): reads the camera frame (SDRAM) -> TinyPose input. After this, the frame is no longer needed.
 *   2. pose_infer()     : TinyPose + decoding (internal RAM only, no SDRAM access).
 */
#ifndef POSE_LIVE_H
#define POSE_LIVE_H

#include <stdint.h>
#include "pose_postproc.h"

/* frame565: camera frame 320x240 RGB565. us_pre: measured time in microseconds. */
void pose_preprocess(const uint16_t *frame565, uint32_t *us_pre);

/* pose: 15 joints in TinyPose pixels (0..127) + scores. us_net: measured time in microseconds.
   Returns 0 if OK, -1 if the network failed. */
int  pose_infer(pose_t *pose, uint32_t *us_net);

#endif /* POSE_LIVE_H */
