import torch
import torch.nn as nn
import torch_scatter as scatter


class HGNNLayer(nn.Module):
    def __init__(self, input_dim, output_dim, num_edge_types_by_shape):
        super(HGNNLayer, self).__init__()
        self.num_edge_types_by_shape = num_edge_types_by_shape
        # Includes bias
        self.C = torch.nn.Linear(input_dim, output_dim)
        self.A = torch.nn.ParameterDict({})
        # Shape is the number of src nodes -- we consider edges of the form ((u_0,...,u_{n-1}), R, v)
        for shape in num_edge_types_by_shape:
            self.A[str(shape)] = torch.nn.Parameter(
                torch.zeros(num_edge_types_by_shape[shape], input_dim * shape, output_dim))
            nn.init.xavier_normal_(self.A[str(shape)])

    # h = x_iC + b + SUM_shape SUM_type SUM_neighbours x_jA_shape,type
    def forward(self, x, hyperedge_index_by_shape, hyperedge_type_by_shape):
        # Some basic checks to verify input
        for shape in hyperedge_index_by_shape:
            assert (shape in hyperedge_type_by_shape)
            assert (hyperedge_index_by_shape[shape].size()[1] == (hyperedge_type_by_shape[shape].size()[0] * shape))
            assert (torch.max(hyperedge_type_by_shape[shape]) <= self.num_edge_types_by_shape[shape] - 1)
        # Not sure whether these tensors are automatically move to device
        index = torch.tensor([], dtype=torch.int16)
        msgs = torch.tensor([], dtype=torch.float16)
        # Loop through hyperedges with different shapes (num of src nodes)
        for shape in hyperedge_index_by_shape:
            # Loop through edge_types for every shape
            for edge_type in range(0, self.num_edge_types_by_shape[shape]):
                mask = (hyperedge_type_by_shape[shape] == edge_type)
                mask = mask.unsqueeze(1).repeat(1, shape).flatten()
                i = torch.reshape(hyperedge_index_by_shape[shape][1][mask], (-1, shape))
                if (i.nelement() != 0):
                    # Compute indices for scatter function
                    i = i[:, 0]
                    index = torch.cat((index, i), dim=0)
                    # Compute src for scatter function
                    tmp = x[hyperedge_index_by_shape[shape][0][mask]]
                    s = tmp.size()[1] * shape
                    # Concat feature vectors of src nodes for hyperedges
                    tmp = torch.reshape(tmp, (-1, s))
                    weights = self.A[str(shape)][edge_type]
                    # Linear transformation of messages
                    tmp = tmp.mm(weights)
                    # Normalisation
                    _, revers_i, counts = torch.unique(i, return_inverse=True, return_counts=True)
                    norm = 1 / counts[revers_i]
                    tmp = norm.unsqueeze(1) * tmp
                    # Tensor with all messages
                    msgs = torch.cat((msgs, tmp))
        index = index.unsqueeze(1).expand_as(msgs)
        # Aggregate
        agg = scatter.scatter_add(src=msgs, index=index, out=torch.zeros_like(x), dim=0)
        # Combine
        h = self.C(x) + agg
        return h


class HGNN(nn.Module):
    def __init__(self, base_dim, num_edge_types_by_shape, num_layers):
        super(HGNN, self).__init__()
        self.num_edge_types_by_shape = num_edge_types_by_shape
        self.num_layers = num_layers
        self.msg_layers = nn.ModuleList([])
        for i in range(self.num_layers):
            self.msg_layers.append(HGNNLayer(base_dim, base_dim, num_edge_types_by_shape))
        # self.lin_layer_1 = nn.Linear(base_dim, base_dim)
        self.lin_layer_2 = nn.Linear(base_dim, 1)

    def forward(self, x, hyperedge_index, hyperedge_type):
        # Message passing layers
        for i in range(self.num_layers):
            x = self.msg_layers[i](x, hyperedge_index, hyperedge_type)
            # x = torch.relu(x)
            x = nn.functional.leaky_relu(x)
        # Two layer mlp as binary classifier
        # x = self.lin_layer_1(x)
        # x = torch.leaky_relu(x)
        x = self.lin_layer_2(x)
        x = torch.sigmoid(x)
        return x
