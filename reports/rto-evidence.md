# RTO/RPO Evidence — Lab 23

Quy tắc duy nhất: mỗi con số ở đây phải trỏ được về **một dòng log thật**
(`đường/dẫn.jsonl:số_dòng`). `pytest tests/test_rto_evidence.py` sẽ mở từng file ra kiểm tra.
Con số không có evidence = trượt, bất kể các phần khác.

## 1. Drill 1 — không có DR (baseline)

| Chỉ số | Giá trị | Cách đo | Evidence |
|---|---|---|---|
| t_outage | `2026-08-25T08:33:52` | chaos kill | `chaos/chaos-events.jsonl:1` |
| Request fail đầu tiên | `+0.2s` | dòng `ok:false` đầu tiên sau t_outage | `reports/drill-1-nodr.jsonl:17` |
| Request thành công sau đó | không có | không có dòng `ok:true` nào sau t_outage | `reports/drill-1-nodr.jsonl` |
| RTO | `NO_RECOVERY` | `tools/measure_rto.py` | `reports/drill-1-nodr.jsonl` |

## 2. Drill 2 — có DR

| Mốc | +giây từ t_outage | Cách đo | Evidence |
|---|---|---|---|
| t_outage (mốc 0) | 0 | `action:kill` | `chaos/chaos-events.jsonl:1` |
| User thấy lỗi đầu tiên | +0.1s | dòng `ok:false` đầu | `reports/drill-2-withdr.jsonl:25` |
| Health check phát hiện | +14.7s | `to:UNHEALTHY, region:a` | `reports/health-events.jsonl:2` |
| Snapshot restore xong | +16.9s | `step:2_restore_snapshot` | `reports/failover-events.jsonl:2` |
| Region phụ ready | +23.1s | `step:4_wait_ready` | `reports/failover-events.jsonl:4` |
| DNS cutover | +23.1s | `step:5_dns_cutover` | `reports/failover-events.jsonl:5` |
| **RTO đo được** | +28.9s | dòng `ok:true` đầu sau lỗi | `reports/drill-2-withdr.jsonl:39` |

| Chỉ số | Đo được | Mục tiêu (slide §1) | Verdict |
|---|---|---|---|
| RTO — Inference API | `28.9s` | 300s (5 phút) | PASS |
| RPO — Vector DB | `4.0s` / `2` doc | 300s (5 phút) | PASS |

## 3. RTO của tôi gồm những gì (bắt buộc — đây là phần chấm điểm hiểu bài)

| Thành phần | Giây | Nó đến từ đâu | Giảm được bằng cách nào |
|---|---|---|---|
| Health-check detect floor | 14.7s | `interval_s × threshold` (5s × 3) trong `reports/health-events.jsonl:2` | Giảm `interval_s` (xuống 2s) hoặc threshold xuống 2 (nhưng tăng rủi ro flapping) |
| Snapshot restore | 2.2s | `2_restore_snapshot` (16.9s) đến `3_scale_pool` trong `reports/failover-events.jsonl:2` | Tối ưu I/O disk, dùng storage tốc độ cao hoặc streaming snapshot |
| GPU pool warm-up | 6.2s | `waited_s` ở `4_wait_ready` trong `reports/failover-events.jsonl:4` | Giữ GPU standby ở chế độ warm/hot hoặc pre-warm weights vào GPU VRAM |
| DNS/LB TTL cache | 5.8s | t_recovered (28.9s) − t_cutover (23.1s) trong `reports/drill-2-withdr.jsonl:39` | Hạ `EDGE_TTL_SECONDS` (từ 5s xuống 1s-2s) hoặc dùng Anycast routing |
