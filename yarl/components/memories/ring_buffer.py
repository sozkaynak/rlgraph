# Copyright 2018 The YARL-Project, All Rights Reserved.
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

from yarl.components.memories.memory import Memory
import tensorflow as tf


class RingBuffer(Memory):
    """
    Simple ring-buffer to be used for on-policy sampling based on sample count
    or episodes. Fetches most recently added memories.
    """
    def __init__(
        self,
        record_space,
        capacity=1000,
        name="",
        scope="ring-buffer",
        sub_indexes=None,
        episode_semantics=False
    ):
        super(RingBuffer, self).__init__(record_space, capacity, name, scope, sub_indexes)
        # Variables.
        self.index = None
        self.size = None
        self.states = None
        self.episode_semantics = episode_semantics
        if self.episode_semantics:
            self.num_episodes = None
            self.episode_indices = None
        # Add Sockets and Computations.
        self.define_inputs("records")
        self.define_outputs("insert")
        self.add_computation("records", "insert", "insert")

    def create_variables(self):
        super(RingBuffer, self).create_variables()

        # Main buffer index.
        self.index = self.get_variable(name="index", dtype=int, trainable=False, initializer=0)
        # Number of elements present.
        self.size = self.get_variable(name="size", dtype=int, trainable=False, initializer=0)

        if self.episode_semantics:
            # Num episodes present.
            self.num_episodes = self.get_variable(name="num-episodes", dtype=int, trainable=False, initializer=0)

            # Terminal indices contiguously arranged.
            self.episode_indices = self.get_variable(
                name="episode-indices",
                shape=(self.capacity,),
                dtype=int,
                trainable=False,
                initializer=0
            )

    def _computation_insert(self, records):
        num_records = tf.shape(records.keys()[0])
        index = self.read_variable(self.index)
        update_indices = tf.range(start=index, stop=index + num_records) % self.capacity
        insert_terminal_slice = self.read_variable(self.record_registry['terminal'], update_indices)

        # Updates all the necessary sub-variables in the record.
        record_updates = self.record_space.flatten(mapping=lambda key, primitive: self.scatter_update_variable(
            variable=self.record_registry[key],
            indices=update_indices,
            updates=records[key]
        ))

        # Update indices and size.
        with tf.control_dependencies(control_inputs=list(record_updates.values())):
            index_updates = list()
            if self.episode_semantics:
                # Episodes before insert.
                num_episodes = self.read_variable(self.num_episodes)

                # Episodes in range we inserted to.
                episodes_in_insert_range = tf.reduce_sum(input_tensor=insert_terminal_slice, axis=0)

                # Newly inserted episodes.
                inserted_episodes = tf.reduce_sum(input_tensor=records['terminal'], axis=0)
                num_episode_update = num_episodes - episodes_in_insert_range + inserted_episodes

                # Remove previous episodes in inserted range.
                # TODO test if these can all update in parallel without problems.
                index_updates.append(self.assign_variable(
                        variable=self.episode_indices[:num_episodes + 1 - episodes_in_insert_range],
                        value=self.episode_indices[episodes_in_insert_range: num_episodes + 1]
                    ))

                # Insert new episodes starting at previous count minus the ones we removed,
                # ending at previous count minus removed + inserted.
                slice_start = num_episodes - episodes_in_insert_range - 1
                slice_end = num_episode_update + 1
                index_updates.append(self.assign_variable(
                    variable=self.episode_indices[slice_start:slice_end],
                    value=tf.boolean_mask(tensor=update_indices, mask=records['terminal'])
                ))

                # Assign final new episode count.
                index_updates.append(self.assign_variable(self.num_episodes, num_episode_update))

            index_updates.append(self.assign_variable(variable=self.index, value=(index + num_records) % self.capacity))
            update_size = tf.minimum(x=(self.read_variable(self.size) + num_records), y=self.capacity)
            index_updates.append(self.assign_variable(self.size, value=update_size))

        # Nothing to return.
        with tf.control_dependencies(control_inputs=index_updates):
            return tf.no_op()

    def read_records(self, indices):
        """
        Obtains record values for the provided indices.

        Args:
            indices Union[ndarray, tf.Tensor]: Indices to read. Assumed to be not contiguous.

        Returns:
             dict: Record value dict.
        """
        records = dict()
        for name, variable in self.record_registry:
            records[name] = self.read_variable(variable, indices)
        return records

    def _computation_get_records(self, num_records):
        stored_records = self.read_variable(self.size)
        index = self.read_variable(self.index)

        # We do not return duplicate records here.
        available_records = tf.minimum(x=stored_records, y=num_records)
        indices = tf.range(start=index - 1 - available_records, limit=index - 1) % self.capacity

        # TODO zeroing out terminals per flag?
        return self.read_records(indices=indices)

    def _computation_get_episodes(self, num_episodes):
        stored_episodes = self.read_variable(self.num_episodes)
        available_episodes = tf.minimum(x=num_episodes, y=stored_episodes)

        start = self.episode_indices[stored_episodes - available_episodes - 1] + 1
        limit = self.episode_indices[stored_episodes - 1]
        limit += tf.where(condition=(start < limit), x=0, y=self.capacity)

        indices = tf.range(start=start, limit=limit) % self.capacity

        return self.read_records(indices=indices)
