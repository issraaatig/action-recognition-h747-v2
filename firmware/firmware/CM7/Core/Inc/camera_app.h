/* camera_app.h — camera module of the application (capture + display on the LCD).
 *
 * This header deliberately does NOT include the BSP camera header: the BSP declares
 * MX_DCMI_Init(DCMI_HandleTypeDef*) while CubeMX declares MX_DCMI_Init(void) in main.h.
 * Keeping the BSP header inside camera_app.c means no file ever sees both declarations.
 */
#ifndef CAMERA_APP_H
#define CAMERA_APP_H

int  camera_init(void);               /* 0 = OK, -1 = sensor not detected */
void camera_capture_and_show(void);   /* one snapshot -> SDRAM -> centre of the LCD */

#endif /* CAMERA_APP_H */
