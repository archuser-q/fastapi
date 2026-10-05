"""Đo hiệu năng tìm thợ theo vị trí: có và không có chỉ mục không gian GiST.

Chạy:  python -m scripts.benchmark_geo
Tùy chọn:
  --sizes 1000,10000,100000   các cỡ dữ liệu (số thợ)
  --queries 50                số lần tìm mỗi cỡ dữ liệu
  --radius 5                  bán kính tìm (km)
  --limit 50                  số thợ gần nhất cần lấy ở kịch bản 3
  --csv ket_qua.csv           ghi thêm kết quả ra file CSV để vẽ biểu đồ

Script dùng bảng TẠM (TEMP TABLE), tự xóa khi kết thúc, không đụng vào dữ liệu thật.

Ba kịch bản:
  1. Vùng cố định: rải thợ trong bán kính 30 km. Thợ càng nhiều thì càng dày,
     số kết quả tăng theo số thợ (giữ nguyên như phiên bản trước để so sánh).
  2. Mật độ không đổi: vùng rải mở rộng theo số thợ, mỗi lần tìm luôn trả về
     khoảng 30 thợ. Kịch bản này cho thấy đặc tính O(log n) của chỉ mục.
  3. Lấy N thợ gần nhất: giống câu truy vấn trong find_nearby_workers
     (lọc trong bán kính, sắp xếp từ gần đến xa, LIMIT), trên dữ liệu của kịch bản 1.

Ba cách được so sánh trong mỗi kịch bản:
  A. Công thức Haversine trên hai cột lat/lng, không chỉ mục
  B. PostGIS nhưng tắt chỉ mục, buộc quét toàn bảng
  C. PostGIS dùng chỉ mục GiST
"""

import argparse
import csv
import math
import random
import statistics
import time

from sqlalchemy import text

from app.database import engine

CENTER = (21.0285, 105.8542)  # Hồ Gươm
FIXED_AREA_KM = 30
# Mật độ để mỗi lần tìm 5 km có khoảng 30 thợ online (1/3 số thợ online):
# 30 * 3 thợ trong diện tích pi * 5^2 km2
DENSITY_PER_KM2 = 90 / (math.pi * 5**2)

HAVERSINE_EXPR = """
    2 * 6371 * asin(sqrt(
        power(sin(radians(lat - :lat) / 2), 2)
      + cos(radians(:lat)) * cos(radians(lat)) * power(sin(radians(lng - :lng) / 2), 2)
    ))
"""
POINT_EXPR = "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography"

RANGE_SQL = {
    "A": text(f"SELECT id FROM bench_workers WHERE availability = 'online' AND {HAVERSINE_EXPR} <= :radius_km"),
    "BC": text(
        f"SELECT id FROM bench_workers WHERE availability = 'online' "
        f"AND ST_DWithin(location, {POINT_EXPR}, :radius_m)"
    ),
}

KNN_SQL = {
    "A": text(
        f"SELECT id FROM bench_workers WHERE availability = 'online' AND {HAVERSINE_EXPR} <= :radius_km "
        f"ORDER BY {HAVERSINE_EXPR} LIMIT :limit"
    ),
    "BC": text(
        f"SELECT id FROM bench_workers WHERE availability = 'online' "
        f"AND ST_DWithin(location, {POINT_EXPR}, :radius_m) "
        f"ORDER BY location <-> {POINT_EXPR} LIMIT :limit"
    ),
}


# ---------- Sinh dữ liệu ----------


def random_point(max_km: float) -> tuple[float, float]:
    """Điểm ngẫu nhiên rải đều trong hình tròn bán kính max_km quanh Hồ Gươm."""
    lat, lng = CENTER
    distance = max_km * math.sqrt(random.random())
    bearing = random.uniform(0, 2 * math.pi)
    return (
        lat + distance / 111.32 * math.cos(bearing),
        lng + distance / (111.32 * math.cos(math.radians(lat))) * math.sin(bearing),
    )


def area_for_constant_density(size: int) -> float:
    return math.sqrt(size / DENSITY_PER_KM2 / math.pi)


def load_data(conn, size: int, area_km: float) -> None:
    conn.execute(text("DROP TABLE IF EXISTS bench_workers"))
    conn.execute(
        text(
            """
            CREATE TEMP TABLE bench_workers (
                id INT PRIMARY KEY,
                lat DOUBLE PRECISION,
                lng DOUBLE PRECISION,
                location geography(Point, 4326),
                availability VARCHAR(20)
            )
            """
        )
    )
    rows = []
    for i in range(size):
        lat, lng = random_point(area_km)
        rows.append({"id": i, "lat": lat, "lng": lng, "a": random.choice(["online", "busy", "offline"])})
    conn.execute(
        text(
            f"""
            INSERT INTO bench_workers (id, lat, lng, location, availability)
            VALUES (:id, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :a)
            """
        ),
        rows,
    )
    conn.execute(text("CREATE INDEX ON bench_workers USING GIST (location)"))
    conn.execute(text("ANALYZE bench_workers"))


def make_params(area_km: float, queries: int, radius: float, limit: int) -> list[dict]:
    # Điểm tìm nằm trong 60% vùng rải để vòng tròn tìm kiếm không bị cắt ở mép
    return [
        {"lat": lat, "lng": lng, "radius_km": radius, "radius_m": radius * 1000, "limit": limit}
        for lat, lng in (random_point(area_km * 0.6) for _ in range(queries))
    ]


# ---------- Đo ----------


def set_index(conn, enabled: bool) -> None:
    value = "on" if enabled else "off"
    conn.execute(text(f"SET enable_indexscan = {value}"))
    conn.execute(text(f"SET enable_bitmapscan = {value}"))


def timed(conn, sql, params_list, use_index: bool = True):
    set_index(conn, use_index)
    durations, results = [], []
    for params in params_list:
        start = time.perf_counter()
        ids = conn.execute(sql, params).scalars().all()
        durations.append((time.perf_counter() - start) * 1000)
        results.append(ids)
    set_index(conn, True)
    return statistics.median(durations), results


def run_methods(conn, sqls: dict, params: list[dict], ordered: bool):
    a_ms, a_res = timed(conn, sqls["A"], params)
    b_ms, b_res = timed(conn, sqls["BC"], params, use_index=False)
    c_ms, c_res = timed(conn, sqls["BC"], params, use_index=True)

    # Tính đúng: bật hay tắt chỉ mục không được làm thay đổi kết quả
    normalize = (lambda r: r) if ordered else sorted
    assert [normalize(r) for r in b_res] == [normalize(r) for r in c_res], (
        "Kết quả có chỉ mục khác không chỉ mục"
    )
    # Haversine (hình cầu) và PostGIS (ellipsoid) có thể lệch vài điểm sát mép bán kính
    mismatch = sum(len(set(a) ^ set(c)) for a, c in zip(a_res, c_res))
    found = statistics.mean(len(r) for r in c_res)
    return a_ms, b_ms, c_ms, found, mismatch


def explain(conn, sql, params) -> str:
    plan = conn.execute(text("EXPLAIN " + sql.text), params).scalars().all()
    return "\n".join("      " + line for line in plan)


# ---------- In kết quả ----------

HEADER = (
    f"{'Số thợ':>10} | {'Vùng rải':>9} | {'A. Haversine':>13} | {'B. Không chỉ mục':>16} | "
    f"{'C. GiST':>9} | {'C nhanh hơn B':>13} | {'C nhanh hơn A':>13} | {'Kết quả TB':>10}"
)


def print_title(number: int, title: str, note: str) -> None:
    print(f"\n{'=' * len(HEADER)}\nKịch bản {number}. {title}\n{note}\n{'=' * len(HEADER)}")
    print(HEADER)
    print("-" * len(HEADER))


def print_row(size, area_km, a_ms, b_ms, c_ms, found, mismatch) -> None:
    print(
        f"{size:>10,} | {area_km:>6.0f} km | {a_ms:>10.2f} ms | {b_ms:>13.2f} ms | {c_ms:>6.2f} ms | "
        f"{b_ms / c_ms:>12.1f}x | {a_ms / c_ms:>12.1f}x | {found:>10.1f}"
        + (f"  (Haversine lệch {mismatch} điểm sát mép)" if mismatch else "")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="1000,10000,100000")
    parser.add_argument("--queries", type=int, default=50)
    parser.add_argument("--radius", type=float, default=5)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--csv", default=None)
    args = parser.parse_args()

    random.seed(42)
    sizes = [int(s) for s in args.sizes.split(",")]
    records = []

    print(
        f"Bán kính tìm {args.radius} km, {args.queries} lần tìm mỗi cỡ dữ liệu. "
        "Thời gian là trung vị (median) của một lần tìm."
    )

    # Sinh điểm tìm kiếm trước khi nạp dữ liệu, cùng thứ tự với phiên bản trước,
    # để kịch bản 1 cho ra đúng dữ liệu và điểm tìm như các lần đo cũ
    params = make_params(FIXED_AREA_KM, args.queries, args.radius, args.limit)

    with engine.connect() as conn:
        # Kịch bản 1 và 3 dùng chung dữ liệu vùng cố định
        fixed = {}
        for size in sizes:
            load_data(conn, size, FIXED_AREA_KM)
            fixed[size] = {
                "range": run_methods(conn, RANGE_SQL, params, ordered=False),
                "knn": run_methods(conn, KNN_SQL, params, ordered=True),
            }
            if size == sizes[-1]:
                knn_plan = explain(conn, KNN_SQL["BC"], params[0])

        print_title(1, "Vùng cố định 30 km (thợ càng nhiều càng dày)", "Tìm TẤT CẢ thợ online trong bán kính.")
        for size in sizes:
            print_row(size, FIXED_AREA_KM, *fixed[size]["range"])
            records.append(("1_vung_co_dinh", size, FIXED_AREA_KM, *fixed[size]["range"]))

        # Kịch bản 2: mật độ không đổi
        print_title(
            2,
            "Mật độ không đổi (vùng rải mở rộng theo số thợ)",
            "Mỗi lần tìm trả về khoảng 30 thợ dù tổng số thợ tăng. Thời gian của C gần như "
            "không đổi là dấu hiệu của O(log n).",
        )
        for size in sizes:
            area_km = area_for_constant_density(size)
            load_data(conn, size, area_km)
            density_params = make_params(area_km, args.queries, args.radius, args.limit)
            row = run_methods(conn, RANGE_SQL, density_params, ordered=False)
            print_row(size, area_km, *row)
            records.append(("2_mat_do_khong_doi", size, round(area_km, 1), *row))
            if size == sizes[-1]:
                density_plan = explain(conn, RANGE_SQL["BC"], density_params[0])

        print_title(
            3,
            f"Lấy {args.limit} thợ gần nhất (giống find_nearby_workers)",
            "Dữ liệu vùng cố định như kịch bản 1, sắp xếp từ gần đến xa rồi LIMIT.",
        )
        for size in sizes:
            print_row(size, FIXED_AREA_KM, *fixed[size]["knn"])
            records.append(("3_gan_nhat_limit", size, FIXED_AREA_KM, *fixed[size]["knn"]))

        conn.execute(text("DROP TABLE IF EXISTS bench_workers"))

    print(f"\nKế hoạch thực thi cách C, kịch bản 2, {sizes[-1]:,} thợ:")
    print(density_plan)
    print(f"\nKế hoạch thực thi cách C, kịch bản 3, {sizes[-1]:,} thợ:")
    print(knn_plan)

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["kich_ban", "so_tho", "vung_rai_km", "A_haversine_ms", "B_khong_chi_muc_ms",
                 "C_gist_ms", "ket_qua_tb", "haversine_lech"]
            )
            for r in records:
                writer.writerow([r[0], r[1], r[2], round(r[3], 3), round(r[4], 3), round(r[5], 3), round(r[6], 1), r[7]])
        print(f"\nĐã ghi kết quả ra {args.csv}")


if __name__ == "__main__":
    main()
