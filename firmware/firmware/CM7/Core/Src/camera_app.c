/* camera_app.c — see camera_app.h. Does NOT include main.h on purpose (MX_DCMI_Init conflict). */
#include <stdio.h>
#include "camera_app.h"
#include "stm32h747i_discovery_camera.h"
#include "stm32h747i_discovery_lcd.h"

/* SDRAM map: 0xD0000000 LCD image (800x480 ARGB8888 = 0x177000 bytes), then the camera image. */
#define CAMERA_FRAME_BUFFER  0xD0177000u
#define CAM_W 320
#define CAM_H 240

static volatile int frame_ready = 0;       /* set by the DCMI interrupt, read by the main loop: volatile */

/* Called by the BSP (from the DCMI interrupt) when a whole frame is in the SDRAM */
void BSP_CAMERA_FrameEventCallback(uint32_t Instance)
{
  frame_ready = 1;
}

int camera_init(void)
{
  if (BSP_CAMERA_Init(0, CAMERA_R320x240, CAMERA_PF_RGB565) != BSP_ERROR_NONE) {
    printf("[CAM] init ERREUR (capteur non detecte ?)\r\n");
    return -1;
  }
  printf("[CAM] init OK : %dx%d RGB565 -> SDRAM 0x%08lX\r\n", CAM_W, CAM_H, (unsigned long)CAMERA_FRAME_BUFFER);
  return 0;
}

/* Capture ONE frame (snapshot) by DMA, then copy it to the centre of the LCD image */
void camera_capture_and_show(void)
{
  frame_ready = 0;
  uint32_t t0 = HAL_GetTick();
  BSP_CAMERA_Start(0, (uint8_t *)CAMERA_FRAME_BUFFER, CAMERA_MODE_SNAPSHOT);
  while (!frame_ready) {                   /* the DMA fills the SDRAM while we wait */
    if (HAL_GetTick() - t0 > 500) {
      printf("[CAM] pas d'image en 500 ms\r\n");
      return;
    }
  }
  uint32_t t_capture = HAL_GetTick() - t0;

  /* RGB565 (16 bits: 5 red, 6 green, 5 blue) -> ARGB8888 (8 bits per channel) for the LCD */
  const uint16_t *cam = (const uint16_t *)CAMERA_FRAME_BUFFER;
  uint32_t *lcd = (uint32_t *)LCD_LAYER_0_ADDRESS;
  const uint32_t x0 = (800 - CAM_W) / 2, y0 = (480 - CAM_H) / 2;
  for (uint32_t y = 0; y < CAM_H; y++) {
    for (uint32_t x = 0; x < CAM_W; x++) {
      uint16_t p = cam[y * CAM_W + x];
      uint32_t r = (p >> 11) & 0x1F, g = (p >> 5) & 0x3F, b = p & 0x1F;
      lcd[(y0 + y) * 800 + (x0 + x)] = 0xFF000000u | (r << 19) | (g << 10) | (b << 3);
    }
  }
  printf("[CAM] image capturee en %lu ms, affichee\r\n", (unsigned long)t_capture);
}
