/* camera_app.c — see camera_app.h. Does NOT include main.h on purpose (MX_DCMI_Init conflict). */
#include <stdio.h>
#include "camera_app.h"
#include "stm32h747i_discovery_camera.h"
#include "stm32h747i_discovery_lcd.h"
#include "stm32_lcd.h"
#include "pose_live.h"

/* SDRAM map: 0xD0000000 LCD image (800x480 ARGB8888 = 0x177000 bytes), then the camera image. */
#define CAMERA_FRAME_BUFFER  0xD0177000u
#define CAM_W 320
#define CAM_H 240

static volatile int frame_ready = 0;       /* set by the DCMI interrupt, read by the main loop: volatile */

/* Called by the BSP (from the DCMI interrupt) when a whole frame is in the SDRAM.
   The capture is paused HERE, right at the end of the frame: otherwise the next frame would start
   overwriting this one (circular DMA) before the main loop has read it. The main loop resumes it. */
void BSP_CAMERA_FrameEventCallback(uint32_t Instance)
{
  BSP_CAMERA_Suspend(0);
  frame_ready = 1;
}

/* Called by the BSP (from the DCMI interrupt) on an error: overrun (FIFO full) or DMA error.
   After an error the HAL stops the DMA: no more frames until the camera is restarted. */
static volatile uint32_t cam_errors = 0;
void BSP_CAMERA_ErrorCallback(uint32_t Instance)
{
  cam_errors++;
}

int camera_init(void)
{
  if (BSP_CAMERA_Init(0, CAMERA_R320x240, CAMERA_PF_RGB565) != BSP_ERROR_NONE) {
    printf("[CAM] init ERREUR (capteur non detecte ?)\r\n");
    return -1;
  }
  printf("[CAM] init OK : %dx%d RGB565 -> SDRAM 0x%08lX\r\n", CAM_W, CAM_H, (unsigned long)CAMERA_FRAME_BUFFER);
  BSP_CAMERA_Start(0, (uint8_t *)CAMERA_FRAME_BUFFER, CAMERA_MODE_CONTINUOUS);
  return 0;
}

/* Where the camera image is drawn on the 800x480 screen (centred) */
#define SCREEN_X0 ((800 - CAM_W) / 2)
#define SCREEN_Y0 ((480 - CAM_H) / 2)

/* TinyPose pixel (0..127, inside the centre 240x240 square of the camera image) -> screen pixel.
   Same geometry as preprocess.c: x 128 -> 240 (x 240/128) then + 40 (crop), then + image offset. */
static uint32_t to_screen_x(float x) { return SCREEN_X0 + (CAM_W - CAM_H) / 2 + (uint32_t)(x * CAM_H / 128.0f); }
static uint32_t to_screen_y(float y) { return SCREEN_Y0 + (uint32_t)(y * CAM_H / 128.0f); }

/* Skeleton segments between JHMDB joints: 0 neck, 1 belly, 2 face, 3 R_shoulder, 4 L_shoulder, 5 R_hip, 6 L_hip,
   7 R_elbow, 8 L_elbow, 9 R_knee, 10 L_knee, 11 R_wrist, 12 L_wrist, 13 R_ankle, 14 L_ankle.
   Colour: yellow = body axis, red = right side, green = left side. */
static const uint8_t bones[14][2] = {
  {2, 0}, {0, 1},                       /* face-neck, neck-belly */
  {0, 3}, {3, 7}, {7, 11},              /* right arm */
  {0, 4}, {4, 8}, {8, 12},              /* left arm */
  {1, 5}, {5, 9}, {9, 13},              /* right leg */
  {1, 6}, {6, 10}, {10, 14},            /* left leg */
};
static const uint32_t bone_color[14] = {
  UTIL_LCD_COLOR_YELLOW, UTIL_LCD_COLOR_YELLOW,
  UTIL_LCD_COLOR_RED, UTIL_LCD_COLOR_RED, UTIL_LCD_COLOR_RED,
  UTIL_LCD_COLOR_GREEN, UTIL_LCD_COLOR_GREEN, UTIL_LCD_COLOR_GREEN,
  UTIL_LCD_COLOR_RED, UTIL_LCD_COLOR_RED, UTIL_LCD_COLOR_RED,
  UTIL_LCD_COLOR_GREEN, UTIL_LCD_COLOR_GREEN, UTIL_LCD_COLOR_GREEN,
};
#define MIN_SCORE 0.3f                  /* same threshold as the normalisation (CLAUDE.md §7) */

static void draw_skeleton(const pose_t *p)
{
  for (int i = 0; i < 14; i++) {
    int a = bones[i][0], b = bones[i][1];
    if (p->score[a] < MIN_SCORE || p->score[b] < MIN_SCORE) continue;   /* unsure joint: no segment */
    UTIL_LCD_DrawLine(to_screen_x(p->x[a]), to_screen_y(p->y[a]),
                      to_screen_x(p->x[b]), to_screen_y(p->y[b]), bone_color[i]);
  }
  for (int j = 0; j < POSE_NUM_JOINTS; j++)
    if (p->score[j] >= MIN_SCORE)
      UTIL_LCD_FillCircle(to_screen_x(p->x[j]), to_screen_y(p->y[j]), 3, UTIL_LCD_COLOR_WHITE);
}

/* One step of the live loop (the camera captures frame N+1 while TinyPose works on frame N):

   wait for frame N (the interrupt has paused the camera) -> copy it to the screen -> preprocess it
   -> resume the camera (frame N+1 is captured from now on) -> TinyPose on N -> draw the skeleton

   Everything that READS the frame or makes heavy SDRAM writes (copy, preprocessing, text) is done while the
   camera is paused: the frame does not change under our feet and the SDRAM bus is free (no DCMI overrun).
   TinyPose only uses the internal AXI SRAM, so it can run in parallel with the capture. */
void camera_capture_and_show(void)
{
  static uint32_t n_frames = 0, t_last_report = 0, sum_wait = 0, sum_copy = 0, sum_pre = 0, sum_net = 0;

  uint32_t t0 = HAL_GetTick();
  while (!frame_ready) {                   /* the DMA fills the SDRAM while we wait */
    if (HAL_GetTick() - t0 > 500) {
      /* After a DCMI error the HAL has stopped the DMA for good: restart the capture instead of waiting forever */
      printf("[CAM] pas d'image en 500 ms (erreurs DCMI : %lu) -> redemarrage camera\r\n", (unsigned long)cam_errors);
      BSP_CAMERA_Stop(0);
      frame_ready = 0;
      BSP_CAMERA_Start(0, (uint8_t *)CAMERA_FRAME_BUFFER, CAMERA_MODE_CONTINUOUS);
      return;
    }
  }
  frame_ready = 0;                         /* frame consumed: the next one will set it again */
  uint32_t t1 = HAL_GetTick();

  /* RGB565 (16 bits: 5 red, 6 green, 5 blue) -> ARGB8888 (8 bits per channel) for the LCD */
  const uint16_t *cam = (const uint16_t *)CAMERA_FRAME_BUFFER;
  uint32_t *lcd = (uint32_t *)LCD_LAYER_0_ADDRESS;
  for (uint32_t y = 0; y < CAM_H; y++) {
    for (uint32_t x = 0; x < CAM_W; x++) {
      uint16_t p = cam[y * CAM_W + x];
      uint32_t r = (p >> 11) & 0x1F, g = (p >> 5) & 0x3F, b = p & 0x1F;
      lcd[(SCREEN_Y0 + y) * 800 + (SCREEN_X0 + x)] = 0xFF000000u | (r << 19) | (g << 10) | (b << 3);
    }
  }
  uint32_t t2 = HAL_GetTick();

  uint32_t us_pre = 0, us_net = 0;
  pose_preprocess(cam, &us_pre);           /* last read of the frame: after this the camera buffer is free */

  /* Statistics once per second: images per second and where the time goes (drawn while the camera is paused) */
  n_frames++;
  sum_wait += t1 - t0; sum_copy += t2 - t1; sum_pre += us_pre;
  uint32_t now = HAL_GetTick();
  if (now - t_last_report >= 1000) {
    uint32_t dt = now - t_last_report;
    uint32_t fps10 = n_frames * 10000 / dt;                  /* images per second x10 (no float printf) */
    printf("[LIVE] %lu.%lu img/s | attente %lu ms, copie ecran %lu ms, pretraitement %lu ms, tinypose %lu ms"
           " | erreurs DCMI %lu\r\n",
           fps10 / 10, fps10 % 10, sum_wait / n_frames, sum_copy / n_frames, sum_pre / n_frames / 1000,
           sum_net / n_frames / 1000, (unsigned long)cam_errors);
    char txt[24];
    snprintf(txt, sizeof txt, "%lu.%lu img/s", fps10 / 10, fps10 % 10);
    UTIL_LCD_FillRect(0, 400, 800, 30, UTIL_LCD_COLOR_BLUE);  /* erase the previous text */
    UTIL_LCD_DisplayStringAt(0, 403, (uint8_t *)txt, CENTER_MODE);
    n_frames = sum_wait = sum_copy = sum_pre = sum_net = 0;
    t_last_report = now;
  }

  BSP_CAMERA_Resume(0);                    /* frame N+1 is captured from now on, in parallel with TinyPose */

  pose_t pose;
  if (pose_infer(&pose, &us_net) == 0)
    draw_skeleton(&pose);                  /* small SDRAM writes during the capture: watch the DCMI error count */
  sum_net += us_net;
}
