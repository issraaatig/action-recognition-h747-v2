/**
  ******************************************************************************
  * @file    tcn_data_params.h
  * @author  AST Embedded Analytics Research Platform
  * @date    2026-10-16T21:26:44+0100
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

#ifndef TCN_DATA_PARAMS_H
#define TCN_DATA_PARAMS_H

#include "ai_platform.h"

/*
#define AI_TCN_DATA_WEIGHTS_PARAMS \
  (AI_HANDLE_PTR(&ai_tcn_data_weights_params[1]))
*/

#define AI_TCN_DATA_CONFIG               (NULL)


#define AI_TCN_DATA_ACTIVATIONS_SIZES \
  { 4072, }
#define AI_TCN_DATA_ACTIVATIONS_SIZE     (4072)
#define AI_TCN_DATA_ACTIVATIONS_COUNT    (1)
#define AI_TCN_DATA_ACTIVATION_1_SIZE    (4072)



#define AI_TCN_DATA_WEIGHTS_SIZES \
  { 24856, }
#define AI_TCN_DATA_WEIGHTS_SIZE         (24856)
#define AI_TCN_DATA_WEIGHTS_COUNT        (1)
#define AI_TCN_DATA_WEIGHT_1_SIZE        (24856)



#define AI_TCN_DATA_ACTIVATIONS_TABLE_GET() \
  (&g_tcn_activations_table[1])

extern ai_handle g_tcn_activations_table[1 + 2];



#define AI_TCN_DATA_WEIGHTS_TABLE_GET() \
  (&g_tcn_weights_table[1])

extern ai_handle g_tcn_weights_table[1 + 2];


#endif    /* TCN_DATA_PARAMS_H */
