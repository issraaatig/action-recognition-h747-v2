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
