import torch
import torch.nn as nn
import torch.nn.functional as F

class DQN(nn.Module):
    def __init__(self, input_shape=19, num_actions=4):
        """
        Deep Q-Network (DQN) for Submarine Navigation.
        
        Args:
            input_shape (int): Size of the state vector (16 Sonar + 1 Battery + 2 Velocity = 19).
            num_actions (int): Number of discrete actions (4: Up, Down, Left, Right).
        """
        super(DQN, self).__init__()
        
        # Neural network layers
        # We use a deeper network (3 hidden layers) to capture the physics dynamics
        self.fc1 = nn.Linear(input_shape, 256)
        self.fc2 = nn.Linear(256, 128)
        self.fc3 = nn.Linear(128, 64)
        self.out = nn.Linear(64, num_actions)
        
    def forward(self, x):
        """
        Forward pass through the network.
        Input: State Tensor
        Output: Q-Values for each action
        """
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = F.relu(self.fc3(x))
        return self.out(x)

