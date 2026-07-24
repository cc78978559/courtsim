import unittest

from courtsim.randomness import RandomStreams, derive_seed


class RandomnessTests(unittest.TestCase):
    def test_seed_derivation_is_stable(self) -> None:
        self.assertEqual(
            derive_seed(42, "game", 7),
            121599856421007539500030026232637546759,
        )

    def test_named_streams_are_isolated(self) -> None:
        streams = RandomStreams(99)
        first_stream = streams.stream("possession", 1)
        second_stream = streams.stream("possession", 2)
        first = [first_stream.random() for _ in range(3)]
        second = [second_stream.random() for _ in range(3)]
        self.assertNotEqual(first, second)

    def test_recreating_stream_replays_values(self) -> None:
        streams = RandomStreams(99)
        left = streams.stream("shot", 5)
        right = streams.stream("shot", 5)
        self.assertEqual([left.random() for _ in range(5)], [right.random() for _ in range(5)])


if __name__ == "__main__":
    unittest.main()
