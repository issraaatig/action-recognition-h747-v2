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
