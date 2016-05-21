import getpass
import sys
import time

import numpy as np
from copy import deepcopy
import random

import tensorflow as tf
from tensorflow.models.rnn import rnn, rnn_cell
from get_babi_data import get_task_6_train
from get_babi_data import get_task_6_test
from get_glove import load_glove_vectors
from get_babi_data import get_task_1_train
from get_babi_data import get_task_1_test
from tensorflow.python.ops.seq2seq import sequence_loss
from format_data import split_training_data
from format_data import format_data
from random import shuffle

#### MODEL PARAMETERS ####

WORD_VECTOR_LENGTH = 50
VOCAB_LENGTH = 10000
LEARNING_RATE = 0.001
NUM_CLASSES = 2
HIDDEN_SIZE = 50
ATTENTION_GATE_HIDDEN_SIZE = 50
EARLY_STOPPING = 2
MAX_INPUT_LENGTH = 200
MAX_QUESTION_LENGTH = 20
MAX_EPOCHS = 20
MAX_EPISODES = 3
MAX_INPUT_SENTENCES = 20

# Number of training elements to train on before an update is printed
UPDATE_LENGTH = 1000


#### END MODEL PARAMETERS ####

def add_placeholders():
  """Generate placeholder variables to represent the input tensors

  These placeholders are used as inputs by the rest of the model building
  code and will be fed data during training.  Note that when "None" is in a
  placeholder's shape, it's flexible

  Adds following nodes to the computational graph.
  (When None is in a placeholder's shape, it's flexible)

  input_placeholder: Input placeholder tensor of shape
                     (None, num_steps), type tf.int32
  labels_placeholder: Labels placeholder tensor of shape
                      (None, num_steps), type tf.float32
  dropout_placeholder: Dropout value placeholder (scalar),
                       type tf.float32

  Add these placeholders to self as the instance variables

    input_placeholder
    question_placeholder
    labels_placeholder

  """

  input_placeholder = tf.placeholder(tf.float32, shape=[None, WORD_VECTOR_LENGTH])
  input_length_placeholder = tf.placeholder(tf.int32, shape=[1])
  end_of_sentences_placeholder = tf.placeholder(tf.int32, shape=[None])
  question_placeholder = tf.placeholder(tf.float32, shape=[None, WORD_VECTOR_LENGTH])
  question_length_placeholder = tf.placeholder(tf.int32, shape=[1])
  labels_placeholder = tf.placeholder(tf.float32, shape=[None, NUM_CLASSES])
  return input_placeholder, input_length_placeholder, end_of_sentences_placeholder, question_placeholder, \
         question_length_placeholder, labels_placeholder


def RNN(X, num_words_in_X, hidden_size, max_input_size):
  # Reshape `X` as a vector. -1 means "set this dimension automatically".
  X_as_vector = tf.reshape(X, [-1])

  # Create another vector containing zeroes to pad `X` to (MAX_INPUT_LENGTH * WORD_VECTOR_LENGTH) elements.
  zero_padding = tf.zeros([max_input_size * WORD_VECTOR_LENGTH] - tf.shape(X_as_vector), dtype=X.dtype)

  # Concatenate `X_as_vector` with the padding.
  X_padded_as_vector = tf.concat(0, [X_as_vector, zero_padding])

  # Reshape the padded vector to the desired shape.
  X_padded = tf.reshape(X_padded_as_vector, [max_input_size, WORD_VECTOR_LENGTH])

  # Split X into a list of tensors of length MAX_INPUT_LENGTH where each tensor is a 1xWORD_VECTOR_LENGTH vector
  # of the word vectors
  X = tf.split(0, max_input_size, X_padded)

  gru_cell = rnn_cell.GRUCell(num_units=hidden_size, input_size=WORD_VECTOR_LENGTH)

  outputs, state = rnn.rnn(gru_cell, X, sequence_length=(num_words_in_X), dtype=tf.float32)

  return outputs, state


def count_positive_and_negative(answer_vecs):
  num_positive = 0
  for answer_vec in answer_vecs:

    if answer_vec[0, 0] == 1:
      num_positive = num_positive + 1

  num_negative = len(answer_vecs) - num_positive

  return num_positive, num_negative


# Takes in an input matrix of size (number of words in input) x (WORD_VECTOR_LENGTH) with the input word vectors
# and a tensor the length of the number of sentences in the input with the index of the word that ends each
# sentence and returns a list of the states after the end of each sentence to be fed to other modules.
def input_module(input_placeholder, input_length_placeholder, index_end_of_sentences):
  # Get outputs after every word
  outputs, state = RNN(input_placeholder, input_length_placeholder, HIDDEN_SIZE, MAX_INPUT_LENGTH)

  # Convert list of outputs into a tensor of dimension (number of words in input) x (INPUT_HIDDEN_SIZE)
  output_mat = tf.concat(0, outputs)

  # Only project the state at the end of each sentence
  sentence_representations_mat = tf.gather(output_mat, index_end_of_sentences)

  # Reshape `X` as a vector. -1 means "set this dimension automatically".
  sentences_as_vector = tf.reshape(sentence_representations_mat, [-1])

  # Create another vector containing zeroes to pad `X` to (MAX_INPUT_LENGTH * WORD_VECTOR_LENGTH) elements.
  zero_padding = tf.zeros([MAX_INPUT_SENTENCES * HIDDEN_SIZE] - tf.shape(sentences_as_vector), dtype=sentences_as_vector.dtype)

  # Concatenate `X_as_vector` with the padding.
  sentences_padded_as_vector = tf.concat(0, [sentences_as_vector, zero_padding])

  # Reshape the padded vector to the desired shape.
  sentences_padded = tf.reshape(sentences_padded_as_vector, [MAX_INPUT_SENTENCES, WORD_VECTOR_LENGTH])

  # Split X into a list of tensors of length MAX_INPUT_LENGTH where each tensor is a 1xWORD_VECTOR_LENGTH vector
  # of the word vectors
  sentence_representations = tf.split(0, MAX_INPUT_SENTENCES, sentences_padded)

  return sentence_representations, tf.shape(sentence_representations_mat)[0]


def question_module(question_placeholder, num_words_in_question):
  outputs, state = RNN(question_placeholder, num_words_in_question, HIDDEN_SIZE, MAX_QUESTION_LENGTH)

  return state


def episodic_memory_module(sentence_states, number_of_sentences, question_state):
  # Initialize all matrices and biases
  # TODO figure out is reuse should be true here
  with tf.variable_scope("episodic_memory_module"):
    W_b = tf.get_variable("W_b", shape=(HIDDEN_SIZE, HIDDEN_SIZE))
    W_1 = tf.get_variable("W_1", shape=(7 * HIDDEN_SIZE + 2, ATTENTION_GATE_HIDDEN_SIZE))
    b_1 = tf.get_variable("b_1", shape=(1, ATTENTION_GATE_HIDDEN_SIZE))
    W_2 = tf.get_variable("W_2", shape=(ATTENTION_GATE_HIDDEN_SIZE, 1))
    b_2 = tf.get_variable("b_2", shape=(1, 1))

  with tf.variable_scope("episode") as episode_scope:
    gru_cell_episode = rnn_cell.GRUCell(num_units=HIDDEN_SIZE)

  with tf.variable_scope("memory") as memory_scope:
    gru_cell_memory = rnn_cell.GRUCell(num_units=HIDDEN_SIZE)

  memory_states = []

  # Initialize first memory state to be the question state
  memory_states.append(question_state)

  q = question_state

  # There is an episode e and a previous memory state m_prev for each pass through the data
  for i in range(MAX_EPISODES):

    m_prev = memory_states[-1]

    if i == 1:
      memory_scope.reuse_variables()

    # Initialize first hidden state for episode to be zeros
    # TODO figure out if this is the right thing to do
    h = tf.zeros([1, HIDDEN_SIZE])
    final_h = tf.zeros([1, HIDDEN_SIZE])

    episode_states = []

    # Loop over the sentences for each episode
    for j in range(MAX_INPUT_SENTENCES):

      if j == 1:
        episode_scope.reuse_variables()

      c_t = sentence_states[j]

      # Compute z
      z = tf.concat(1, [c_t, m_prev, tf.mul(c_t, q), tf.mul(c_t, m_prev), tf.abs(tf.sub(c_t, q)),
                        tf.abs(tf.sub(c_t, m_prev)), tf.matmul(c_t, tf.matmul(W_b, tf.transpose(q))),
                        tf.matmul(c_t, tf.matmul(W_b, tf.transpose(m_prev)))])

      # Compute G
      attention_gate_hidden_state = tf.tanh(tf.add(tf.matmul(z, W_1), b_1))
      g = tf.sigmoid(tf.add(tf.matmul(attention_gate_hidden_state, W_2), b_2))

      # Compute next hidden state
      h_prev = h
      # with tf.variable_scope("episode", reuse=True):
      #gru_cell_episode = rnn_cell.GRUCell(num_units=HIDDEN_SIZE)
      output, gru_state = gru_cell_episode(c_t, h_prev)
      h = g * gru_state + (1 - g) * h_prev

      # TODO fix so this doesnt run for max sentences every time
      h = tf.cond(number_of_sentences >= j, lambda: tf.zeros([1,HIDDEN_SIZE]), lambda: h)

      final_h = tf.cond(tf.equal(number_of_sentences, j-1), lambda: h, lambda: final_h)

    # Episode state is the final hidden state after pass over the data
    e = final_h

    # Compute next m with previous m and episode
    # with tf.variable_scope("memory", reuse=True):
    #gru_cell_memory = rnn_cell.GRUCell(num_units=HIDDEN_SIZE)
    output, m = gru_cell_memory(e, m)

  # Return final memory state
  return m


def answer_module(episodic_memory_state):
  with tf.variable_scope("answer_module"):
    W_out = tf.get_variable("W_out", shape=(HIDDEN_SIZE, NUM_CLASSES))
    b_out = tf.get_variable("b_out", shape=(1, NUM_CLASSES))

  prediction_probs = tf.nn.softmax(tf.matmul(episodic_memory_state, W_out) + b_out)

  return prediction_probs


def get_end_of_sentences(words):
  end_of_sentences = []

  for i in range(len(words)):
    word = words[i]
    if word == ".":
      end_of_sentences.append(i)

  return end_of_sentences


def run_baseline():
  # Get train dataset for task 6
  train_total = get_task_6_train()

  train, validation = split_training_data(train_total)

  # Get test dataset for task 6
  test = get_task_6_test()

  # Get word to glove vectors dictionary
  glove_dict = load_glove_vectors()

  # Split data into batches

  # Get data into word vector format
  text_train, question_train, answer_train = format_data(train, glove_dict)
  text_val, question_val, answer_val = format_data(validation, glove_dict)
  text_test, question_test, answer_test = format_data(test, glove_dict)

  num_positive_train, num_negative_train = count_positive_and_negative(answer_train)

  # Print summary statistics
  print "Training samples: {}".format(len(train))
  print "Positive training samples: {}".format(num_positive_train)
  print "Negative training samples: {}".format(num_negative_train)
  print "Validation samples: {}".format(len(validation))
  print "Testing samples: {}".format(len(test))

  # Add placeholders
  input_placeholder, input_length_placeholder, end_of_sentences_placeholder, question_placeholder, \
  question_length_placeholder, labels_placeholder, = add_placeholders()

  # Input module
  with tf.variable_scope("input"):
    sentence_states, number_of_sentences = input_module(input_placeholder, input_length_placeholder, end_of_sentences_placeholder)

  # Question module
  with tf.variable_scope("question"):
    question_state = question_module(question_placeholder, question_length_placeholder)

  # Episodic memory moduel
  with tf.variable_scope("episode"):
      episodic_memory_state = episodic_memory_module(sentence_states, number_of_sentences, question_state)

  # Answer module
  with tf.variable_scope("answer"):
    prediction_probs = answer_module(episodic_memory_state)

  # To get predictions perform a max over probabilities
  prediction = tf.argmax(prediction_probs, 1)

  # Compute loss
  cost = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(prediction_probs, labels_placeholder))

  # Add optimizer
  optimizer = tf.train.AdamOptimizer(learning_rate=LEARNING_RATE).minimize(cost)

  # Initialize all variables
  init = tf.initialize_all_variables()
  saver = tf.train.Saver()

  # Train over multiple epochs
  with tf.Session() as sess:
    best_loss = float('inf')
    best_val_epoch = 0

    sess.run(init)
    # train until we reach the maximum number of epochs
    for epoch in range(MAX_EPOCHS):

      print 'Epoch {}'.format(epoch)
      start = time.time()
      ###

      # Shuffle training data
      # TODO put this in a function
      # train_shuf = []
      # train_input_shuf = []
      # train_question_shuf = []
      # train_answer_shuf = []
      # index_shuf = range(len(text_train))
      # shuffle(index_shuf)
      # for i in index_shuf:
      #   train_shuf.append(train[i])
      #   train_input_shuf.append(text_train[i])
      #   train_question_shuf.append(question_train[i])
      #   train_answer_shuf.append(answer_train[i])
      #
      # train = train_shuf
      # text_train = train_input_shuf
      # question_train = train_question_shuf
      # answer_train = train_answer_shuf

      total_training_loss = 0
      num_correct = 0

      prev_prediction = 0

      # Compute average loss on training data
      for i in range(len(train)):

        index_end_of_sentences = get_end_of_sentences(train[i][0])
        num_words_in_inputs = [np.shape(text_train[i])[0]]
        num_words_in_question = [np.shape(question_train[i])[0]]

        # Print all inputs
        # print "Current input word vectors: {}".format(text_train[i])
        # print "Current number of words in input: {}".format(num_words_in_inputs)
        # print "Current question word vectors: {}".format(question_train[i])
        # print "Current number of words in question: {}".format(num_words_in_question)

        # print i
        # print num_words_in_inputs
        # print len(num_words_in_inputs)
        # print np.shape(num_words_in_inputs)
        loss, current_pred, probs, _ = sess.run(
          [cost, prediction, prediction_probs, optimizer],
          feed_dict={input_placeholder: text_train[i],
                     input_length_placeholder: num_words_in_inputs,
                     end_of_sentences_placeholder: index_end_of_sentences,
                     question_placeholder: question_train[i],
                     question_length_placeholder: num_words_in_question,
                     labels_placeholder: answer_train[i]})

        # Print all outputs and intermediate steps for debugging
        # print "Current input matrix with all words and padding: {}".format(X_input)
        # print "Current input matrix with all words and padding: {}".format(X_padded_input)
        # print "Current input matrix with all words and padding: {}".format(X_padded_question)
        # print "Current input ouput vector: {}".format(input_output_vec)
        # print "Current input state vector: {}".format(input_state_vec)
        # print "Current question ouput vector: {}".format(question_output_vec)
        # print "Current question state vector: {}".format(question_state_vec)
        # print "Current concatenated input and question embedding vector: {}".format(input_and_question_vec)

        # print "Current pred probs: {}".format(probs)
        # print "Current pred: {}".format(current_pred[0])
        # print "Current answer vector: {}".format(answer_train[i])
        # print "Current answer: {}".format(np.argmax(answer_train[i]))
        # print "Current loss: {}".format(loss)

        if current_pred[0] == np.argmax(answer_train[i]):
          num_correct = num_correct + 1

        # Print a training update
        if i % UPDATE_LENGTH == 0:
          print "Current average training loss: {}".format(total_training_loss / (i + 1))
          print "Current training accuracy: {}".format(float(num_correct) / (i + 1))
          # print "Current input matrix with all words and padding: {}".format(X_input)
          # print "Current input matrix with all words and padding: {}".format(X_padded_input)
          # print "Current input matrix with all words and padding: {}".format(X_padded_question)
          # print "Current input ouput vector: {}".format(input_output_vec)
          # print "Current input state vector: {}".format(input_state_vec)
          # print "Current question ouput vector: {}".format(question_output_vec)
          # print "Current question state vector: {}".format(question_state_vec)
          # print "Current concatenated input and question embedding vector: {}".format(input_and_question_vec)
          # print "Current W: {}".format(W_out_mat)
          # print "Current b: {}".format(b_out_mat)

        total_training_loss = total_training_loss + loss

        # Check if prediction changed
        # if prev_prediction != current_pred[0]:
        #   print "Prediction changed"

        prev_prediction = current_pred[0]

      average_training_loss = total_training_loss / len(train)
      training_accuracy = float(num_correct) / len(train)

      validation_loss = float('inf')

      total_validation_loss = 0
      num_correct_val = 0
      # Compute average loss on validation data
      for i in range(len(validation)):
        num_words_in_inputs = [np.shape(text_val[i])[0]]
        num_words_in_question = [np.shape(question_val[i])[0]]
        loss, current_pred, probs, input_output_vec, input_state_vec, X_padded_input, question_output_vec, question_state_vec, X_padded_question, input_and_question_vec, W_out_mat, b_out_mat = sess.run(
          [cost, prediction, prediction_probs, input_output[num_words_in_inputs[0] - 1], input_state, X_input,
           question_output[num_words_in_question[0] - 1], question_state, Q_input, input_and_question, W_out, b_out],
          feed_dict={input_placeholder: text_val[i],
                     input_length_placeholder: num_words_in_inputs,
                     question_placeholder: question_val[i],
                     question_length_placeholder: num_words_in_question,
                     labels_placeholder: answer_val[i]})

        if current_pred == np.argmax(answer_val[i]):
          num_correct_val = num_correct_val + 1

        total_validation_loss = total_validation_loss + loss

      average_validation_loss = total_validation_loss / len(validation)
      validation_accuracy = float(num_correct_val) / len(validation)

      print 'Training loss: {}'.format(average_training_loss)
      print 'Training accuracy: {}'.format(training_accuracy)
      print 'Validation loss: {}'.format(average_validation_loss)
      print 'Validation accuracy: {}'.format(validation_accuracy)
      if average_validation_loss < best_loss:
        best_loss = average_validation_loss
        best_val_epoch = epoch
        saver.save(sess, '../data/weights/rnn.weights')
        print "Weights saved"
      # if epoch - best_val_epoch > EARLY_STOPPING:
      #   break
      print 'Total time: {}'.format(time.time() - start)

    # Compute average loss on testing data with best weights
    saver.restore(sess, '../data/weights/rnn.weights')

    sess.run(accuracy,
             feed_dict={input_placeholder: text_val, labels_placeholder: answer_val,
                        initial_state: np.zeros(HIDDEN_SIZE)})

    print '=-=' * 5
    print 'Test perplexity: {}'.format(accuracy)
    print '=-=' * 5

    # TODO add input loop so we can test and debug with our own examples
    input = ""
    while input:
      # Run model

      input = raw_input('> ')


if __name__ == "__main__":
  run_baseline()
