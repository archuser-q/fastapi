"""Chia đơn đang chờ thành các NHÓM TRANH CHẤP thợ — nền tảng của chế độ ghép "auto" (hybrid).

Hai đơn thuộc cùng nhóm nếu có chung ít nhất 1 thợ ứng viên, nối bắc cầu
(A chung thợ với B, B chung thợ với C -> A, B, C cùng nhóm). Cài đặt bằng Union-Find (DSU)
có nén đường đi, độ phức tạp ~O(tổng số cặp đơn-ứng viên).

Ý nghĩa:
  - Nhóm 1 đơn: không đơn nào khác cần thợ của nó -> ghép tham lam (top-k) đã là tối ưu cho đơn đó,
    gửi ngay để khách không phải chờ cửa sổ lô.
  - Nhóm >= 2 đơn: các đơn giành nhau thợ -> giải Hungarian trên nhóm để tối đa tổng điểm toàn cục.
Các nhóm độc lập nhau nên giải riêng từng nhóm cho cùng kết quả với giải chung, mà ma trận nhỏ hơn.
"""

from collections.abc import Iterable, Sequence


def competition_groups(candidates: Sequence[Iterable[int]]) -> list[list[int]]:
    """candidates[i] = tập id thợ ứng viên của đơn i. Trả về các nhóm (chỉ số đơn tăng dần)."""
    parent = list(range(len(candidates)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[int, int] = {}
    for i, cand in enumerate(candidates):
        for wid in cand:
            if wid in owner:
                ra, rb = find(i), find(owner[wid])
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
            else:
                owner[wid] = i
    groups: dict[int, list[int]] = {}
    for i in range(len(candidates)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())
