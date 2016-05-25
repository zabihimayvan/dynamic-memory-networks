import argparse


LEARNING_RATE = 0.001
REG = 0.0001
MAX_EPOCHS = 20
DROPOUT = 0.2
OUT_DIR = './outputs'
TASK = 6
HIDDEN_SIZE = 50
ATTENTION_GATE_HIDDEN_SIZE = 50
UPDATE_LENGTH = 100

def parse_args():
  """
  Parses the command line input.

  """
  parser = argparse.ArgumentParser()
  parser.add_argument('-lr', default=LEARNING_RATE, help='learning rate', type=float)
  parser.add_argument('-reg', default=REG, help='regularization', type=float)
  parser.add_argument('-epochs', default=MAX_EPOCHS, help='number of epochs', type=int)
  parser.add_argument('-dropout', default=DROPOUT, help='dropout rate', type=float)
  parser.add_argument('-outdir', default=OUT_DIR, help='location of output directory')
  parser.add_argument('-task', default=TASK, help='facebook babi task number', type=int)
  parser.add_argument('-hidden_size', default=HIDDEN_SIZE, help='hidden size', type=int)
  parser.add_argument('-attention_hidden_size', default=ATTENTION_GATE_HIDDEN_SIZE, help='hidden size of attention gate', type=int)
  parser.add_argument('-print_every', default=UPDATE_LENGTH, help='number of training elements to train on before an update is printed', type=int)

  args = parser.parse_args()

  params = {
  'LEARNING_RATE': args.lr,
  'REG': args.reg,
  'MAX_EPOCHS': args.epochs,
  'DROPOUT': args.dropout,
  'OUT_DIR': args.outdir,
  'TASK': args.task,
  'HIDDEN_SIZE': args.hidden_size,
  'ATTENTION_GATE_HIDDEN_SIZE': args.attention_hidden_size,
  'UPDATE_LENGTH': args.print_every
  }

  return params



