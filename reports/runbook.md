# Runbook 1 trang — Region chính down (SOP On-Call)

Runbook phải chạy được lúc 3h sáng bởi người KHÔNG viết nó. Mỗi bước: lệnh copy-paste
được + cách biết bước đó xong.

| # | Bước | Lệnh | Biết là xong khi | Ai làm |
|---|---|---|---|---|
| 1 | Xác nhận outage | `python chaos/kill_region.py status` | `a.alive=false` hoặc `/readyz` fail 3 lần liên tiếp | on-call |
| 2 | Mở incident + bấm giờ RTO | `python dr/runbook.py --primary a --target b --backend fs` | Timestamp ghi vào `reports/runbook-run.jsonl` | on-call |
| 3 | Restore state ở region phụ | `python state/snapshot.py get --region b --backend fs` | `state/region-b/vectors.sqlite` và `weights/model.bin` tồn tại | DR automation / on-call |
| 4 | Scale pool warm→full | `printf full > state/region-b/pool_state` | `/readyz` của b trả 200 | DR automation / on-call |
| 5 | DNS/LB cutover | `printf b > edge/active_region` | `curl localhost:8080/edge/state` cho `active_region=b` | DR automation / on-call |
| 6 | Verify golden signals | `curl -s localhost:8080/v1/infer` (10 probes) | p95 < 200ms, error rate = 0% | on-call / SRE |
| 7 | Đo RTO + postmortem | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | `rto_verdict == "PASS"`, RTO ≤ 300s | Incident Commander |

**Rollback (failover ngược):** 
- **Điều kiện trả traffic về region A:** Region A đã được khôi phục hoàn toàn, endpoint `/healthz` và `/readyz` trả 200 ổn định liên tục trong tối thiểu 15 phút, dữ liệu vector mới nhất phát sinh tại Region B đã được replicate ngược về Region A.
- **Ai quyết định:** Incident Commander (hoặc Lead SRE trực ca) phê duyệt thủ công, tuyệt đối KHÔNG cấu hình tự động failover ngược để chống flapping.
