# Copyright 2018 The RLgraph authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from functools import partial

from rlgraph.components.optimizers.horovod_optimizer import HorovodOptimizer
from rlgraph.components.optimizers.local_optimizers import *
from rlgraph.components.optimizers.multi_gpu_sync_optimizer import MultiGpuSyncOptimizer
from rlgraph.components.optimizers.optimizer import Optimizer
from rlgraph.components.optimizers.dynamic_batching_optimizer import DynamicBatchingOptimizer


Optimizer.__lookup_classes__ = dict(
    horovod=HorovodOptimizer,
    dynamic_batching=DynamicBatchingOptimizer,
    multigpu=MultiGpuSyncOptimizer,
    multigpusync=MultiGpuSyncOptimizer,
    # LocalOptimizers.
    gradientdescent=GradientDescentOptimizer,
    adagrad=AdagradOptimizer,
    adadelta=AdadeltaOptimizer,
    adam=AdamOptimizer,
    nadam=NadamOptimizer,
    sgd=SGDOptimizer,
    rmsprop=RMSPropOptimizer
)

# The default Optimizer to use if a spec is None and no args/kwars are given.
Optimizer.__default_constructor__ = partial(GradientDescentOptimizer, learning_rate=0.0001)

__all__ = ["Optimizer", "LocalOptimizer", "HorovodOptimizer", "MultiGpuSyncOptimizer",
           "GradientDescentOptimizer", "SGDOptimizer",
           "AdagradOptimizer", "AdadeltaOptimizer", "AdamOptimizer", "NadamOptimizer",
           "RMSPropOptimizer", "DynamicBatchingOptimizer"]
