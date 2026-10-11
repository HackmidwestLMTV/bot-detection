"""Small CPU research candidates; labels are 0=enrolled human, 1=simulated bot."""
import torch
from torch import nn


class SequenceModel(nn.Module):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        if kind == "cnn":
            self.conv1 = nn.Conv1d(8, 32, 5, padding=2)
            self.conv2 = nn.Conv1d(32, 64, 5, padding=2)
            self.conv3 = nn.Conv1d(64, 64, 3, padding=1)
            width = 64
        elif kind == "lstm":
            self.rnn = nn.LSTM(8, 32, batch_first=True)
            width = 32
        else:
            raise ValueError("unknown model")
        self.head1 = nn.Linear(width + 25, 16)
        self.head2 = nn.Linear(16, 1)

    def forward(self, sequence, features):
        mask = sequence[:, :, 7:8]
        if self.kind == "cnn":
            h = torch.relu(self.conv1(sequence.transpose(1, 2)))
            h = torch.relu(self.conv2(h))
            h = torch.relu(self.conv3(h)).transpose(1, 2)
        else:
            h, _ = self.rnn(sequence)
        h = (h * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
        return self.head2(torch.relu(self.head1(torch.cat([h, features], dim=1)))).squeeze(1)
