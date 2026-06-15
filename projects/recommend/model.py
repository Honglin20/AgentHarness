"""Neural Collaborative Filtering model."""
import torch
import torch.nn as nn

from data import N_USERS, N_ITEMS, EMBED_DIM


class NCF(nn.Module):
    """User/item embeddings + MLP for binary interaction prediction."""

    def __init__(self, n_users=N_USERS, n_items=N_ITEMS, embed_dim=EMBED_DIM,
                 hidden_dim=64, n_layers=2):
        super().__init__()
        self.user_embedding = nn.Embedding(n_users, embed_dim)
        self.item_embedding = nn.Embedding(n_items, embed_dim)

        layers = []
        in_dim = embed_dim * 2
        for _ in range(n_layers):
            layers.append(nn.Linear(in_dim, hidden_dim))
            layers.append(nn.ReLU())
            in_dim = hidden_dim
        layers.append(nn.Linear(in_dim, 1))
        self.mlp = nn.Sequential(*layers)

    def forward(self, user_item_tuple):
        user_ids, item_ids = user_item_tuple
        u = self.user_embedding(user_ids)
        i = self.item_embedding(item_ids)
        x = torch.cat([u, i], dim=-1)
        logit = self.mlp(x).squeeze(-1)
        return torch.sigmoid(logit)

    def dummy_inputs(self):
        return (torch.zeros(1, dtype=torch.long), torch.zeros(1, dtype=torch.long))
