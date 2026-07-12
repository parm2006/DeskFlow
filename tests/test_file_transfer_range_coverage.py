import unittest

from app.file_transfer.range_coverage import RangeCoverage


class RangeCoverageTests(unittest.TestCase):
    def test_merges_overlapping_adjacent_and_reread_ranges(self):
        coverage = RangeCoverage(100)

        self.assertEqual(coverage.add(10, 20), 20)
        self.assertEqual(coverage.add(20, 20), 30)
        self.assertEqual(coverage.add(0, 10), 40)
        self.assertEqual(coverage.add(5, 10), 40)
        self.assertEqual(coverage.intervals, ((0, 40),))

    def test_accepts_out_of_order_ranges_and_reports_completion(self):
        coverage = RangeCoverage(10)
        coverage.add(5, 5)
        coverage.add(0, 5)

        self.assertEqual(coverage.covered, 10)
        self.assertTrue(coverage.complete)

    def test_rejects_invalid_or_beyond_size_ranges(self):
        coverage = RangeCoverage(10)
        for offset, count in ((-1, 1), (0, -1), (9, 2), (11, 0)):
            with self.subTest(offset=offset, count=count):
                with self.assertRaises(ValueError):
                    coverage.add(offset, count)


if __name__ == "__main__":
    unittest.main()
