from gailtf.baselines.common.mpi_running_mean_std import RunningMeanStd
from gailtf.baselines.common import tf_util as U
from gailtf.common.tf_util import *
import numpy as np


class TransitionClassifier(object):
  def __init__(self, env, hidden_size, entcoeff=0.001,  scope="adversary"):
    self.scope = scope
    self.observation_shape = env.observation_space.shape
    self.actions_shape = env.action_space.shape
    self.input_shape = tuple([o+a for o,a in zip(self.observation_shape, self.actions_shape)])
    self.num_actions = env.action_space.shape[0]
    self.hidden_size = hidden_size
    self.build_ph()
    # Build grpah
    generator_logits = self.build_graph(self.generator_obs_ph, self.generator_acs_ph, reuse=False)
    expert_logits = self.build_graph(self.expert_obs_ph, self.expert_acs_ph, reuse=True)
    # Build accuracy
    generator_acc = tf.reduce_mean(tf.to_float(tf.nn.sigmoid(generator_logits) < 0.5))
    expert_acc = tf.reduce_mean(tf.to_float(tf.nn.sigmoid(expert_logits) > 0.5))
    # Build regression loss
    # let x = logits, z = targets.
    # z * -log(sigmoid(x)) + (1 - z) * -log(1 - sigmoid(x))
    generator_loss = tf.nn.sigmoid_cross_entropy_with_logits(logits=generator_logits, labels=tf.zeros_like(generator_logits))
    generator_loss = tf.reduce_mean(generator_loss)
    expert_loss = tf.nn.sigmoid_cross_entropy_with_logits(logits=expert_logits, labels=tf.ones_like(expert_logits))
    expert_loss = tf.reduce_mean(expert_loss)
    # Build entropy loss
    logits = tf.concat([generator_logits, expert_logits], 0)
    entropy = tf.reduce_mean(logit_bernoulli_entropy(logits))
    entropy_loss = -entcoeff*entropy
    # Loss + Accuracy terms
    self.losses = [generator_loss, expert_loss, entropy, entropy_loss, generator_acc, expert_acc]
    self.loss_name = ["generator_loss", "expert_loss", "entropy", "entropy_loss", "generator_acc", "expert_acc"]
    self.total_loss = generator_loss + expert_loss + entropy_loss
    # Build Reward for policy
    self.reward_op = -tf.log(1-tf.nn.sigmoid(generator_logits)+1e-8)
    var_list = self.get_trainable_variables()
    self.lossandgrad = U.function([self.generator_obs_ph, self.generator_acs_ph, self.expert_obs_ph, self.expert_acs_ph],
                         self.losses + [U.flatgrad(self.total_loss, var_list)])

  def build_ph(self):
    self.generator_obs_ph = tf.placeholder(tf.float32, (None, ) + self.observation_shape, name="observations_ph")
    self.generator_acs_ph = tf.placeholder(tf.float32, (None, ) + self.actions_shape, name="actions_ph")
    self.expert_obs_ph = tf.placeholder(tf.float32, (None, ) + self.observation_shape, name="expert_observations_ph")
    self.expert_acs_ph = tf.placeholder(tf.float32, (None, ) + self.actions_shape, name="expert_actions_ph")

  def build_graph(self, obs_ph, acs_ph, reuse=False):
    with tf.variable_scope(self.scope):
      if reuse:
        tf.get_variable_scope().reuse_variables()

      with tf.variable_scope("obfilter"):
          self.obs_rms = RunningMeanStd(shape=self.observation_shape)

      obs = (obs_ph - self.obs_rms.mean) / self.obs_rms.std
      obscaled = obs / 255.0

      x = obscaled
      x = tf.nn.relu(U.conv2d(x, 8, "l1", [8, 8], [4, 4], pad="VALID"))
      x = tf.nn.relu(U.conv2d(x, 16, "l2", [4, 4], [2, 2], pad="VALID"))
      x = U.flattenallbut0(x)
      h = tf.concat([x, acs_ph], axis=1)
      h = tf.nn.relu(U.dense(h, 128, 'lin', U.normc_initializer(1.0)))
      logits = U.dense(h, 1, "logits", U.normc_initializer(0.01))
      # obs = (obs_ph - self.obs_rms.mean) / self.obs_rms.std
      # _input = tf.concat([obs, acs_ph], axis=1) # concatenate the two input -> form a transition
      # p_h1 = tf.contrib.layers.fully_connected(_input, self.hidden_size, activation_fn=tf.nn.tanh)
      # p_h2 = tf.contrib.layers.fully_connected(p_h1, self.hidden_size, activation_fn=tf.nn.tanh)
      # logits = tf.contrib.layers.fully_connected(p_h2, 1, activation_fn=tf.identity)
    return logits

  def get_trainable_variables(self):
    return tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, self.scope)

  def get_reward(self, obs, acs):
    sess = U.get_session()
    obs = np.expand_dims(obs, 0)
    acs = np.expand_dims(acs, 0)
    feed_dict = {self.generator_obs_ph:obs, self.generator_acs_ph:acs}
    reward = sess.run(self.reward_op, feed_dict) # LOOK HERE
    return reward

