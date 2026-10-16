# Journal de debug

Une entrée par bug résolu. Format :

```
## [Date] [Phase X] Titre court
- **Symptôme** : ce que j'ai observé (UART, écran, LED, debugger)
- **Hypothèses** (par probabilité) : 1. … 2. … 3. …
- **Méthode de debug** : breakpoint où, registre/variable lu, valeur obtenue
- **Cause réelle** :
- **Correction** :
- **Leçon** : ce que je ferai directement la prochaine fois
```

---

## 2026-10-15 [Phase 0] Rien sur l'UART : le M7 bloqué dans Error_Handler (M4 non flashé)
- **Symptôme** : après « Run As » de `firmware_CM7` seul, aucun caractère sur le port série (0 octet en 8 s sur COM3),
  écran de la carte noir, notre LED LD1 ne clignote pas (une autre LED clignote : ancien programme du M4 / LED ST-LINK).
- **Hypothèses** (par probabilité) :
  1. terminal sur le mauvais port (COM4 dans CLAUDE.md, alors que la carte est sur **COM3**) ;
  2. M7 bloqué dans `Error_Handler()` : la séquence de boot dual-core attend que le M4 se mette en STOP ;
  3. programme non flashé / flash échoué ;
  4. terminal ouvert après le message de démarrage.
- **Méthode de debug** :
  - Gestionnaire de périphériques → port réel = COM3 (hypothèse 1 corrigée, mais toujours 0 octet → pas la cause) ;
  - lecture des registres du Cortex-M7 sans reset : `STM32_Programmer_CLI -c port=SWD mode=HOTPLUG ap=0 shared -coreReg`
    → `PC = 0x08000C20`, `LR = 0x08000877`, `PRIMASK = 1` (interruptions coupées) ;
  - traduction adresse → ligne : `arm-none-eabi-addr2line -f -e firmware_CM7.elf 0x08000C20 0x08000876`
    → PC dans `Error_Handler()` (main.c:362), appelé depuis **main.c:108** (timeout de l'attente `RCC_FLAG_D2CKRDY`).
- **Cause réelle** : seul le M7 avait été flashé. Le M4 contenait encore la démo d'usine, qui ne se met pas en STOP ;
  l'attente de synchronisation du M7 expire → `Error_Handler()` (boucle infinie, IRQ désactivées).
- **Correction** : flasher aussi `firmware_CM4` (Run As), puis `firmware_CM7`, puis RESET.
  Résultat : LED LD1 clignote, `tick = …` toutes les ~502 ms sur COM3 à 115200 bauds.
- **Leçon** : sur un STM32H7 dual-core, **toujours flasher les deux cœurs**. Quand rien ne marche, ne pas deviner :
  mettre en pause (Suspend) ou lire **PC / LR**, puis traduire l'adresse en ligne de code. `PRIMASK = 1` + boucle
  infinie = signature typique de `Error_Handler()`.

## 2026-10-16 [Phase 3.1] SDRAM : MemManage à la première écriture (MPU), puis région MPU « incomplète »
- **Symptôme** : `[SDRAM] init OK` s'affiche, puis plus rien ; la LED s'arrête. Après ajout d'une région MPU pour la SDRAM : **même symptôme**.
- **Hypothèses** (par probabilité) : 1. faute mémoire (MPU) sur la zone SDRAM (D12) ; 2. interruption non gérée (MDMA activée par le BSP) ;
  3. attente infinie dans le BSP.
- **Méthode de debug** (sans arrêter la carte, `STM32_Programmer_CLI -c port=SWD mode=HOTPLUG ap=0 shared`) :
  - `-coreReg` → `XPSR = 0x41000004` : champ IPSR = **4 = MemManage** ; `PC` dans `MemManage_Handler` ; `LR = 0xFFFFFFE9` (retour d'exception) ;
  - `-r32 0xE000ED28` → **CFSR = 0x82** : DACCVIOL (accès donnée interdit) + MMARVALID ; `-r32 0xE000ED34` → **MMFAR = 0xD0000000** ;
  - pile d'exception lue à SP : `R3 = 0xA5A5A5A5` (= 0 ^ 0xA5A5A5A5, 1re écriture), adresse → `main.c:97` (boucle d'écriture) via addr2line.
  - Après la 1re correction, mêmes valeurs → relecture du `MPU_Config()` généré.
- **Cause réelle** : (1) la région MPU 0 par défaut interdit 0x60000000–0xDFFFFFFF, SDRAM comprise (D12).
  (2) La région 1 ajoutée dans CubeMX n'avait que Base/Size/Enable : CubeMX n'écrit que les champs modifiés, et la même variable
  `MPU_InitStruct` sert aux deux régions → la région 1 **héritait de `AccessPermission = MPU_REGION_NO_ACCESS`** de la région 0.
- **Correction** : CubeMX → CORTEX_M7 → MPU Region 1 : base 0xD0000000, 32 MB, **Access Permission = ALL ACCESS PERMITTED** (réglé
  explicitement), non cacheable / non bufferable. Résultat : 8 388 608 mots écrits/relus, **0 erreur** (~0,9 s).
- **Leçon** : IPSR (exception n°) + CFSR + MMFAR/BFAR donnent la cause d'une faute en 3 lectures. Le Fault Analyzer ne montre rien si le
  processeur est encore arrêté au breakpoint de `main` : il faut d'abord Resume puis Suspend. Quand une faute **ne change pas** après une
  correction, relire le **code généré** (ici un champ hérité d'une région précédente), pas seulement l'écran de configuration.

## 2026-10-16 [Phase 3.3] Caméra : « pas d'image en 500 ms » — 3 bugs en chaîne
### Bug 1 : la fonction `MX_DCMI_Init` de CubeMX remplace en silence celle du BSP
- **Symptôme** : `[CAM] init OK` (le capteur répond en I2C), puis `pas d'image en 500 ms` en boucle ; écran bleu seul.
- **Hypothèses** : 1. DCMI/DMA mal configurés ; 2. IRQ de fin d'image non reçue (handler manquant) ; 3. capteur muet ; 4. cache.
- **Méthode** (SWD hotplug, `-r32`) : DCMI `CR = 0` (jamais activé), DMA2 Stream3 `NDTR = 0x9600` (rien transféré),
  **`PAR = 0x00000028`** au lieu de `0x48020028`. 0x28 = décalage du registre DR → calculé avec `Instance = NULL`.
  Puis `.map` / `nm` : `MX_DCMI_Init` défini dans **main.o**, la version du BSP écartée.
- **Cause réelle** : la case « Generate Code » de MX_DCMI_Init s'était recochée dans CubeMX. CubeMX a généré `void MX_DCMI_Init(void)`
  (non weak) dans main.c, qui **remplace au linkage** la fonction `__weak MX_DCMI_Init(DCMI_HandleTypeDef*)` du BSP
  → c'est `hdcmi` (CubeMX) qui est initialisé, pas `hcamera_dcmi` (BSP). Aucun avertissement : le linker ne compare pas les paramètres.
- **Correction** : CubeMX → Advanced Settings → MX_DCMI_Init (M7) : Generate Code décoché → `.map` : `MX_DCMI_Init` vient de
  `stm32h747i_discovery_camera.o`. Une 1re image arrive (91 ms), mais presque noire.
- **Leçon** : une adresse « absurde mais petite » (0x28, 0x10…) dans un pointeur = base NULL + décalage d'un registre.
  Une fonction `__weak` peut être remplacée sans message : vérifier dans le `.map` **quel fichier** fournit le symbole.

### Bug 2 : une seule image en mode snapshot
- **Symptôme** : 1re image OK, puis `pas d'image en 500 ms`.
- **Méthode** : DCMI `IER = 0` (toutes les interruptions coupées). Lecture de `stm32h7xx_hal_dcmi.c` : en mode snapshot, l'IRQ de fin
  d'image coupe LINE/VSYNC/ERR/OVR/FRAME, et seul `HAL_DCMI_Init` les réactive ; `HAL_DCMI_Start_DMA` ne le fait pas.
- **Correction** : mode **continu**, démarré une seule fois dans `camera_init()`. La boucle attend `frame_ready`, puis le remet à 0.
  (Piège rencontré : `frame_ready = 0` placé **dans** le `while (!frame_ready)` → jamais remis à 0 → « capturee en 0 ms » en boucle :
  un temps trop beau pour être vrai est un indice.)

### Bug 3 : overrun du FIFO DCMI (bus SDRAM saturé)
- **Symptôme** : en continu, 1 image puis plus rien. DMA `EN = 0` arrêté après 67 mots.
- **Méthode** : adresse de `hcamera_dcmi` dans le `.map`, lecture de la structure en RAM : `State = 4` (ERROR),
  **`ErrorCode = 0x41`** = OVR (0x01) + DMA (0x40). Ajout d'un compteur dans `BSP_CAMERA_ErrorCallback` affiché par UART.
- **Cause réelle** : pendant que le DMA caméra écrit en SDRAM, la copie CPU (lecture + écriture pixel par pixel, non cacheable)
  et le LTDC (~90 Mo/s) utilisent le même bus FMC → le DMA attend trop, le FIFO du DCMI déborde, la HAL arrête le DMA définitivement.
- **Correction** : `BSP_CAMERA_Suspend(0)` avant la copie, `BSP_CAMERA_Resume(0)` après. Résultat : `erreurs DCMI : 0`,
  image en direct correcte, ~42 ms d'attente par image, boucle ≈ 175 ms.
- **Leçon** : sur H7, la SDRAM est une ressource partagée (CPU, LTDC, DMA, DMA2D). Un overrun = un problème de **débit/priorité**,
  pas de configuration. Amélioration prévue : copie par DMA2D (rafales, conversion RGB565→ARGB8888 matérielle).

## 2026-10-16 [Phase 3.4] Test prétraitement + TinyPose : joints décalés de 70 px alors que l'entrée est exacte
- **Symptôme** : `[TEST] pretraitement : ... octets differents = 0 / 49152` (bloc exact) mais
  `[TEST] pretraitement + tinypose : joints 70000000 e-6 px, scores 64620 e-6`. Le test TinyPose n°1 (autre image) reste bit-exact.
- **Hypothèses** : 1. le TCN (exécuté entre les deux tests) corrompt la mémoire de TinyPose ; 2. l'entrée est modifiée entre la
  vérification et `ai_run()` (DMA, interruption) ; 3. le code C X-CUBE-AI n'est pas bit-exact avec TFLite sur toutes les images.
- **Méthode** :
  - `nm -S` : `pool0` (TinyPose, 0x24008020, 229 888 o) et `tcn_pool` (0x24040240) ne se chevauchent pas → hypothèse 1 peu probable ;
  - adresses réelles des buffers lues via les pointeurs `ai_input` / `ai_output` (structure `ai_buffer`, champ `data` à +4) ;
  - **dump de la sortie de la carte** par SWD : `STM32_Programmer_CLI ... -u 0x24008138 15360 board_out.bin` ;
  - même image passée à `stedgeai validate --mode host` (le code C généré, compilé et exécuté sur PC) :
    **carte = code C sur PC (0 différence)**, code C ≠ TFLite (3 755 valeurs). Sur l'image du test n°1 : 0 différence partout.
- **Cause réelle** : pas un bug de la carte. Le noyau int8 d'X-CUBE-AI ne donne pas exactement les mêmes entiers que TFLite sur
  certaines images (43 % des images, PCK pourtant identique 0,621 / 0,622). Le test n°1 était exact « par chance ». Le joint à 70 px
  a un score de 0,25 : heatmap plate, un petit écart change l'argmax (et la normalisation le remplacera, score < 0,3).
- **Correction** : aucune dans le firmware. La référence bit-exacte de la carte est la sortie de `stedgeai validate --mode host`,
  pas TFLite. Écart accepté (précision identique).
- **Leçon** : quand la carte et Python divergent, **isoler l'étage** : vérifier l'entrée, puis exécuter le même code C sur PC.
  Un dump mémoire par SWD (`-u adresse taille fichier`) permet de comparer des milliers de valeurs, pas seulement une erreur max.
