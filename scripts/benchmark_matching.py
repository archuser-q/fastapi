"""Thực nghiệm so sánh 2 chế độ ghép cặp (phục vụ Chương 5 của báo cáo).

Không cần DB: dùng đúng hàm điểm (app.matching.scoring) và thuật toán Hungarian / Greedy
(app.matching.hungarian, app.matching.greedy) mà hệ thống thật đang chạy.

Phần A — Bài toán gán tĩnh (1 thời điểm có n đơn chờ, m thợ rảnh):
    So sánh tổng điểm phù hợp & số đơn ghép được của Greedy (xử lý theo thứ tự đến) với
    Hungarian (tối ưu toàn cục), và thời gian chạy theo kích thước để minh hoạ độ phức tạp O(n^3).

Phần B — Mô phỏng vận hành theo thời gian (sự kiện rời rạc, bước 1 giây):
    Đơn đến theo phân phối Poisson, thợ có thể nhận/từ chối, có thời gian phản hồi, hết hạn offer,
    thợ bận trong thời gian di chuyển + sửa chữa. So sánh:
      - instant k=1, instant k=3 (gửi top-k mỗi đợt)
      - batch W = 5 / 10 / 20 / 30 giây (Hungarian mỗi W giây)
      - auto k=1, auto k=3 (hybrid: mỗi nhịp 2 giây chia đơn theo nhóm tranh chấp thợ,
        đơn đứng riêng -> top-k như tức thời, nhóm >= 2 đơn -> Hungarian; app.matching.grouping)
    Chỉ số: tỷ lệ ghép thành công, thời gian khách chờ (TB, trung vị, P90), điểm phù hợp TB,
    quãng đường thợ di chuyển TB, số offer/đơn, thời gian tính toán.

Chạy:
    python -m scripts.benchmark_matching                 # mặc định, ~1-2 phút
    python -m scripts.benchmark_matching --quick         # chạy nhanh để thử
    python -m scripts.benchmark_matching --out results   # lưu CSV + bảng Markdown (+ biểu đồ nếu có matplotlib)
"""

import argparse
import csv
import math
import random
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.matching.greedy import greedy_in_order
from app.matching.grouping import competition_groups
from app.matching.hungarian import hungarian_max, total_score
from app.matching.scoring import Weights, factor_scores, weighted_total

WEIGHTS = Weights(distance=0.4, trust=0.3, price=0.1, workload=0.2)
SEARCH_RADIUS_KM = 5.0
CITY_RADIUS_KM = 8.0


# =====================================================================
# Sinh dữ liệu
# =====================================================================


def rand_point(rng: random.Random, radius_km: float) -> tuple[float, float]:
    d = radius_km * math.sqrt(rng.random())
    b = rng.uniform(0, 2 * math.pi)
    return d * math.cos(b), d * math.sin(b)  # toạ độ phẳng (km) quanh tâm thành phố


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class SimWorker:
    id: int
    pos: tuple[float, float]
    trust: float
    price_ratio: float | None
    busy_until: float = 0.0
    offer_until: float = -1.0  # đang giữ offer tới thời điểm này
    jobs_done: int = 0


def make_workers(rng: random.Random, n: int) -> list[SimWorker]:
    out = []
    for i in range(n):
        out.append(
            SimWorker(
                id=i,
                pos=rand_point(rng, CITY_RADIUS_KM),
                trust=min(0.99, max(0.3, rng.betavariate(8, 2))),
                price_ratio=None if rng.random() < 0.3 else rng.uniform(0.9, 1.6),
            )
        )
    return out


def pair_score(order_pos, w: SimWorker, active_orders: int = 0) -> float | None:
    d = dist(order_pos, w.pos)
    if d > SEARCH_RADIUS_KM:
        return None
    s, _ = weighted_total(factor_scores(d, SEARCH_RADIUS_KM, w.trust, w.price_ratio, active_orders), WEIGHTS)
    return s


# =====================================================================
# Phần A: bài toán gán tĩnh
# =====================================================================


def part_a(sizes, reps, seed):
    rows = []
    for n in sizes:
        rng = random.Random(seed + n)
        gs, hs, gm, hm, gt, ht = [], [], [], [], [], []
        for _ in range(reps(n)):
            workers = make_workers(rng, n)
            orders = [rand_point(rng, CITY_RADIUS_KM) for _ in range(n)]
            matrix = [[pair_score(o, w) for w in workers] for o in orders]
            t0 = time.perf_counter()
            g = greedy_in_order(matrix)
            gt.append((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter()
            h = hungarian_max(matrix)
            ht.append((time.perf_counter() - t0) * 1000)
            gs.append(total_score(matrix, g))
            hs.append(total_score(matrix, h))
            gm.append(len(g))
            hm.append(len(h))
        g_avg, h_avg = statistics.mean(gs), statistics.mean(hs)
        rows.append(
            {
                "n_orders=n_workers": n,
                "lan_chay": reps(n),
                "greedy_tong_diem": round(g_avg, 3),
                "hungarian_tong_diem": round(h_avg, 3),
                "cai_thien_%": round((h_avg - g_avg) / g_avg * 100, 2) if g_avg else 0,
                "greedy_so_cap": round(statistics.mean(gm), 1),
                "hungarian_so_cap": round(statistics.mean(hm), 1),
                "greedy_ms": round(statistics.mean(gt), 3),
                "hungarian_ms": round(statistics.mean(ht), 2),
            }
        )
        print(f"  A n={n}: greedy={g_avg:.3f} hungarian={h_avg:.3f} ({rows[-1]['cai_thien_%']}%), "
              f"hungarian {rows[-1]['hungarian_ms']} ms")
    return rows


# =====================================================================
# Phần B: mô phỏng theo thời gian
# =====================================================================


@dataclass
class SimOrder:
    id: int
    pos: tuple[float, float]
    created: float
    offered: set = field(default_factory=set)
    live: dict = field(default_factory=dict)  # worker_id -> (respond_at, accept, score)
    wave_until: float = -1.0
    matched_at: float | None = None
    worker: int | None = None
    score: float | None = None
    pickup_km: float | None = None
    offers: int = 0
    cancelled: bool = False


@dataclass
class SimConfig:
    name: str
    mode: str  # instant | batch | auto
    k: int = 3
    window: int = 10


def simulate(cfg: SimConfig, n_workers, rate_per_min, minutes, accept_prob, seed, timeout=60, max_wait=900):
    rng = random.Random(seed)
    workers = make_workers(rng, n_workers)
    # Sinh trước dòng đơn (Poisson) để mọi cấu hình dùng CÙNG dữ liệu đầu vào
    arrivals, t = [], 0.0
    while True:
        t += rng.expovariate(rate_per_min / 60.0)
        if t > minutes * 60:
            break
        arrivals.append(SimOrder(id=len(arrivals), pos=rand_point(rng, CITY_RADIUS_KM), created=t))
    resp_rng = random.Random(seed * 7 + 1)
    # Quyết định của thợ cho từng cặp (đơn, thợ) cố định để các cấu hình so sánh công bằng
    decisions: dict[tuple[int, int], tuple[float, bool]] = {}

    def decision(o, w):
        key = (o.id, w.id)
        if key not in decisions:
            decisions[key] = (resp_rng.uniform(3, 25), resp_rng.random() < accept_prob)
        return decisions[key]

    pending: list[SimOrder] = []
    compute_ms = 0.0
    decisions_made = 0
    idx = 0
    horizon = minutes * 60 + max_wait + 60

    def free(w: SimWorker, now: float) -> bool:
        return w.busy_until <= now and w.offer_until < now

    def send(o: SimOrder, w: SimWorker, s: float, now: float):
        delay, accept = decision(o, w)
        o.live[w.id] = (now + min(delay, timeout), accept and delay <= timeout, s)
        o.offered.add(w.id)
        o.offers += 1
        w.offer_until = now + timeout

    for now in range(int(horizon)):
        while idx < len(arrivals) and arrivals[idx].created <= now:
            pending.append(arrivals[idx])
            idx += 1

        # 1. Phản hồi offer: ai nhận sớm nhất thì được đơn
        for o in pending:
            if not o.live:
                continue
            due = [(t_, wid, acc, s) for wid, (t_, acc, s) in o.live.items() if t_ <= now]
            winners = sorted((t_, wid, s) for t_, wid, acc, s in due if acc)
            if winners:
                _, wid, s = winners[0]
                w = workers[wid]
                o.matched_at, o.worker, o.score = now, wid, s
                o.pickup_km = dist(o.pos, w.pos)
                travel = o.pickup_km / 20 * 3600  # xe máy 20 km/h
                w.busy_until = now + travel + rng.uniform(30, 90) * 60
                w.pos = o.pos
                w.jobs_done += 1
                for other in o.live:
                    workers[other].offer_until = -1
                o.live.clear()
            else:
                for _, wid, _, _ in due:
                    workers[wid].offer_until = -1
                    del o.live[wid]

        still = []
        for o in pending:
            if o.matched_at is None and now - o.created > max_wait:
                o.cancelled = True
                for wid in o.live:
                    workers[wid].offer_until = -1
                o.live.clear()
            elif o.matched_at is None:
                still.append(o)
        pending = still

        # 2. Ra quyết định ghép
        if cfg.mode == "instant":
            for o in pending:
                if o.live:
                    continue
                t0 = time.perf_counter()
                cands = []
                for w in workers:
                    if w.id in o.offered or not free(w, now):
                        continue
                    s = pair_score(o.pos, w)
                    if s is not None:
                        cands.append((s, -dist(o.pos, w.pos), w))
                cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
                compute_ms += (time.perf_counter() - t0) * 1000
                decisions_made += 1
                for s, _, w in cands[: cfg.k]:
                    send(o, w, s, now)
        elif cfg.mode == "auto":
            if now % cfg.window == 0:
                pool = [o for o in pending if not o.live]
                if pool:
                    t0 = time.perf_counter()
                    cand = []
                    for o in pool:
                        row = {}
                        for w in workers:
                            if w.id in o.offered or not free(w, now):
                                continue
                            s = pair_score(o.pos, w)
                            if s is not None:
                                row[w.id] = s
                        cand.append(row)
                    plan = []
                    for g in competition_groups(cand):
                        if len(g) == 1:
                            row = cand[g[0]]
                            best = sorted(row, key=lambda wid: (row[wid], -dist(pool[g[0]].pos, workers[wid].pos)), reverse=True)
                            plan += [(pool[g[0]], workers[wid], row[wid]) for wid in best[: cfg.k]]
                        else:
                            wids = sorted({wid for i in g for wid in cand[i]})
                            matrix = [[cand[i].get(wid) for wid in wids] for i in g]
                            plan += [(pool[g[a]], workers[wids[b]], matrix[a][b]) for a, b in hungarian_max(matrix)]
                    compute_ms += (time.perf_counter() - t0) * 1000
                    decisions_made += 1
                    for o, w, sc in plan:
                        send(o, w, sc, now)
        elif now % cfg.window == 0:
            pool = [o for o in pending if not o.live]
            idle = [w for w in workers if free(w, now)]
            if pool and idle:
                t0 = time.perf_counter()
                matrix = [[(None if w.id in o.offered else pair_score(o.pos, w)) for w in idle] for o in pool]
                pairs = hungarian_max(matrix)
                compute_ms += (time.perf_counter() - t0) * 1000
                decisions_made += 1
                for i, j in pairs:
                    send(pool[i], idle[j], matrix[i][j], now)

    done = [o for o in arrivals if o.matched_at is not None]
    waits = sorted(o.matched_at - o.created for o in done)

    def pct(p):
        return waits[min(len(waits) - 1, int(p * len(waits)))] if waits else 0

    return {
        "cau_hinh": cfg.name,
        "so_don": len(arrivals),
        "ty_le_ghep_%": round(len(done) / len(arrivals) * 100, 1) if arrivals else 0,
        "cho_TB_giay": round(statistics.mean(waits), 1) if waits else 0,
        "cho_trung_vi_giay": round(pct(0.5), 1),
        "cho_P90_giay": round(pct(0.9), 1),
        "diem_TB": round(statistics.mean(o.score for o in done), 4) if done else 0,
        "tong_diem": round(sum(o.score for o in done), 2),
        "quang_duong_TB_km": round(statistics.mean(o.pickup_km for o in done), 2) if done else 0,
        "offer_moi_don": round(statistics.mean(o.offers for o in arrivals), 2) if arrivals else 0,
        "tinh_toan_ms_moi_lan": round(compute_ms / decisions_made, 3) if decisions_made else 0,
    }


def part_b(scenarios, minutes, accept_prob, seeds):
    configs = [
        SimConfig("instant k=1", "instant", k=1),
        SimConfig("instant k=3", "instant", k=3),
        SimConfig("batch W=5s", "batch", window=5),
        SimConfig("batch W=10s", "batch", window=10),
        SimConfig("batch W=20s", "batch", window=20),
        SimConfig("batch W=30s", "batch", window=30),
        SimConfig("auto k=1", "auto", k=1, window=2),
        SimConfig("auto k=3", "auto", k=3, window=2),
    ]
    rows = []
    for label, n_workers, rate in scenarios:
        for cfg in configs:
            runs = [simulate(cfg, n_workers, rate, minutes, accept_prob, s) for s in seeds]
            avg = {k: (round(statistics.mean(r[k] for r in runs), 3) if isinstance(runs[0][k], (int, float)) else runs[0][k]) for k in runs[0]}
            avg = {"kich_ban": label, "so_tho": n_workers, "don_moi_phut": rate, **avg}
            rows.append(avg)
            print(f"  B [{label}] {cfg.name:12s} ghép {avg['ty_le_ghep_%']}% | chờ TB {avg['cho_TB_giay']}s | "
                  f"điểm TB {avg['diem_TB']} | {avg['quang_duong_TB_km']} km")
    return rows


# =====================================================================
# Xuất kết quả
# =====================================================================


def to_markdown(rows) -> str:
    if not rows:
        return ""
    keys = list(rows[0].keys())
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    for r in rows:
        lines.append("| " + " | ".join(str(r[k]) for k in keys) + " |")
    return "\n".join(lines)


def save(rows, path: Path):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def charts(a_rows, b_rows, out: Path):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (không có matplotlib -> bỏ qua vẽ biểu đồ; cài: pip install matplotlib)")
        return
    ns = [r["n_orders=n_workers"] for r in a_rows]
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ax[0].plot(ns, [r["greedy_tong_diem"] for r in a_rows], "o-", label="Greedy")
    ax[0].plot(ns, [r["hungarian_tong_diem"] for r in a_rows], "s-", label="Hungarian")
    ax[0].set_xlabel("Số đơn = số thợ"), ax[0].set_ylabel("Tổng điểm phù hợp"), ax[0].legend()
    ax[0].set_title("Chất lượng ghép (bài toán tĩnh)")
    ax[1].plot(ns, [r["hungarian_ms"] for r in a_rows], "s-", color="C1")
    ax[1].set_xlabel("n"), ax[1].set_ylabel("ms"), ax[1].set_title("Thời gian Hungarian (O(n³))")
    fig.tight_layout()
    fig.savefig(out / "A_static.png", dpi=150)

    scen = sorted({r["kich_ban"] for r in b_rows})
    fig, ax = plt.subplots(1, 3, figsize=(15, 4))
    for s in scen:
        rs = [r for r in b_rows if r["kich_ban"] == s]
        names = [r["cau_hinh"] for r in rs]
        ax[0].plot(names, [r["cho_TB_giay"] for r in rs], "o-", label=s)
        ax[1].plot(names, [r["diem_TB"] for r in rs], "o-", label=s)
        ax[2].plot(names, [r["quang_duong_TB_km"] for r in rs], "o-", label=s)
    for a, t in zip(ax, ["Thời gian khách chờ TB (s)", "Điểm phù hợp TB", "Quãng đường thợ đi TB (km)"]):
        a.set_title(t)
        a.tick_params(axis="x", rotation=30)
        a.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "B_dynamic.png", dpi=150)
    print(f"  Đã lưu biểu đồ vào {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="chạy nhỏ để thử nhanh")
    ap.add_argument("--out", type=str, default=None, help="thư mục lưu CSV/Markdown/biểu đồ")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    if args.quick:
        sizes, reps = [10, 25, 50], (lambda n: 10)
        scenarios, minutes, seeds = [("vua", 40, 1.0)], 60, [1]
    else:
        sizes, reps = [10, 25, 50, 100, 150, 200], (lambda n: 30 if n <= 50 else 5)
        scenarios = [("thua_don", 60, 0.5), ("vua", 60, 1.5), ("cao_diem", 60, 3.0)]
        minutes, seeds = 120, [1, 2, 3]

    print("Phần A — Bài toán gán tĩnh: Greedy vs Hungarian")
    a_rows = part_a(sizes, reps, args.seed)
    print("\nPhần B — Mô phỏng vận hành (xác suất thợ nhận đơn 0.85, offer hết hạn 60s, chờ tối đa 15 phút)")
    b_rows = part_b(scenarios, minutes, 0.85, seeds)

    report = "## Phần A — Bài toán gán tĩnh\n\n" + to_markdown(a_rows) + "\n\n## Phần B — Mô phỏng vận hành\n\n" + to_markdown(b_rows) + "\n"
    print("\n" + report)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        save(a_rows, out / "A_static.csv")
        save(b_rows, out / "B_dynamic.csv")
        (out / "ket_qua.md").write_text(report, encoding="utf-8")
        charts(a_rows, b_rows, out)
        print(f"Đã lưu kết quả vào {out.resolve()}")


if __name__ == "__main__":
    main()
