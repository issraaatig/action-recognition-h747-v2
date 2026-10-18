# Récapitulatif — SDRAM, écran, caméra (Phase 3)

> Ce qu'on a fait pour avoir l'image de la caméra en direct sur l'écran : configuration, code, registres,
> interruptions, et les bugs rencontrés. (TinyPose / TCN : hors de ce document.)

---

## 0. Vue d'ensemble

```
 Capteur OV5640 ──(8 bits + PCLK/HSYNC/VSYNC)──► DCMI ──► DMA2 Stream3 ──► SDRAM 0xD0177000 (image 320×240 RGB565)
   ▲ réglages par I2C4                                                         │
   │                                                    CPU : copie + conversion RGB565 → ARGB8888
   │                                                                           ▼
   │                                                      SDRAM 0xD0000000 (image écran 800×480 ARGB8888)
   │                                                                           │ lue en continu par le LTDC
   │                                                                           ▼
   └── BSP_CAMERA_Init()                                LTDC ──► DSI HOST ──► écran 800×480 (NT35510/OTM8009A)
```

**Carte mémoire de la SDRAM (32 Mo à partir de 0xD0000000)** :

| Adresse | Taille | Contenu |
|---|---|---|
| `0xD0000000` | 800 × 480 × 4 = `0x177000` (1,5 Mo) | image de l'écran (layer 0 du LTDC), ARGB8888 |
| `0xD0177000` | 320 × 240 × 2 = `0x25800` (150 Ko) | image de la caméra, RGB565 |

**Principe commun aux trois parties** : on utilise les **pilotes BSP de ST** (Board Support Package : code déjà écrit
pour cette carte), copiés dans `CM7/Core`. CubeMX sert seulement à activer les périphériques pour ajouter les fichiers
HAL au projet, avec **« Generate Code » décoché** (ou « Do Not Generate Function Call ») : c'est le BSP qui initialise.

---

## 1. La SDRAM externe (32 Mo, IS42S32800J, contrôleur FMC)

### Pourquoi
La RAM interne (~1 Mo) ne suffit pas pour deux images (1,5 Mo + 150 Ko). La SDRAM de la carte est vue par le CPU
comme de la mémoire normale à partir de `0xD0000000` (banque 2 du FMC).

### Configuration
- **CubeMX** : FMC → SDRAM2 (SDCKE1 + SDNE1), 4 banques, adresses 12 bits, données 32 bits, byte enable.
  Advanced Settings : **« Do Not Generate Function Call »** pour `MX_FMC_Init` (d'où le warning
  `MX_FMC_Init defined but not used`, normal).
- **Fichiers BSP ajoutés** : `stm32h747i_discovery_sdram.c/.h`, composant `is42s32800j.c/.h`,
  `is42s32800j_conf.h`, `stm32h747i_discovery_conf.h`, `stm32h747i_discovery_errno.h`.
- **MPU** (protection mémoire du Cortex-M7, CubeMX → CORTEX_M7) :

| Région | Base | Taille | Accès | Cache | Rôle |
|---|---|---|---|---|---|
| 0 | `0x00000000` | 4 Go, sous-régions `0x87` désactivées | **NO_ACCESS** | — | interdit `0x60000000–0xDFFFFFFF` (zone FMC) par défaut |
| 1 | `0xD0000000` | 32 Mo | **FULL_ACCESS** | **non cacheable**, non bufferable | ré-autorise la SDRAM |

  Pourquoi **non cacheable** (décision D15) : la caméra (DMA) écrit en SDRAM sans passer par le cache du CPU.
  Avec le cache, le CPU pourrait relire une **ancienne copie** de l'image. Prix : accès CPU plus lents.

### Code (`main.c`, zone USER CODE 0)
```c
static void sdram_test(void)
{
  if (BSP_SDRAM_Init(0) != BSP_ERROR_NONE) { printf("[SDRAM] init ERREUR\r\n"); return; }
  volatile uint32_t *mem = (volatile uint32_t *)SDRAM_DEVICE_ADDR;   /* 0xD0000000 */
  const uint32_t n = SDRAM_DEVICE_SIZE / 4;                          /* 8 M mots de 32 bits */
  for (uint32_t i = 0; i < n; i++) mem[i] = i ^ 0xA5A5A5A5u;          /* écriture d'un motif */
  uint32_t errors = 0;
  for (uint32_t i = 0; i < n; i++) if (mem[i] != (i ^ 0xA5A5A5A5u)) errors++;   /* relecture */
  printf("[SDRAM] %lu mots testes, %lu erreurs\r\n", (unsigned long)n, (unsigned long)errors);
}
```
- `volatile` : oblige le compilateur à vraiment écrire puis relire la mémoire (sinon il pourrait « deviner » le résultat).
- Motif `i ^ 0xA5A5A5A5` : chaque mot est différent → détecte aussi une erreur d'adressage (deux adresses qui se recouvrent).
- Résultat : **8 388 608 mots, 0 erreur** (~0,9 s).

### Bug rencontré : MemManage à la première écriture
| | |
|---|---|
| Symptôme | `[SDRAM] init OK` puis plus rien, LED arrêtée |
| Registres lus | `XPSR = 0x41000004` → champ **IPSR = 4 = MemManage** ; `CFSR (0xE000ED28) = 0x82` → **DACCVIOL** (bit 1, accès donnée interdit) + **MMARVALID** (bit 7) ; `MMFAR (0xE000ED34) = 0xD0000000` → l'adresse fautive |
| Cause 1 | la région MPU 0 interdit toute la zone FMC |
| Cause 2 | la région 1 ajoutée avait **hérité** de `NO_ACCESS` : CubeMX n'écrit que les champs modifiés, et la même variable `MPU_InitStruct` sert pour les deux régions |
| Correction | région 1 avec **ALL ACCESS PERMITTED** réglé explicitement |
| Leçon | IPSR + CFSR + MMFAR donnent la cause d'une faute en 3 lectures ; quand rien ne change après une correction, relire le **code généré** |

---

## 2. L'écran (DSI 800×480 : LTDC + DSI HOST + DMA2D)

### Les trois blocs
| Bloc | Rôle |
|---|---|
| **LTDC** | lit l'image en SDRAM (`0xD0000000`) en continu et produit les pixels au rythme de l'écran (~60 images/s, ~90 Mo/s) |
| **DSI HOST** | transporte ces pixels vers la dalle par le lien série MIPI-DSI ; envoie aussi les commandes d'initialisation de la dalle |
| **DMA2D** | « accélérateur graphique » : remplissage de rectangles, copies, conversions de format (utilisé par `UTIL_LCD_FillRect`, `Clear`…) |

### Configuration
- **CubeMX** : LTDC « RGB888 (24 bits) — DSI mode », DSIHOST « Video Mode », DMA2D ; **Generate Code décoché** pour les trois.
- **Horloge du pixel** : PLL3 = M 5 / N 132 / R 24 → **27,5 MHz** (horloge LTDC).
- **Fichiers BSP** : `stm32h747i_discovery_lcd.c/.h`, `stm32h747i_discovery_bus.c/.h`, `stm32_lcd.c/.h` (texte et dessin),
  composants `otm8009a`, `nt35510` (la carte peut avoir l'une ou l'autre dalle : **détection automatique**), `adv7533`,
  et le dossier `Fonts` (exclu de la compilation : `stm32_lcd.c` inclut directement les polices).

### Code (`main.c`)
```c
static void lcd_test(void)
{
  if (BSP_LCD_Init(0, LCD_ORIENTATION_LANDSCAPE) != BSP_ERROR_NONE) { printf("[LCD] init ERREUR\r\n"); return; }
  UTIL_LCD_SetFuncDriver(&LCD_Driver);       /* stm32_lcd dessine à travers le BSP */
  UTIL_LCD_Clear(UTIL_LCD_COLOR_BLUE);
  UTIL_LCD_SetBackColor(UTIL_LCD_COLOR_BLUE);
  UTIL_LCD_SetTextColor(UTIL_LCD_COLOR_WHITE);
  UTIL_LCD_SetFont(&Font24);
  UTIL_LCD_DisplayStringAt(0, 20, (uint8_t *)"Action recognition H747", CENTER_MODE);
}
```

### Interruptions de l'écran (`stm32h7xx_it.c`, USER CODE 1)
`BSP_LCD_Init` **active** les interruptions LTDC, DSI et DMA2D dans le NVIC. Si aucune fonction `XXX_IRQHandler` n'existe,
le CPU part dans `Default_Handler` (boucle infinie) au premier événement. On les redirige vers la HAL :
```c
void LTDC_IRQHandler(void)  { HAL_LTDC_IRQHandler(&hlcd_ltdc); }
void DSI_IRQHandler(void)   { HAL_DSI_IRQHandler(&hlcd_dsi); }
void DMA2D_IRQHandler(void) { HAL_DMA2D_IRQHandler(&hlcd_dma2d); }
```
(`hlcd_ltdc`, `hlcd_dsi`, `hlcd_dma2d` : les « handles » déclarés par le BSP, d'où `#include "stm32h747i_discovery_lcd.h"`.)

### Problèmes rencontrés
- **Fichiers manquants à la compilation** (`sdram.h`, `stm32_lcd.c` introuvable…) : chemins des fichiers BSP ; on a copié
  tout le BSP dans `CM7/Core` au lieu de pointer vers `C:/Utilities/...` (le projet exemple ST importé cassait ces chemins).
- **« Update conflict » dans CubeIDE** : fichier modifié sur le disque et dans l'éditeur → répondre **No** (garder le disque).
- Résultat : `[LCD] init OK : 800 x 480 pixels`, fond bleu + titre.

---

## 3. La caméra (B-CAMS-OMV : OV5640, DCMI + DMA2 Stream3)

### Les blocs
| Bloc | Rôle |
|---|---|
| **OV5640** | le capteur ; réglé (résolution, format) par le bus **I2C4** ; envoie les pixels sur 8 fils + 3 signaux de synchro |
| **DCMI** | interface caméra du STM32 : reçoit les octets au rythme de **PCLK**, repère lignes (**HSYNC**) et images (**VSYNC**), range dans un petit FIFO |
| **DMA2 Stream3** | vide le FIFO du DCMI vers la SDRAM, sans le CPU (153 600 octets = **38 400 mots = `0x9600`** par image) |

### Configuration
- **CubeMX** : DCMI « Slave 8 bits External Synchro », **attribué au seul Cortex-M7** (retiré du M4), **Generate Code décoché**
  pour `MX_DCMI_Init` (voir bug 1).
- **Fichiers BSP** : `stm32h747i_discovery_camera.c/.h`, composants `ov5640`, `ov9655`, `camera.h`.
- **Nouveau module** `camera_app.c/.h` : tout le code caméra est isolé ici. Il n'inclut **pas** `main.h`, car `main.h`
  déclare `MX_DCMI_Init(void)` et le BSP `MX_DCMI_Init(DCMI_HandleTypeDef*)` → conflit de types si un fichier voit les deux.

### Interruptions de la caméra (`stm32h7xx_it.c`)
```c
void BSP_CAMERA_IRQHandler(uint32_t Instance);       /* déclarées à la main : pas d'include du header caméra */
void BSP_CAMERA_DMA_IRQHandler(uint32_t Instance);   /* (même conflit MX_DCMI_Init) */

void DCMI_IRQHandler(void)         { BSP_CAMERA_IRQHandler(0); }      /* fin d'image, erreurs, overrun */
void DMA2_Stream3_IRQHandler(void) { BSP_CAMERA_DMA_IRQHandler(0); }  /* fin de transfert DMA */
```
Le BSP appelle ensuite **nos callbacks** (fonctions `__weak` qu'on redéfinit dans `camera_app.c`) :
```c
void BSP_CAMERA_FrameEventCallback(uint32_t Instance)   /* une image complète est en SDRAM */
{
  BSP_CAMERA_Suspend(0);   /* pause tout de suite : sinon l'image suivante écraserait celle-ci (DMA circulaire) */
  frame_ready = 1;         /* variable volatile lue par la boucle principale */
}
void BSP_CAMERA_ErrorCallback(uint32_t Instance) { cam_errors++; }   /* overrun ou erreur DMA */
```

**Vérification dans le NVIC** (registres `ISER`, un bit par interruption activée) :

| Registre | Valeur lue | Bits → interruptions |
|---|---|---|
| ISER1 `0xE000E104` | `0x08000000` | bit 27 → IRQ 59 = **DMA2_Stream3** |
| ISER2 `0xE000E108` | `0x05004000` | bit 14 → IRQ 78 = **DCMI** ; bit 24 → IRQ 88 = **LTDC** ; bit 26 → IRQ 90 = **DMA2D** |
| ISER3 `0xE000E10C` | `0x0C000000` | bit 27 → IRQ 123 = **DSI** ; bit 26 → IRQ 122 = **MDMA** |

⚠️ L'**MDMA** est activé dans le NVIC par `BSP_SDRAM_Init` (pour ses fonctions de copie par DMA), mais nous n'avons
**pas** de `MDMA_IRQHandler`. Sans danger tant qu'on ne lance aucun transfert MDMA ; sinon → `Default_Handler`
(boucle infinie). C'est exactement le piège évité pour LTDC / DSI / DMA2D / DCMI.

### Code de la boucle (`camera_app.c`, version finale de la phase 3)
```c
int camera_init(void)
{
  if (BSP_CAMERA_Init(0, CAMERA_R320x240, CAMERA_PF_RGB565) != BSP_ERROR_NONE) return -1;
  BSP_CAMERA_Start(0, (uint8_t *)CAMERA_FRAME_BUFFER, CAMERA_MODE_CONTINUOUS);   /* démarrée UNE fois */
  return 0;
}

void camera_capture_and_show(void)
{
  uint32_t t0 = HAL_GetTick();
  while (!frame_ready) {                         /* attendre l'interruption de fin d'image */
    if (HAL_GetTick() - t0 > 500) {              /* plus rien depuis 500 ms : la HAL a arrêté le DMA */
      BSP_CAMERA_Stop(0);                        /* -> on redémarre la caméra au lieu d'attendre à vie */
      frame_ready = 0;
      BSP_CAMERA_Start(0, (uint8_t *)CAMERA_FRAME_BUFFER, CAMERA_MODE_CONTINUOUS);
      return;
    }
  }
  frame_ready = 0;                               /* image consommée */

  /* copie vers l'écran (caméra en pause) : RGB565 -> ARGB8888 */
  const uint16_t *cam = (const uint16_t *)CAMERA_FRAME_BUFFER;
  uint32_t *lcd = (uint32_t *)LCD_LAYER_0_ADDRESS;
  for (uint32_t y = 0; y < 240; y++)
    for (uint32_t x = 0; x < 320; x++) {
      uint16_t p = cam[y * 320 + x];
      uint32_t r = (p >> 11) & 0x1F, g = (p >> 5) & 0x3F, b = p & 0x1F;   /* 5 + 6 + 5 bits */
      lcd[(120 + y) * 800 + (240 + x)] = 0xFF000000u | (r << 19) | (g << 10) | (b << 3);
    }
  /* ... texte « x img/s » (toujours caméra en pause) ... */
  BSP_CAMERA_Resume(0);                          /* l'image suivante est capturée à partir d'ici */
}
```
Règle retenue : **tout ce qui lit l'image ou écrit beaucoup en SDRAM se fait caméra en pause.**

### Registres caméra lus pendant le debug
(`STM32_Programmer_CLI -c port=SWD mode=HOTPLUG ap=0 shared -r32 <adresse> <taille>` : lecture **sans arrêter** la carte)

**DCMI** (base `0x48020000`)

| Registre | Offset | Bits utiles |
|---|---|---|
| CR | 0x00 | b0 **CAPTURE**, b1 **CM** (0 = continu, 1 = snapshot), b5 PCKPOL, b6 HSPOL, b7 VSPOL, b10-11 EDM (largeur), b14 **ENABLE** |
| SR | 0x04 | b0 HSYNC, b1 VSYNC, b2 FIFO non vide |
| RIS | 0x08 | événements bruts : b0 FRAME, b1 **OVR**, b2 ERR, b3 VSYNC, b4 LINE |
| IER | 0x0C | interruptions activées (mêmes bits que RIS) |
| DR | 0x28 | registre de données lu par le DMA |

**DMA2 Stream3** (base `0x40020458`)

| Registre | Offset | Bits utiles |
|---|---|---|
| CR | 0x00 | b0 **EN**, b2 TEIE, b4 TCIE, b6-7 DIR, b8 **CIRC**, b10 MINC, b11-12 PSIZE, b13-14 MSIZE, b16-17 PL (priorité) |
| NDTR | 0x04 | mots **restant** à transférer (`0x9600` = rien n'a bougé) |
| PAR | 0x08 | adresse du périphérique (doit être `0x48020028` = DCMI→DR) |
| M0AR | 0x0C | adresse mémoire (`0xD0177000`) |

Exemple : `CR = 0x00025517` = EN + TEIE + TCIE + DMEIE + CIRC + MINC + PSIZE/MSIZE 32 bits + priorité haute.

**Handle HAL `hcamera_dcmi`** (variable du BSP en RAM ; adresse trouvée dans le fichier `.map`) :
`State` (4 = ERROR) et **`ErrorCode`** : `0x01` OVR, `0x02` SYNC, `0x20` TIMEOUT, `0x40` DMA (cumulatif).

### Bugs de la caméra (dans l'ordre)
| # | Symptôme | Ce qu'on a lu | Cause | Correction |
|---|---|---|---|---|
| 1 | `init OK` puis « pas d'image » | DCMI CR = 0 ; DMA NDTR = `0x9600` ; **PAR = `0x00000028`** | CubeMX avait régénéré un `MX_DCMI_Init(void)` normal dans `main.c`, qui **remplace au linkage** la fonction `__weak` du BSP → le handle du BSP restait vide (`Instance = NULL`, d'où NULL + 0x28) | Generate Code décoché ; vérifié dans le `.map` que `MX_DCMI_Init` vient de `stm32h747i_discovery_camera.o` |
| 2 | 1 image puis plus rien (snapshot) | DCMI **IER = 0** | en snapshot, la HAL coupe les interruptions à la fin de l'image et ne les remet que dans `HAL_DCMI_Init` | mode **continu**, démarré une seule fois |
| 2b | « capturée en 0 ms » | — | `frame_ready = 0` écrit **dans** le `while (!frame_ready)` → jamais remis à 0 | `frame_ready = 0` après la boucle |
| 3 | en continu : 1 image puis rien | DMA **EN = 0** après 67 mots ; `ErrorCode = 0x41` (OVR + DMA) | **overrun** : copie CPU + LTDC + DMA caméra sur le même bus SDRAM → le FIFO du DCMI déborde | pause pendant la copie (Suspend / Resume) + compteur d'erreurs |
| 4 | panne après ~28 s | (raisonnement) | texte « x img/s » (DMA2D) dessiné **après** la reprise de la caméra | `Resume` à la toute fin + redémarrage automatique |
| 5 | (ouvert) erreurs fréquentes en -O2, rares en -O0 | `ErrorCode = 0x61` (OVR + TIMEOUT + DMA) | course de **timing** entre la pause (IRQ) et la reprise (boucle) | -O0 pour l'instant ; vraie solution : **double buffer DMA** (phase 9) |

### Autres réglages / pièges vus en route
- **Le M4 doit être flashé aussi** (Run CM4 puis CM7) : sinon le M7 reste bloqué dans `Error_Handler` au démarrage
  (synchronisation de boot entre cœurs). Diagnostic : PC = `Error_Handler`, LR → `main.c:108`, `PRIMASK = 1`.
- **Le DCMI ne doit être attribué qu'au M7** : sinon le `main.c` du M4 l'initialise aussi.
- **Vérifier que le bon programme est flashé** : comparer quelques octets de la flash (`-r32 <adresse d'une fonction>`) à
  ceux de l'ELF (`objdump -s`). Un log identique au précédent « au milliseconde près » = ancien programme.
- **Image non en miroir** : test de la feuille « ABC » ; `BSP_CAMERA_SetMirrorFlip()` existe si besoin.

---

## 4. La boîte à outils de debug utilisée

| Besoin | Outil / commande |
|---|---|
| Lire un registre ou la RAM sans arrêter la carte | `STM32_Programmer_CLI -c port=SWD mode=HOTPLUG ap=0 shared -r32 <adresse> <taille>` |
| Registres du cœur (PC, LR, XPSR, PRIMASK) | `... -coreReg` |
| Copier une zone mémoire dans un fichier (dump) | `... -u <adresse> <taille> fichier.bin` |
| Adresse → fonction / ligne de code | `arm-none-eabi-addr2line -f -e firmware_CM7.elf <adresse>` |
| Où est une variable / quelle version d'une fonction est liée | fichier `firmware_CM7.map`, `arm-none-eabi-nm -S` |
| Cause d'une faute | IPSR (dans XPSR), CFSR `0xE000ED28`, MMFAR `0xE000ED34`, BFAR `0xE000ED38` |
| Interruptions activées | NVIC ISER `0xE000E100 +` (1 bit par IRQ) |
| Mesurer un temps | `HAL_GetTick()` (ms), `DWT->CYCCNT` (cycles, 400 par µs) |
| Voir ce que fait la carte en continu | `printf` sur l'UART (COM3, 115200) : lignes `[LIVE]`, compteur `erreurs DCMI` |

**Les 4 leçons principales**
1. Une adresse absurde mais petite (`0x28`) dans un pointeur = base **NULL** + décalage d'un registre.
2. Une fonction `__weak` peut être remplacée **sans aucun message** : le `.map` dit quel fichier fournit le symbole.
3. Sur H7, la SDRAM est **partagée** (CPU, LTDC, DMA2D, DMA caméra) : un overrun = un problème de débit et de *timing*.
4. Un bug qui change avec l'optimisation (-O0 / -O2) = un problème de *timing* (ou un `volatile` manquant), pas de logique.
