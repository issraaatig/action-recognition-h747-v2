
/**
  ******************************************************************************
  * @file    app_x-cube-ai.c
  * @author  X-CUBE-AI C code generator
  * @brief   AI program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */

 /*
  * Description
  *   v1.0 - Minimum template to show how to use the Embedded Client API
  *          model. Only one input and one output is supported. All
  *          memory resources are allocated statically (AI_NETWORK_XX, defines
  *          are used).
  *          Re-target of the printf function is out-of-scope.
  *   v2.0 - add multiple IO and/or multiple heap support
  *
  *   For more information, see the embeded documentation:
  *
  *       [1] %X_CUBE_AI_DIR%/Documentation/index.html
  *
  *   X_CUBE_AI_DIR indicates the location where the X-CUBE-AI pack is installed
  *   typical : C:\Users\[user_name]\STM32Cube\Repository\STMicroelectronics\X-CUBE-AI\7.1.0
  */

#ifdef __cplusplus
 extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/

#if defined ( __ICCARM__ )
#elif defined ( __CC_ARM ) || ( __GNUC__ )
#endif

/* System headers */
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <inttypes.h>
#include <string.h>

#include "app_x-cube-ai.h"
#include "main.h"
#include "ai_datatypes_defines.h"
#include "tinypose.h"
#include "tinypose_data.h"
#include "tcn.h"
#include "tcn_data.h"

/* USER CODE BEGIN includes */
 #include <math.h>
 #include "pose_postproc.h"
 #include "skeleton_norm.h"
 #include "temporal_buffer.h"
 #include "test_vectors/tv_tinypose.h"
 #include "test_vectors/tv_normalize.h"
 #include "test_vectors/tv_temporal.h"
 #include "preprocess.h"
 #include "test_vectors/tv_preprocess.h"
/* USER CODE END includes */

/* IO buffers ----------------------------------------------------------------*/

#if !defined(AI_TINYPOSE_INPUTS_IN_ACTIVATIONS)
AI_ALIGNED(4) ai_i8 data_in_1[AI_TINYPOSE_IN_1_SIZE_BYTES];
ai_i8* data_ins[AI_TINYPOSE_IN_NUM] = {
data_in_1
};
#else
ai_i8* data_ins[AI_TINYPOSE_IN_NUM] = {
NULL
};
#endif

#if !defined(AI_TINYPOSE_OUTPUTS_IN_ACTIVATIONS)
AI_ALIGNED(4) ai_i8 data_out_1[AI_TINYPOSE_OUT_1_SIZE_BYTES];
ai_i8* data_outs[AI_TINYPOSE_OUT_NUM] = {
data_out_1
};
#else
ai_i8* data_outs[AI_TINYPOSE_OUT_NUM] = {
NULL
};
#endif

/* Activations buffers -------------------------------------------------------*/

AI_ALIGNED(32)
static uint8_t pool0[AI_TINYPOSE_DATA_ACTIVATION_1_SIZE];

ai_handle data_activations0[] = {pool0};
ai_handle data_activations1[] = {pool0};

/* AI objects ----------------------------------------------------------------*/

static ai_handle tinypose = AI_HANDLE_NULL;

static ai_buffer* ai_input;
static ai_buffer* ai_output;

static void ai_log_err(const ai_error err, const char *fct)
{
  /* USER CODE BEGIN log */
  if (fct)
    printf("TEMPLATE - Error (%s) - type=0x%02x code=0x%02x\r\n", fct,
        err.type, err.code);
  else
    printf("TEMPLATE - Error - type=0x%02x code=0x%02x\r\n", err.type, err.code);

  do {} while (1);
  /* USER CODE END log */
}

static int ai_boostrap(ai_handle *act_addr)
{
  ai_error err;

  /* Create and initialize an instance of the model */
  err = ai_tinypose_create_and_init(&tinypose, act_addr, NULL);
  if (err.type != AI_ERROR_NONE) {
    ai_log_err(err, "ai_tinypose_create_and_init");
    return -1;
  }

  ai_input = ai_tinypose_inputs_get(tinypose, NULL);
  ai_output = ai_tinypose_outputs_get(tinypose, NULL);

#if defined(AI_TINYPOSE_INPUTS_IN_ACTIVATIONS)
  /*  In the case where "--allocate-inputs" option is used, memory buffer can be
   *  used from the activations buffer. This is not mandatory.
   */
  for (int idx=0; idx < AI_TINYPOSE_IN_NUM; idx++) {
	data_ins[idx] = ai_input[idx].data;
  }
#else
  for (int idx=0; idx < AI_TINYPOSE_IN_NUM; idx++) {
	  ai_input[idx].data = data_ins[idx];
  }
#endif

#if defined(AI_TINYPOSE_OUTPUTS_IN_ACTIVATIONS)
  /*  In the case where "--allocate-outputs" option is used, memory buffer can be
   *  used from the activations buffer. This is no mandatory.
   */
  for (int idx=0; idx < AI_TINYPOSE_OUT_NUM; idx++) {
	data_outs[idx] = ai_output[idx].data;
  }
#else
  for (int idx=0; idx < AI_TINYPOSE_OUT_NUM; idx++) {
	ai_output[idx].data = data_outs[idx];
  }
#endif

  return 0;
}

static int ai_run(void)
{
  ai_i32 batch;

  batch = ai_tinypose_run(tinypose, ai_input, ai_output);
  if (batch != 1) {
    ai_log_err(ai_tinypose_get_error(tinypose),
        "ai_tinypose_run");
    return -1;
  }

  return 0;
}

/* USER CODE BEGIN 2 */
/* Second network: the TCN (the template only handles tinypose) */
static ai_handle tcn = AI_HANDLE_NULL;
AI_ALIGNED(32) static uint8_t tcn_pool[AI_TCN_DATA_ACTIVATIONS_SIZE];

/* Cortex-M7 cycle counter (DWT): +1 per CPU cycle, i.e. 400 per microsecond at 400 MHz */
static void cycles_start(void)
{
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;   /* enable the DWT unit           */
  DWT->LAR = 0xC5ACCE55;                            /* unlock it (needed on the M7) */
  DWT->CYCCNT = 0;                                  /* reset the counter            */
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;              /* start counting               */
}

static uint32_t cycles_to_us(uint32_t cycles)
{
  return cycles / (SystemCoreClock / 1000000U);     /* 400 cycles = 1 us */
}

/* Test 1: TinyPose on the test image, compared with the Python result */
static void test_tinypose(void)
{
  /* 1. copy the test image INTO the network input buffer (it lives in the activations) */
  memcpy(ai_input[0].data, tv_pose_input, AI_TINYPOSE_IN_1_SIZE_BYTES);

  /* 2. run TinyPose and measure the time */
  cycles_start();
  if (ai_run() != 0) return;                        /* ai_run() already printed the error */
  uint32_t us = cycles_to_us(DWT->CYCCNT);

  /* 3. compare the 15360 int8 values with the expected heatmaps */
  const int8_t *out = (const int8_t *)ai_output[0].data;
  const int8_t *exp = &tv_pose_expected_heatmaps[0][0][0];
  int max_err = 0, n_diff = 0;
  for (int i = 0; i < AI_TINYPOSE_OUT_1_SIZE; i++) {
    int d = abs(out[i] - exp[i]);
    if (d > max_err) max_err = d;
    if (d != 0) n_diff++;
  }
  printf("[TEST] tinypose : %lu us, erreur max = %d, valeurs differentes = %d / %d\r\n",
         us, max_err, n_diff, AI_TINYPOSE_OUT_1_SIZE);
}

/* Largest absolute difference between two float arrays */
static float max_abs_diff(const float *a, const float *b, int n)
{
  float m = 0.0f;
  for (int i = 0; i < n; i++) {
    float d = fabsf(a[i] - b[i]);
    if (d > m) m = d;
  }
  return m;
}

/* newlib-nano printf cannot print floats: show small errors as integers of 1e-6 */
#define MICRO(x) ((unsigned long)((x) * 1e6f))

/* Tests 2, 3, 4: decoding, normalisation + buffer, TCN */
static void test_chain(void)
{
  /* Test 2: decode the heatmaps that TinyPose just produced ON THE BOARD */
  pose_t pose;
  pose_decode_heatmaps((const int8_t *)ai_output[0].data, 32, 128,
                       TV_POSE_OUT_SCALE, TV_POSE_OUT_ZERO_POINT, &pose);
  float joints[15][2];
  for (int j = 0; j < 15; j++) { joints[j][0] = pose.x[j]; joints[j][1] = pose.y[j]; }
  printf("[TEST] decodage : joints %lu e-6 px, scores %lu e-6\r\n",
         MICRO(max_abs_diff(&joints[0][0], &tv_pose_expected_joints[0][0], 30)),
         MICRO(max_abs_diff(pose.score, tv_pose_expected_scores, 15)));

  /* Test 3: normalisation of 20 frames + circular buffer */
  skel_norm_t norm;
  tbuf_t buf;
  float feats[TV_NORM_N_FEATURES];
  float err_norm = 0.0f;
  skel_norm_init(&norm, TV_NORM_N_FEATURES == 32, 0.0f);
  tbuf_init(&buf, TV_NORM_N_FEATURES);
  for (int t = 0; t < TV_NORM_N_FRAMES; t++) {
    pose_t p;
    for (int j = 0; j < 15; j++) {
      p.x[j] = tv_norm_joints[t][j][0];
      p.y[j] = tv_norm_joints[t][j][1];
      p.score[j] = tv_norm_scores[t][j];
    }
    skel_norm_process(&norm, &p, feats);
    float e = max_abs_diff(feats, tv_norm_expected[t], TV_NORM_N_FEATURES);
    if (e > err_norm) err_norm = e;
    tbuf_push(&buf, feats);
  }
  static float window[TBUF_LEN * TV_NORM_N_FEATURES];
  tbuf_get_chronological(&buf, window);
  printf("[TEST] normalisation : %lu e-6, buffer : %lu e-6\r\n", MICRO(err_norm),
         MICRO(max_abs_diff(window, &tv_temp_input[0][0], TBUF_LEN * TV_NORM_N_FEATURES)));

  /* Test 4: TCN on the test window */
  ai_buffer *tin  = ai_tcn_inputs_get(tcn, NULL);
  ai_buffer *tout = ai_tcn_outputs_get(tcn, NULL);
  memcpy(tin[0].data, tv_temp_input, AI_TCN_IN_1_SIZE_BYTES);   /* input lives in tcn_pool */
  cycles_start();
  if (ai_tcn_run(tcn, tin, tout) != 1) {
    ai_log_err(ai_tcn_get_error(tcn), "ai_tcn_run");
    return;
  }
  uint32_t us = cycles_to_us(DWT->CYCCNT);
  const float *probs = (const float *)tout[0].data;
  printf("[TEST] tcn : %lu us, erreur max probas %lu e-6\r\n", us,
         MICRO(max_abs_diff(probs, tv_temp_expected_probs, 6)));
  printf("[TEST] probas x1000 : jump %lu clap %lu wave %lu sit %lu stand %lu other %lu\r\n",
         (unsigned long)(probs[0] * 1000), (unsigned long)(probs[1] * 1000),
         (unsigned long)(probs[2] * 1000), (unsigned long)(probs[3] * 1000),
         (unsigned long)(probs[4] * 1000), (unsigned long)(probs[5] * 1000));
}

/* Test 5: camera preprocessing (RGB565 320x240 -> 128x128x3), written straight into the TinyPose input,
   then TinyPose + decoding on that image: compared with Python (pc/common/preprocess.py + tflite int8) */
static void test_preprocess(void)
{
  uint8_t *in = (uint8_t *)ai_input[0].data;
  cycles_start();
  preprocess_camera_to_tinypose(&tv_pp_input[0][0], in);
  uint32_t us = cycles_to_us(DWT->CYCCNT);

  const uint8_t *exp = &tv_pp_expected[0][0][0];
  int max_err = 0, n_diff = 0;
  for (int i = 0; i < AI_TINYPOSE_IN_1_SIZE_BYTES; i++) {
    int d = abs(in[i] - exp[i]);
    if (d > max_err) max_err = d;
    if (d != 0) n_diff++;
  }
  printf("[TEST] pretraitement : %lu us, erreur max = %d, octets differents = %d / %d\r\n",
         us, max_err, n_diff, AI_TINYPOSE_IN_1_SIZE_BYTES);

  if (ai_run() != 0) return;
  pose_t pose;
  pose_decode_heatmaps((const int8_t *)ai_output[0].data, 32, 128,
                       TV_POSE_OUT_SCALE, TV_POSE_OUT_ZERO_POINT, &pose);
  float joints[15][2];
  for (int j = 0; j < 15; j++) { joints[j][0] = pose.x[j]; joints[j][1] = pose.y[j]; }
  printf("[TEST] pretraitement + tinypose : joints %lu e-6 px, scores %lu e-6\r\n",
         MICRO(max_abs_diff(&joints[0][0], &tv_pp_expected_joints[0][0], 30)),
         MICRO(max_abs_diff(pose.score, tv_pp_expected_scores, 15)));
}


int acquire_and_process_data(ai_i8* data[])
{
  /* fill the inputs of the c-model
  for (int idx=0; idx < AI_TINYPOSE_IN_NUM; idx++ )
  {
      data[idx] = ....
  }

  */
  return 0;
}

int post_process(ai_i8* data[])
{
  /* process the predictions
  for (int idx=0; idx < AI_TINYPOSE_OUT_NUM; idx++ )
  {
      data[idx] = ....
  }

  */
  return 0;
}
/* USER CODE END 2 */

/* Entry points --------------------------------------------------------------*/

void MX_X_CUBE_AI_Init(void)
{
    /* USER CODE BEGIN 5 */
	  printf("\r\n[AI] initialisation\r\n");

	  /* 1. TinyPose : la fonction du squelette le cree dans pool0 (225 Ko) */
	  if (ai_boostrap(data_activations0) == 0)
	    printf("[AI] tinypose OK : entree %u o, sortie %u o, activations %u o\r\n",
	           (unsigned)AI_TINYPOSE_IN_1_SIZE_BYTES, (unsigned)AI_TINYPOSE_OUT_1_SIZE_BYTES,
	           (unsigned)AI_TINYPOSE_DATA_ACTIVATIONS_SIZE);

	  /* 2. TCN : on le cree nous-memes, dans son propre buffer tcn_pool */
	  ai_handle tcn_act[] = { tcn_pool };
	  ai_error err = ai_tcn_create_and_init(&tcn, tcn_act, NULL);
	  if (err.type != AI_ERROR_NONE)
	    ai_log_err(err, "ai_tcn_create_and_init");
	  else
	    printf("[AI] tcn OK : entree %u o, sortie %u o, activations %u o\r\n",
	           (unsigned)AI_TCN_IN_1_SIZE_BYTES, (unsigned)AI_TCN_OUT_1_SIZE_BYTES,
	           (unsigned)AI_TCN_DATA_ACTIVATIONS_SIZE);
    /* USER CODE END 5 */
}

void MX_X_CUBE_AI_Process(void)
{
    /* USER CODE BEGIN 6 */
  static int done = 0;          /* run the tests only once, then let main() continue */
  if (!done) {
    done = 1;
    test_tinypose();
    test_chain();
    test_preprocess();
  }
    /* USER CODE END 6 */
}
/* Multiple network support --------------------------------------------------*/

#include <string.h>
#include "ai_datatypes_defines.h"

static const ai_network_entry_t networks[AI_MNETWORK_NUMBER] = {
    {
        .name = (const char *)AI_TINYPOSE_MODEL_NAME,
        .config = AI_TINYPOSE_DATA_CONFIG,
        .ai_get_report = ai_tinypose_get_report,
        .ai_create = ai_tinypose_create,
        .ai_destroy = ai_tinypose_destroy,
        .ai_get_error = ai_tinypose_get_error,
        .ai_init = ai_tinypose_init,
        .ai_run = ai_tinypose_run,
        .ai_forward = ai_tinypose_forward,
        .ai_data_params_get = ai_tinypose_data_params_get,
        .activations = data_activations0
    },
    {
        .name = (const char *)AI_TCN_MODEL_NAME,
        .config = AI_TCN_DATA_CONFIG,
        .ai_get_report = ai_tcn_get_report,
        .ai_create = ai_tcn_create,
        .ai_destroy = ai_tcn_destroy,
        .ai_get_error = ai_tcn_get_error,
        .ai_init = ai_tcn_init,
        .ai_run = ai_tcn_run,
        .ai_forward = ai_tcn_forward,
        .ai_data_params_get = ai_tcn_data_params_get,
        .activations = data_activations1
    },
};

struct network_instance {
     const ai_network_entry_t *entry;
     ai_handle handle;
     ai_network_params params;
};

/* Number of instance is aligned on the number of network */
AI_STATIC struct network_instance gnetworks[AI_MNETWORK_NUMBER] = {0};

AI_DECLARE_STATIC
ai_bool ai_mnetwork_is_valid(const char* name,
        const ai_network_entry_t *entry)
{
    if (name && (strlen(entry->name) == strlen(name)) &&
            (strncmp(entry->name, name, strlen(entry->name)) == 0))
        return true;
    return false;
}

AI_DECLARE_STATIC
struct network_instance *ai_mnetwork_handle(struct network_instance *inst)
{
    for (int i=0; i<AI_MNETWORK_NUMBER; i++) {
        if ((inst) && (&gnetworks[i] == inst))
            return inst;
        else if ((!inst) && (gnetworks[i].entry == NULL))
            return &gnetworks[i];
    }
    return NULL;
}

AI_DECLARE_STATIC
void ai_mnetwork_release_handle(struct network_instance *inst)
{
    for (int i=0; i<AI_MNETWORK_NUMBER; i++) {
        if ((inst) && (&gnetworks[i] == inst)) {
            gnetworks[i].entry = NULL;
            return;
        }
    }
}

AI_API_ENTRY
const char* ai_mnetwork_find(const char *name, ai_int idx)
{
    const ai_network_entry_t *entry;

    for (int i=0; i<AI_MNETWORK_NUMBER; i++) {
        entry = &networks[i];
        if (ai_mnetwork_is_valid(name, entry))
            return entry->name;
        else {
            if (!idx--)
                return entry->name;
        }
    }
    return NULL;
}

AI_API_ENTRY
ai_error ai_mnetwork_create(const char *name, ai_handle* network,
        const ai_buffer* network_config)
{
    const ai_network_entry_t *entry;
    const ai_network_entry_t *found = NULL;
    ai_error err;
    struct network_instance *inst = ai_mnetwork_handle(NULL);

    if (!inst) {
        err.type = AI_ERROR_ALLOCATION_FAILED;
        err.code = AI_ERROR_CODE_NETWORK;
        return err;
    }

    for (int i=0; i<AI_MNETWORK_NUMBER; i++) {
        entry = &networks[i];
        if (ai_mnetwork_is_valid(name, entry)) {
            found = entry;
            break;
        }
    }

    if (!found) {
        err.type = AI_ERROR_INVALID_PARAM;
        err.code = AI_ERROR_CODE_NETWORK;
        return err;
    }

    if (network_config == NULL)
        err = found->ai_create(network, found->config);
    else
        err = found->ai_create(network, network_config);
    if ((err.code == AI_ERROR_CODE_NONE) && (err.type == AI_ERROR_NONE)) {
        inst->entry = found;
        inst->handle = *network;
        *network = (ai_handle*)inst;
    }

    return err;
}

AI_API_ENTRY
ai_handle ai_mnetwork_destroy(ai_handle network)
{
    struct network_instance *inn;
    inn =  ai_mnetwork_handle((struct network_instance *)network);
    if (inn) {
        ai_handle hdl = inn->entry->ai_destroy(inn->handle);
        if (hdl != inn->handle) {
            ai_mnetwork_release_handle(inn);
            network = AI_HANDLE_NULL;
        }
    }
    return network;
}

AI_API_ENTRY
ai_bool ai_mnetwork_get_report(ai_handle network, ai_network_report* report)
{
    struct network_instance *inn;
    inn =  ai_mnetwork_handle((struct network_instance *)network);
    if (inn)
        return inn->entry->ai_get_report(inn->handle, report);
    else
        return false;
}

AI_API_ENTRY
ai_error ai_mnetwork_get_error(ai_handle network)
{
    struct network_instance *inn;
    ai_error err;
    err.type = AI_ERROR_INVALID_PARAM;
    err.code = AI_ERROR_CODE_NETWORK;

    inn =  ai_mnetwork_handle((struct network_instance *)network);
    if (inn)
        return inn->entry->ai_get_error(inn->handle);
    else
        return err;
}

AI_API_ENTRY
ai_bool ai_mnetwork_init(ai_handle network)
{
    struct network_instance *inn;
    ai_network_params par;

    inn =  ai_mnetwork_handle((struct network_instance *)network);
    if (inn) {
        inn->entry->ai_data_params_get(&par);
        for (int idx=0; idx < par.map_activations.size; idx++)
          AI_BUFFER_ARRAY_ITEM_SET_ADDRESS(&par.map_activations, idx, inn->entry->activations[idx]);
        return inn->entry->ai_init(inn->handle, &par);
    }
    else
        return false;
}

AI_API_ENTRY
ai_i32 ai_mnetwork_run(ai_handle network, const ai_buffer* input,
        ai_buffer* output)
{
    struct network_instance* inn;
    inn =  ai_mnetwork_handle((struct network_instance *)network);
    if (inn)
        return inn->entry->ai_run(inn->handle, input, output);
    else
        return 0;
}

AI_API_ENTRY
ai_i32 ai_mnetwork_forward(ai_handle network, const ai_buffer* input)
{
    struct network_instance *inn;
    inn =  ai_mnetwork_handle((struct network_instance *)network);
    if (inn)
        return inn->entry->ai_forward(inn->handle, input);
    else
        return 0;
}

AI_API_ENTRY
 int ai_mnetwork_get_private_handle(ai_handle network,
         ai_handle *phandle,
         ai_network_params *pparams)
 {
     struct network_instance* inn;
     inn =  ai_mnetwork_handle((struct network_instance *)network);
     if (inn && phandle && pparams) {
         *phandle = inn->handle;
         *pparams = inn->params;
         return 0;
     }
     else
         return -1;
 }

#ifdef __cplusplus
}
#endif
