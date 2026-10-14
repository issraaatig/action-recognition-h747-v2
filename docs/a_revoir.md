# À revoir plus tard

Points mis de côté pour avancer ; à reprendre quand le pipeline tournera sur la carte.

| Sujet | Où on s'est arrêté | Pourquoi y revenir |
|---|---|---|
| Arbre des horloges (HSE → PLL → 400 MHz, prescalers AHB/APB) | réglé dans CubeMX, explication jugée difficile | comprendre avant d'ajouter caméra, écran, timers |
| Premier debug pas à pas (breakpoint ligne 163, F6, `uwTick`, registre PC) | instructions données, exercice non fait | compétence de base pour les phases 5 et 8 (HardFault, watchpoints) |
| Vérifier `SYSCLK = 400000000 Hz` dans Tera Term (RESET) | ticks vus, ligne « Hello » pas encore relue | confirmer les 400 MHz réels |
| Écran et caméra (démo d'usine effacée) | exemple ST local : `STM32Cube_FW_H7_V1.13.0/Projects/STM32H747I-DISCO/Examples/DCMI/DCMI_CaptureMode` | base de la phase 3 (capteur OV5640 du B-CAMS-OMV pris en charge par le BSP) |
| Améliorer TinyPose (cross-fitting, distillation MoveNet, QAT, vidéos maison) | voir decisions.md D9/D10 | précision d'action 0.50 sur JHMDB |
