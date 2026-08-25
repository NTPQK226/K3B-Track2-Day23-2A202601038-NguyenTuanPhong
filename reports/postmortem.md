# Postmortem — DR Drill Lab 23

Theo đúng template §4 "Sau Failover: Blameless Postmortem". Blameless: câu hỏi là
"hệ thống/process nào cho phép chuyện này", không phải "ai làm sai".

## 1. Timeline (mọi dòng phải có evidence path:line)

| ISO time | Sự kiện | Evidence |
|---|---|---|
| 2026-08-25T08:54:59 | outage bắt đầu | `chaos/chaos-events.jsonl:1` |
| 2026-08-25T08:54:59 | user đầu tiên bị ảnh hưởng | `reports/drill-2-withdr.jsonl:25` |
| 2026-08-25T08:55:14 | health check alert | `reports/health-events.jsonl:2` |
| 2026-08-25T08:55:16 | operator confirm cutover | `reports/runbook-run.jsonl:2` |
| 2026-08-25T08:55:28 | resolved (request đầu tiên OK từ region phụ) | `reports/drill-2-withdr.jsonl:39` |

## 2. RTO/RPO đo được vs mục tiêu — gap ở bước nào?

- RTO mục tiêu: 300s · đo được: `28.9s` · gap: `-271.1s` (đạt chuẩn SLA)
- RPO mục tiêu: 300s · đo được: `4.0s` (`2` doc bị mất) · gap: `-296.0s` (đạt chuẩn SLA)
- **Bước tốn nhiều giây nhất:** `Health-check detection floor (14.7s)` — vì cơ chế chống flapping cần 3 lần fail liên tiếp (5s × 3 = 15s) để xác nhận sự cố thật sự.

## 3. Root cause (5 whys)

1. *Vì sao request bị gián đoạn?* Vì Region A gặp sự cố mất kết nối mạng và treo kết nối.
2. *Vì sao Region B không phục vụ ngay lập tức?* Vì cần thời gian để Health Checker xác nhận outage và kích hoạt phục hồi dữ liệu từ snapshot.
3. *Vì sao có độ trễ phát hiện 14.7s?* Vì hệ thống đặt ngưỡng anti-flap 3 lần thăm dò liên tiếp để ngăn ngừa chuyển vùng nhầm do chập chờn mạng cục bộ.
4. *Vì sao mất 2 document?* Vì chu kỳ snapshot replication là 30s nên 2 docs mới ingest trong 4.0s cuối chưa kịp đẩy lên snapshot store.
5. *Nếu đây là outage thật, bước nào trong runbook dễ rủi ro nhất?* Bước Restore Snapshot nếu phiên bản model weights không khớp với vector embeddings hoặc snapshot bị lỗi.

## 4. Action items (có owner + deadline)

| # | Action | Owner | Deadline | Giảm RTO/RPO bao nhiêu giây |
|---|---|---|---|---|
| 1 | Tối ưu chu kỳ health check thăm dò xuống 3s (detect floor 9s) | SRE Team | 2026-09-01 | Giảm RTO ~6s |
| 2 | Giảm chu kỳ replication xuống 15s kết hợp WAL stream | Data Infra | 2026-09-05 | Giảm RPO ~15s |

## 5. Ba câu hỏi bắt buộc trả lời

1. `interval × threshold` của bạn là bao nhiêu giây? Nó chiếm bao nhiêu % RTO?
   - Trả lời: $5\text{s} \times 3 = 15\text{s}$. Nó chiếm $14.7\text{s} / 28.9\text{s} \approx 50.9\%$ tổng RTO đo được.
2. Nếu hạ interval xuống 1s, RTO giảm mấy giây — và bạn trả giá gì (§4 flapping)?
   - Trả lời: RTO giảm khoảng 12 giây (detect floor giảm còn 3s). Cái giá phải trả là nguy cơ **flapping** rất cao: khi mạng chỉ lag hoặc drop gói trong tích tắc, hệ thống vội vã chuyển vùng gây gián đoạn kép và phân mảnh dữ liệu.
3. Nếu outage kéo dài 6 giờ và region chính mất dữ liệu vĩnh viễn, `docs_lost` của bạn có nghĩa gì với khách hàng?
   - Trả lời: 2 documents bị mất tương ứng với 2 yêu cầu/giao dịch của người dùng không được ghi nhận vào hệ thống tri thức. Cần cơ chế lưu đệm ở client/gateway (DLQ) để replay lại khi khôi phục.
