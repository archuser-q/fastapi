"""Thuật toán Hungarian (Kuhn–Munkres) — tự cài đặt, không dùng thư viện ngoài.

Bài toán gán 2 phía có trọng số (weighted bipartite assignment):
    - n đơn đang chờ (hàng), m thợ đang rảnh (cột)
    - score[i][j] thuộc [0, 1] = điểm phù hợp đơn i – thợ j (cùng hàm điểm với chế độ tức thời),
      None = cặp không hợp lệ (thợ ngoài bán kính, không có kỹ năng, ...)
    - Tìm tập cặp (i, j), mỗi đơn tối đa 1 thợ, mỗi thợ tối đa 1 đơn, sao cho:
        (1) số cặp hợp lệ là LỚN NHẤT (ghép được càng nhiều đơn càng tốt), rồi
        (2) tổng điểm phù hợp là LỚN NHẤT trong các cách ghép đó.

Cách quy về bài toán cực tiểu chi phí chuẩn:
    cost[i][j] = 1 - score[i][j]   nếu hợp lệ   (thuộc [0, 1])
    cost[i][j] = BIG = k + 1       nếu không hợp lệ, k = min(n, m)
  Vì tổng chi phí mọi cặp hợp lệ <= k < BIG, lời giải tối ưu luôn dùng ít cặp "BIG" nhất có thể
  (tức nhiều cặp hợp lệ nhất), và với cùng số cặp hợp lệ thì min sum(1 - s) <=> max sum(s).
  Cặp "BIG" trong lời giải bị loại bỏ (đơn đó chờ lượt sau).

Cài đặt: phiên bản dùng thế vị (potentials) u, v và đường tăng ngắn nhất kiểu Dijkstra,
độ phức tạp O(n^2 * m) với n <= m (ma trận được chuyển vị nếu n > m) — tức O(n^3) khi n ≈ m.
"""

from collections.abc import Sequence

INF = float("inf")


def _min_cost_assignment(cost: Sequence[Sequence[float]]) -> list[int]:
    """Gán tối ưu cho ma trận n x m (n <= m), cực tiểu tổng chi phí.

    Trả về assign[i] = cột được gán cho hàng i (mọi hàng đều được gán vì n <= m).
    Dùng chỉ số 1..n, 1..m bên trong; cột 0 là cột giả làm gốc của đường tăng.
    """
    n = len(cost)
    m = len(cost[0]) if n else 0
    if n == 0:
        return []
    if n > m:
        raise ValueError("Cần n <= m")

    u = [0.0] * (n + 1)  # thế vị hàng
    v = [0.0] * (m + 1)  # thế vị cột
    p = [0] * (m + 1)  # p[j] = hàng đang được gán vào cột j (0 = trống)
    way = [0] * (m + 1)  # cột đứng trước j trên đường tăng

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            row = cost[i0 - 1]
            delta = INF
            j1 = 0
            ui0 = u[i0]
            for j in range(1, m + 1):
                if not used[j]:
                    cur = row[j - 1] - ui0 - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        # Lật đường tăng
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assign = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            assign[p[j] - 1] = j - 1
    return assign


def hungarian_max(score: Sequence[Sequence[float | None]]) -> list[tuple[int, int]]:
    """Ghép tối ưu toàn cục cho ma trận điểm n x m (n, m bất kỳ).

    Trả về danh sách cặp (i, j) hợp lệ (score không None), sắp theo i.
    """
    n = len(score)
    m = len(score[0]) if n else 0
    if n == 0 or m == 0:
        return []

    big = float(min(n, m) + 1)
    cost = [[(1.0 - s) if s is not None else big for s in row] for row in score]

    transposed = n > m
    if transposed:
        cost = [list(col) for col in zip(*cost)]

    assign = _min_cost_assignment(cost)
    pairs = []
    for r, c in enumerate(assign):
        if c < 0:
            continue
        i, j = (c, r) if transposed else (r, c)
        if score[i][j] is not None:
            pairs.append((i, j))
    pairs.sort()
    return pairs


def total_score(score: Sequence[Sequence[float | None]], pairs: list[tuple[int, int]]) -> float:
    return sum(score[i][j] for i, j in pairs)  # type: ignore[misc]
