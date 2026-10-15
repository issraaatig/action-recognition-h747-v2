/**
  ******************************************************************************
  * @file    tinypose_data_params.h
  * @author  AST Embedded Analytics Research Platform
  * @date    2026-10-15T10:24:04+0100
  * @brief   AI Tool Automatic Code Generator for Embedded NN computing
  ******************************************************************************
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  ******************************************************************************
  */

#ifndef TINYPOSE_DATA_PARAMS_H
#define TINYPOSE_DATA_PARAMS_H

#include "ai_platform.h"

/*
#define AI_TINYPOSE_DATA_WEIGHTS_PARAMS \
  (AI_HANDLE_PTR(&ai_tinypose_data_weights_params[1]))
*/

#define AI_TINYPOSE_DATA_CONFIG               (NULL)


#define AI_TINYPOSE_DATA_ACTIVATIONS_SIZES \
  { 229888, }
#define AI_TINYPOSE_DATA_ACTIVATIONS_SIZE     (229888)
#define AI_TINYPOSE_DATA_ACTIVATIONS_COUNT    (1)
#define AI_TINYPOSE_DATA_ACTIVATION_1_SIZE    (229888)



#define AI_TINYPOSE_DATA_WEIGHTS_SIZES \
  { 117108, }
#define AI_TINYPOSE_DATA_WEIGHTS_SIZE         (117108)
#define AI_TINYPOSE_DATA_WEIGHTS_COUNT        (1)
#define AI_TINYPOSE_DATA_WEIGHT_1_SIZE        (117108)



#define AI_TINYPOSE_DATA_ACTIVATIONS_TABLE_GET() \
  (&g_tinypose_activations_table[1])

extern ai_handle g_tinypose_activations_table[1 + 2];



#define AI_TINYPOSE_DATA_WEIGHTS_TABLE_GET() \
  (&g_tinypose_weights_table[1])

extern ai_handle g_tinypose_weights_table[1 + 2];


#endif    /* TINYPOSE_DATA_PARAMS_H */
