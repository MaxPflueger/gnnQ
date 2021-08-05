import torch
from model import HGNN
from utils import load_triples, create_triples_with_ids, create_y_vector, create_index_matrices, load_answers
import numpy as np
import argparse
from torchmetrics import Accuracy, Precision, Recall

parser = argparse.ArgumentParser(description='Bla bla')
parser.add_argument('--train_data', type=str, default='train')
parser.add_argument('--val_data', type=str, default='val')
parser.add_argument('--base_dim', type=int, default=16)
parser.add_argument('--num_layers', type=int, default=3)
parser.add_argument('--epochs', type=int, default=20)
parser.add_argument('--val_epochs', type=int, default=10)
parser.add_argument('--lr', type=int, default=0.1)
args = parser.parse_args()

base_dim = args.base_dim
num_layers = args.num_layers
epochs = args.epochs
learning_rate = args.lr
val_epochs = args.val_epochs

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

triples = load_triples(args.train_data + '/graph.ttl')
triples, entity2id, relation2id, _, _ = create_triples_with_ids(triples)
num_nodes = len(entity2id)
num_rel = len(relation2id)
answers = load_answers('answers.pickle')
answers = [entity2id[entity[0]] for entity in answers]
y_train = create_y_vector(answers, num_nodes)
subquery_answers = load_answers('subquery_answers.pickle')
subquery_answers = [[entity2id[entity] for entity in answer] for answer in subquery_answers]
x_train = torch.cat((torch.ones(num_nodes,1), torch.zeros(num_nodes,base_dim - 1)), dim=1)
hyperedge_index_train, hyperedge_type_train, num_edge_types_by_shape_train = create_index_matrices(triples, num_rel, subquery_answers)

# Make sure relations types in all graphs have the same ids -- why did this work up to now when applying model to val data?
triples_val = load_triples(args.val_data + '/graph.ttl')
triples_val, entity2id_val, _, _, _ = create_triples_with_ids(args.val_data + '/graph.ttl', relation2id)
num_nodes_val = len(entity2id_val)
answers = load_answers(args.val_data + '/answers.npy')
y_val = create_y_vector(answers, num_nodes_val)
subquery_answers_val = load_answers('val_subquery_answers.npy')
subquery_answers_val = [[entity2id_val[entity] for entity in answer] for answer in subquery_answers_val]
x_val = torch.cat((torch.ones(num_nodes_val,1), torch.zeros(num_nodes_val,base_dim - 1)), dim=1)
hyperedge_index_val, hyperedge_type_val, num_edge_types_by_shape_val = create_index_matrices(triples_val, num_rel, subquery_answers_val)

model = HGNN(base_dim, num_edge_types_by_shape_train, num_layers)
model.to(device)
help = model.parameters()
for param in model.parameters():
    print(type(param.data), param.size())

optimizer = torch.optim.SGD(model.parameters(), lr=learning_rate)
loss_fn = torch.nn.BCELoss()

accuracy = Accuracy(threshold=0.5)
precision = Precision(threshold=0.5)
recall = Recall(threshold=0.5)

def train_loop(model, loss_fn, optimizer, epochs, hyperedge_index_train, hyperedge_type_train, x_train, y_train, hyperedge_index_val, hyperedge_type_val, x_val, y_val):
    for i in range(epochs):
        model.train()
        pred = model(x_train, hyperedge_index_train, hyperedge_type_train).flatten()
        pred = torch.cat((pred[answers], pred[torch.randint(x_train.size()[0], size=(len(answers),))]), dim=0)
        loss = loss_fn(pred, torch.cat((torch.ones(len(answers)), torch.zeros(len(answers))), dim = 0))
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if i % val_epochs == 0:
            model.eval()
            pred = model(x_val, hyperedge_index_val, hyperedge_type_val).flatten()
            acc = accuracy(pred, y_val)
            pre = precision(pred, y_val)
            rec = recall(pred, y_val)
            print('Val')
            print(acc)
            print(pre)
            print(rec)


train_loop(model, loss_fn, optimizer, epochs, hyperedge_index_train, hyperedge_type_train, x_train, y_train, hyperedge_index_val, hyperedge_type_val, x_val, y_val)

torch.save(model.state_dict(), './model.pt')