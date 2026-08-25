"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n: int, name: str, **kw):
    """Ghi 1 dòng {ts, iso, step, name, ...} vào LOG và print ra stdout."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "step": n,
        "name": name,
        **kw,
    }
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print("RUNBOOK", json.dumps(rec))
    return rec


def confirm(auto: bool, msg: str) -> bool:
    """auto=True -> True; ngược lại hỏi y/N. Đừng bỏ hàm này đi."""
    if auto:
        return True
    try:
        ans = input(f"{msg} [y/N]: ").strip().lower()
        return ans in ("y", "yes")
    except EOFError:
        return True


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    """7 bước chuẩn hóa phản ứng sự cố."""
    t_start = time.time()

    # 1. Xác nhận outage (probe cả 2 region)
    chaos_log = pathlib.Path("chaos/chaos-events.jsonl")
    t_outage = None
    if chaos_log.exists():
        kills = [json.loads(line) for line in chaos_log.read_text().splitlines() if line.strip() and json.loads(line).get("action") == "kill"]
        if kills:
            t_outage = kills[-1]["ts"]

    p_alive = False
    try:
        r = httpx.get(f"{URL[primary]}/healthz", timeout=1.0)
        p_alive = (r.status_code == 200)
    except Exception:
        p_alive = False

    t_alive = False
    try:
        r = httpx.get(f"{URL[target]}/healthz", timeout=1.0)
        t_alive = (r.status_code == 200)
    except Exception:
        t_alive = False

    step(1, "xac_nhan_outage", primary=primary, target=target, primary_alive=p_alive, target_alive=t_alive)

    # 2. Thông báo incident
    delay_s = round(time.time() - t_outage, 2) if t_outage else None
    step(2, "thong_bao_incident", primary=primary, t_outage=t_outage, alert_delay_s=delay_s)

    # Hỏi confirm nếu không phải mode auto
    if not confirm(auto, f"Xác nhận failover từ {primary} sang {target}?"):
        print("Hủy bỏ failover theo yêu cầu của operator.")
        return {"ok": False, "aborted": True}

    # 3. Scale GPU pool (Gọi failover.failover DUY NHẤT 1 LẦN)
    fo_res = fo.failover(target=target, backend=backend)
    step(3, "scale_gpu_pool", target=target, failover_ok=fo_res.get("ok"))

    if not fo_res.get("ok"):
        print("Failover thất bại.")
        return {"ok": False, "failover_result": fo_res}

    # 4. Verify state replica (Đọc từ kết quả bước 3)
    target_state = fo_res.get("target_state", {})
    step(4, "verify_state_replica", target=target, vector_count=target_state.get("count"),
         weights=target_state.get("weights"), rpo_seconds=fo_res.get("rpo_seconds"),
         docs_lost=fo_res.get("docs_lost"))

    # 5. DNS cutover (Đọc lại trạng thái từ bước 3)
    step(5, "dns_cutover", active_region=target, ok=fo_res.get("ok"))

    # 6. Verify golden signals (10 request thật vào proxy)
    latencies = []
    errors = 0
    with httpx.Client(timeout=2.0) as c:
        for i in range(10):
            t0 = time.time()
            try:
                r = c.get("http://127.0.0.1:8080/v1/infer", params={"q": f"probe {i}"})
                if r.status_code == 200:
                    latencies.append((time.time() - t0) * 1000)
                else:
                    errors += 1
            except Exception:
                errors += 1
            time.sleep(0.05)

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    err_rate = errors / 10.0
    step(6, "verify_golden_signals", requests=10, error_rate=err_rate, p95_latency_ms=round(p95, 1))

    # 7. Post incident
    elapsed_total = round(time.time() - t_start, 2)
    step(7, "post_incident", elapsed_s=elapsed_total,
         measure_cmd="python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300")

    return {
        "ok": True,
        "elapsed_s": elapsed_total,
        "failover": fo_res,
        "golden_signals": {"p95_latency_ms": round(p95, 1), "error_rate": err_rate},
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
