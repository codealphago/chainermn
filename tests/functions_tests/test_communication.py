import nose.plugins.skip
import unittest

import chainer
import chainer.testing
import chainer.testing.attr
import chainermn
import chainermn.functions
import numpy as np


@chainer.testing.parameterize(
    {'gpu': True},
    {'gpu': False},
)
class TestCommunication(unittest.TestCase):

    def setUp(self):
        if self.gpu:
            self.communicator = chainermn.create_communicator('hierarchical')
            device = self.communicator.intra_rank
            chainer.cuda.get_device(device).use()
        else:
            self.communicator = chainermn.create_communicator('naive')
            device = -1

        if self.communicator.size < 2:
            raise nose.plugins.skip.SkipTest()

        rank_next = (self.communicator.rank + 1) % self.communicator.size
        rank_prev = (self.communicator.rank - 1) % self.communicator.size

        # Send to the next-ranked node.
        self.send = chainermn.functions.Send(
            self.communicator, peer_rank=rank_next, peer_tag=0, device=device)

        # Receive from the previous-ranked node.
        self.recv = chainermn.functions.Recv(
            self.communicator, peer_rank=rank_prev, peer_tag=0, device=device)

        # Activation function.
        self.f = chainer.functions.sigmoid

        # Evaluation function.
        self.evaluation = chainer.functions.mean_squared_error

        # Input data.
        self.x = chainer.Variable(
            np.arange(10).reshape(1, 10).astype('float32') / 10)

        self.model = chainer.links.Linear(
            10, 10, initialW=self._init_w(self.communicator.rank))
        self.entire_model = [chainer.links.Linear(
            10, 10, initialW=self._init_w(l))
            for l in range(self.communicator.size)]

        if device >= 0:
            self.x.to_gpu()
            self.model.to_gpu()
            for model in self.entire_model:
                model.to_gpu()

    def _init_w(self, l):
        return 1.0 * np.arange(100).reshape(10, 10).astype('float32') \
            / ((l + 1) * 100)

    def test_communication(self):
        if self.communicator.rank == 0:
            # Input process.
            y = self.f(self.model(self.x))
            err = self.send(y)
            err.backward()
            grad = self.model.W.grad

            # Compute the expected gradient.
            x_ = self.x
            for l in range(self.communicator.size):
                x_ = self.f(self.entire_model[l](x_))
            err_ = self.evaluation(x_, self.x)
            err_.backward()
            grad_expected = self.entire_model[0].W.grad

            chainer.testing.assert_allclose(grad, grad_expected)

        elif self.communicator.rank == self.communicator.size - 1:
            # Output process.
            x = self.recv()
            y = self.f(self.model(x))
            err = self.evaluation(y, self.x)
            err.backward()

            # Compute the expected output.
            x_ = self.x
            for l in range(self.communicator.size):
                x_ = self.f(self.entire_model[l](x_))
            y_expect = x_

            chainer.testing.assert_allclose(y.data, y_expect.data)

        else:
            # Intermediate processes.
            x = self.recv()
            y = self.f(self.model(x))
            err = self.send(y)
            err.backward()
