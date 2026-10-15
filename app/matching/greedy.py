"""Ghép tham lam (Greedy) — dùng làm mốc so sánh với Hungarian.

Chế độ tức thời của hệ thống xử lý từng đơn theo thứ tự đến: mỗi đơn lấy thợ có điểm cao nhất
trong số thợ còn rảnh tại thời điểm đó. Hàm dưới đây mô phỏng đúng cách làm đó trên một ma trận
điểm (đơn theo thứ tự đến = thứ tự hàng), để so sánh trực tiếp với lời giải tối ưu toàn cục.
"""

from collections.abc import Sequence


def greedy_in_order(score: Sequence[Sequence[float | None]]) -> list[tuple[int, int]]:
    taken: set[int] = set()
    pairs = []
    for i, row in enumerate(score):
        best_j, best = -1, -1.0
        for j, s in enumerate(row):
            if s is not None and j not in taken and s > best:
                best_j, best = j, s
        if best_j >= 0:
            taken.add(best_j)
            pairs.append((i, best_j))
    return pairs
