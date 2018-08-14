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

from rlgraph import get_backend, RLGraphError
from rlgraph.components.component import Component
from rlgraph.components.explorations.epsilon_exploration import EpsilonExploration
from rlgraph.components.common.noise_components import NoiseComponent
from rlgraph.spaces import IntBox, FloatBox
from rlgraph.spaces.space_utils import sanity_check_space
from rlgraph.utils.util import dtype, get_shape

if get_backend() == "tf":
    import tensorflow as tf


class Exploration(Component):
    """
    A Component that can be plugged on top of a Policy's output to produce action choices.
    It includes noise and/or epsilon-based exploration options as well as an out-Socket to draw actions from
    the Policy's distribution - either by sampling or by deterministically choosing the max-likelihood value.

    API:
        get_action(sample_deterministic, sample_stochastic[, time_step]): Returns an action:
            - epsilon-based exploration: Action depends on time-step (e.g. epsilon-decay).
            - noise-based exploration: Noise is added to the sampled action.
            - No exploration: Action depends on ctor parameter `non_explore_behavior`. Either always deterministic
                or stochastic choice.
        # TODO: actions (any): A batch of actions taken from a batch of NN-outputs without any exploration.
    """
    def __init__(self, non_explore_behavior="max-likelihood", epsilon_spec=None, noise_spec=None,
                 scope="exploration", **kwargs):
        """
        Args:
            non_explore_behavior (str): One of:
                max-likelihood: When not exploring, pick an action deterministically (max-likelihood) from the
                    Policy's distribution.
                sample: When not exploring, pick an action stochastically according to the Policy's distribution.
                random: When not exploring, pick an action randomly.
            epsilon_spec (any): The spec or Component object itself to construct an EpsilonExploration Component.
            noise_spec (dict): The specification dict for a noise generator that adds noise to the NN's output.
        """
        super(Exploration, self).__init__(scope=scope, **kwargs)

        self.action_space = None
        self.non_explore_behavior = non_explore_behavior

        self.epsilon_exploration = None
        self.noise_component = None

        # Don't allow both epsilon and noise component
        if epsilon_spec and noise_spec:
            raise RLGraphError("Cannot use both epsilon exploration and a noise component at the same time.")

        # Add epsilon component.
        if epsilon_spec:
            self.epsilon_exploration = EpsilonExploration.from_spec(epsilon_spec)
            self.add_components(self.epsilon_exploration)

            # Define our interface.
            def get_action(self, sample_deterministic, sample_stochastic, time_step, use_exploration=True):
                epsilon_decisions = self.call(self.epsilon_exploration.do_explore, sample_deterministic, time_step)
                return self.call(self._graph_fn_pick, use_exploration, epsilon_decisions,
                                  sample_deterministic, sample_stochastic)

        # Add noise component.
        elif noise_spec:
            self.noise_component = NoiseComponent.from_spec(noise_spec)
            self.add_components(self.noise_component)

            def get_action(self, sample_deterministic, sample_stochastic, time_step=0, use_exploration=True):
                noise = self.call(self.noise_component.get_noise)
                return self.call(self._graph_fn_add_noise, use_exploration, noise,
                                  sample_deterministic, sample_stochastic)

        # Don't explore at all.
        else:
            if self.non_explore_behavior == "max-likelihood":
                def get_action(self, sample_deterministic, sample_stochastic, time_step=0, use_exploration=False):
                    return sample_deterministic
            else:
                def get_action(self, sample_deterministic, sample_stochastic, time_step=0, use_exploration=False):
                    return sample_stochastic

        self.define_api_method("get_action", get_action)

    def check_input_spaces(self, input_spaces, action_space=None):
        assert action_space is not None
        self.action_space = action_space.with_batch_rank()
        assert self.action_space.has_batch_rank, "ERROR: `self.action_space` does not have batch rank!"

        if self.epsilon_exploration and self.noise_component:
            # Check again at graph creation? This is currently redundant to the check in __init__
            raise RLGraphError("Cannot use both epsilon exploration and a noise component at the same time.")

        if self.epsilon_exploration:
            sanity_check_space(self.action_space, allowed_types=[IntBox], must_have_categories=True,
                               num_categories=(1, None))
        elif self.noise_component:
            sanity_check_space(self.action_space, allowed_types=[FloatBox])

    def _graph_fn_pick(self, use_exploration, epsilon_decisions, sample_deterministic, sample_stochastic):
        """
        Exploration for discrete action spaces.
        Either pick a random action (if `use_exploration` and `epsilon_decision` are True),
            or return non-explorative action.

        Args:
            use_exploration (DataOp): The master switch determining, whether to use exploration or not.
            epsilon_decisions (DataOp): The bool coming from the epsilon-exploration component specifying
                whether to use exploration or not (per batch item).
            sample_deterministic (DataOp): The output from a distribution's "sample_deterministic" API-method.
            sample_stochastic (DataOp): The output from a distribution's "sample_stochastic" API-method.

        Returns:
            DataOp: The DataOp representing the action. This will match the shape of self.action_space.
        """
        if get_backend() == "tf":
            batch_size = tf.shape(sample_stochastic)[0]
            random_actions = tf.random_uniform(shape=(batch_size,) + self.action_space.shape,
                                               maxval=self.action_space.num_categories,
                                               dtype=dtype("int"))

            return tf.where(
                # `use_exploration` given as actual bool or as tensor?
                condition=epsilon_decisions if type(use_exploration) == bool else tf.logical_and(use_exploration,
                                                                                                 epsilon_decisions),
                x=random_actions,
                y=sample_deterministic if self.non_explore_behavior == "max-likelihood" else sample_stochastic
            )

    def _graph_fn_add_noise(self, use_exploration, noise, sample_deterministic, sample_stochastic):
        """
        Noise for continuous action spaces.
        Return the action with added noise.

        Args:
            use_exploration (DataOp): The master switch determining, whether to add noise or not.
            noise (DataOp): The noise coming from the noise component.
            sample_deterministic (DataOp): The output from a distribution's "sample_deterministic" API-method.
            sample_stochastic (DataOp): The output from a distribution's "sample_stochastic" API-method.

        Returns:
            DataOp: The DataOp representing the action. This will match the shape of self.action_space.

        """
        if get_backend() == "tf":
            sampler = sample_deterministic if self.non_explore_behavior == 'max-likelihood' else sample_stochastic
            return tf.cond(
                use_exploration, true_fn=lambda: sampler + noise, false_fn=lambda: sampler
            )
