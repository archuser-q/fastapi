"""Lõi thuật toán ghép cặp khách hàng – thợ (Thành viên B).

Tách riêng khỏi DB để:
  - dùng chung cho API thật (services/dispatch_service.py),
  - dùng cho công cụ mô phỏng của web quản trị (matching_controller.simulate),
  - dùng cho script thực nghiệm so sánh 2 chế độ (scripts/benchmark_matching.py).

Gồm:
  scoring.py   – hàm điểm phù hợp (Weighted Scoring) 4 tiêu chí, chuẩn hóa về [0, 1]
  hungarian.py – thuật toán Hungarian (Kuhn–Munkres) tự cài đặt cho bài toán gán 2 phía
  greedy.py    – ghép tham lam theo thứ tự đến (dùng cho thực nghiệm)
"""
