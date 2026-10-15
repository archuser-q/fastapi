"""Kiểm chứng thuật toán Hungarian tự cài đặt bằng vét cạn trên ma trận nhỏ (chạy không cần DB)."""

import itertools
import random

import pytest

from app.matching.greedy import greedy_in_order
from app.matching.hungarian import hungarian_max, total_score


def brute_force(score):
    """Thử mọi cách gán; tiêu chí: (số cặp hợp lệ lớn nhất, rồi tổng điểm lớn nhất)."""
    n, m = len(score), len(score[0])
    best = (-1, -1.0)
    if n <= m:
        for perm in itertools.permutations(range(m), n):
            pairs = [(i, perm[i]) for i in range(n) if score[i][perm[i]] is not None]
            key = (len(pairs), round(total_score(score, pairs), 9))
            best = max(best, key)
    else:
        for perm in itertools.permutations(range(n), m):
            pairs = [(perm[j], j) for j in range(m) if score[perm[j]][j] is not None]
            key = (len(pairs), round(total_score(score, pairs), 9))
            best = max(best, key)
    return best


def random_matrix(rng, n, m, p_invalid):
    return [[None if rng.random() < p_invalid else round(rng.random(), 4) for _ in range(m)] for _ in range(n)]


@pytest.mark.parametrize("seed", range(300))
def test_hungarian_matches_brute_force(seed):
    rng = random.Random(seed)
    n, m = rng.randint(1, 6), rng.randint(1, 6)
    score = random_matrix(rng, n, m, p_invalid=rng.choice([0, 0.2, 0.5, 0.8]))
    pairs = hungarian_max(score)

    # Lời giải hợp lệ: mỗi hàng/cột tối đa 1 lần, không dùng cặp None
    assert len({i for i, _ in pairs}) == len(pairs) == len({j for _, j in pairs})
    assert all(score[i][j] is not None for i, j in pairs)

    got = (len(pairs), round(total_score(score, pairs), 9))
    assert got == brute_force(score)


def test_classic_example_beats_greedy():
    # Đơn A đến trước "chiếm" thợ 0 (điểm 0.9) khiến đơn B chỉ còn thợ 1 (0.1).
    # Tối ưu toàn cục: A-1 (0.8) + B-0 (0.85) = 1.65 > greedy 0.9 + 0.1 = 1.0
    score = [[0.9, 0.8], [0.85, 0.1]]
    assert total_score(score, greedy_in_order(score)) == pytest.approx(1.0)
    assert hungarian_max(score) == [(0, 1), (1, 0)]
    assert total_score(score, hungarian_max(score)) == pytest.approx(1.65)


def test_prefers_more_matches_over_higher_score():
    # Ghép (0,0)=1.0 thì đơn 1 không còn ai; ghép (0,1)+(1,0) được 2 đơn dù tổng điểm thấp hơn
    score = [[1.0, 0.1], [0.1, None]]
    assert hungarian_max(score) == [(0, 1), (1, 0)]


def test_empty_and_all_invalid():
    assert hungarian_max([]) == []
    assert hungarian_max([[None, None], [None, None]]) == []


def test_larger_random_is_never_worse_than_greedy():
    rng = random.Random(7)
    for _ in range(30):
        score = random_matrix(rng, rng.randint(5, 40), rng.randint(5, 40), 0.3)
        h, g = hungarian_max(score), greedy_in_order(score)
        assert (len(h), total_score(score, h)) >= (len(g), total_score(score, g) - 1e-9)
