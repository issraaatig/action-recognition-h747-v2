# Déployer les deux modèles avec CubeMX + X-CUBE-AI 9.0

Chaîne complète :

```
pc/models/tinypose/A_hm128/tinypose_int8.tflite ─┐
                                                  ├─> X-CUBE-AI (CubeMX) ─> code C généré ─> CubeIDE ─> carte
pc/models/temporal/A_hm128_tcn/model_float32.tflite ┘
firmware/app/*.c (post-traitement, normalisation, buffer) ─> copiés dans le projet CM7
```

> Rien ici n'a encore été testé sur la carte. Chaque étape se termine par une vérification que **tu** fais
> (sortie UART, valeur dans le debugger) — voir CLAUDE.md, règle 6.

## 1. Projet CubeMX (une fois)
1. Nouveau projet STM32CubeIDE → Board Selector → **STM32H747I-DISCO**, nom `firmware`, dans ce dossier.
   « Initialize all peripherals with default mode ? » → **No**.
2. Horloges : M7 **400 MHz** (HSE 25 MHz, PLL1 M=5 N=160 P=2), Supply = SMPS direct (voir decisions.md D1).
3. USART1 (PA9/PA10, 115200 8N1) assigné au **CM7** pour `printf`.
4. Les deux modèles tournent sur le **Cortex-M7** uniquement.

## 2. Ajouter X-CUBE-AI et les deux réseaux
1. *Middleware and Software Packs* → **Select Components** → X-CUBE-AI 9.0.0 :
   - *Artificial Intelligence X-CUBE-AI* → **Core** : coché ;
   - *Device Application* → **Application Template** (squelette `app_x-cube-ai.c` que l'on remplira).
   - Contexte : **Cortex-M7**.
2. Onglet X-CUBE-AI → **Add network** (deux fois) :

| Nom du réseau | Type | Fichier | Rôle |
|---|---|---|---|
| `tinypose` | TFLite | `pc/models/tinypose/A_hm128/tinypose_int8.tflite` | image 128×128×3 uint8 → heatmaps 32×32×15 int8 |
| `tcn` | TFLite | `pc/models/temporal/A_hm128_tcn/model_float32.tflite` | fenêtre 16×30 float → 6 probabilités |

3. **Analyze** sur chaque réseau. Valeurs attendues (rapports dans `st_ai_out/`) :
   - tinypose : poids ~114 Ko, activations ~225 Ko, ~21,2 M MACC ;
   - tcn (float) : poids ~25 Ko, activations ~2 Ko.
   Si tes chiffres diffèrent, ce n'est pas le même fichier ou pas la même version de X-CUBE-AI.
4. (Optionnel) **Validate on desktop** : X-CUBE-AI exécute le code C généré sur PC et le compare au .tflite.
5. **Generate Code**. Dans `CM7/X-CUBE-AI/App/` apparaissent `tinypose.c/.h`, `tinypose_data.c/.h`,
   `tcn.c/.h`, `tcn_data.c/.h` et `app_x-cube-ai.c`.

## 3. Ajouter nos blocs C
Copier dans le projet CM7 (et ajouter le dossier aux *Include paths* : Properties → C/C++ Build → Settings) :
- `firmware/app/pose_postproc.c/.h`, `skeleton_norm.c/.h`, `temporal_buffer.c/.h` ;
- `firmware/test_vectors/*.h` (uniquement pour les tests ; `tv_tinypose.h` pèse ~50 Ko de données en flash).

Ces fichiers sont déjà validés sur PC contre Python (`firmware/host_tests/test_blocks.c`, erreur max = 0).

## 4. Appeler les deux réseaux (API X-CUBE-AI 9.0)
Les noms exacts des macros sont dans les `.h` générés (`tinypose.h`, `tinypose_data.h`) : **vérifie-les**.

```c
#include "tinypose.h"
#include "tinypose_data.h"
#include "tcn.h"
#include "tcn_data.h"
#include "pose_postproc.h"
#include "skeleton_norm.h"
#include "temporal_buffer.h"

/* Activations = mémoire de travail des réseaux. 225 Ko pour TinyPose : à placer en AXI SRAM (étape 5). */
AI_ALIGNED(32) static ai_u8 pose_act[AI_TINYPOSE_DATA_ACTIVATIONS_SIZE];
AI_ALIGNED(32) static ai_u8 tcn_act[AI_TCN_DATA_ACTIVATIONS_SIZE];
static ai_handle pose_net = AI_HANDLE_NULL, tcn_net = AI_HANDLE_NULL;

static skel_norm_t norm;
static tbuf_t      tbuf;

void actions_init(void)
{
  ai_error e;
  e = ai_tinypose_create_and_init(&pose_net, (const ai_handle[]){pose_act}, NULL);
  if (e.type != AI_ERROR_NONE) printf("tinypose init: type %d code %d\r\n", e.type, e.code);
  e = ai_tcn_create_and_init(&tcn_net, (const ai_handle[]){tcn_act}, NULL);
  if (e.type != AI_ERROR_NONE) printf("tcn init: type %d code %d\r\n", e.type, e.code);
  skel_norm_init(&norm, 0, 0.0f);   /* mêmes réglages que le modèle : 30 features, pas de lissage */
  tbuf_init(&tbuf, 30);
}

/* rgb128 : image 128×128×3 uint8, RGB, HWC (ligne par ligne, pixel par pixel, R puis G puis B). */
int actions_process_frame(const uint8_t *rgb128, float probs[6])
{
  ai_buffer *in  = ai_tinypose_inputs_get(pose_net, NULL);
  ai_buffer *out = ai_tinypose_outputs_get(pose_net, NULL);
  static int8_t heatmaps[32 * 32 * 15];
  in[0].data  = AI_HANDLE_PTR(rgb128);
  out[0].data = AI_HANDLE_PTR(heatmaps);
  if (ai_tinypose_run(pose_net, in, out) != 1) return -1;

  /* Paramètres de quantification de la sortie : dans le rapport X-CUBE-AI ou dans tv_tinypose.h
   * (TV_POSE_OUT_SCALE, TV_POSE_OUT_ZERO_POINT) — ils sont fixés à la conversion du .tflite. */
  pose_t pose;
  pose_decode_heatmaps(heatmaps, 32, 128, TV_POSE_OUT_SCALE, TV_POSE_OUT_ZERO_POINT, &pose);

  float feats[30];
  skel_norm_process(&norm, &pose, feats);
  tbuf_push(&tbuf, feats);

  static float window[16 * 30];
  tbuf_get_chronological(&tbuf, window);       /* plus ancien -> plus récent */
  in  = ai_tcn_inputs_get(tcn_net, NULL);
  out = ai_tcn_outputs_get(tcn_net, NULL);
  in[0].data  = AI_HANDLE_PTR(window);
  out[0].data = AI_HANDLE_PTR(probs);
  return (ai_tcn_run(tcn_net, in, out) == 1) ? 0 : -1;
}
```

Remarques :
- Si l'option *« use activation buffer for inputs/outputs »* est cochée dans X-CUBE-AI, `in[0].data` pointe
  déjà dans les activations : il faut alors **copier** l'image dedans au lieu de remplacer le pointeur.
- Ensuite : lissage (moyenne des 5 dernières `probs`) + seuil 0.6 → action affichée (CLAUDE.md §3).

## 5. Ordre de validation sur la carte (règle d'or)
| # | Test | Résultat attendu (UART) |
|---|---|---|
| 1 | `actions_init()` | aucune erreur `type/code` |
| 2 | TinyPose sur `tv_pose_input` | heatmaps = `tv_pose_expected_heatmaps` (écart ≤ 1 en int8) |
| 3 | post-traitement | joints = `tv_pose_expected_joints` |
| 4 | normalisation + buffer | = `tv_norm_expected` / `tv_temp_input` (erreur ~0) |
| 5 | TCN sur `tv_temp_input` | `tv_temp_expected_probs` = [0.092 0.017 0.043 0.464 0.326 0.058] (erreur < 1e-4) |
| 6 | latence | DWT->CYCCNT autour de `ai_tinypose_run` → ms à 400 MHz, à noter dans results.md |

Pièges probables (à déboguer toi-même, cf. phases 3 et 5 de CLAUDE.md) :
- **HardFault** au premier `ai_tinypose_run` : 225 Ko d'activations en DTCM (128 Ko) ne tiennent pas →
  regarder le `.map`, placer `pose_act` en AXI SRAM (`0x24000000`) avec une section dans le `.ld`.
- **Heatmaps fausses avec la caméra** mais justes avec `tv_pose_input` : format d'image (RGB565 vs RGB888,
  ordre BGR, cache D non invalidé après le DMA DCMI).
