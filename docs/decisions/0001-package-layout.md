# ADR 0001 — Package snake_case bên trong thư mục có dấu gạch ngang

- **Trạng thái:** Accepted (quyết định D1 của chủ dự án trong `AGENTS.md`, 2026-11-02)
- **Phạm vi:** toàn bộ code Python trong `shared/` và `projects/`

## Bối cảnh

`AGENTS.md` mục 5 quy định các thư mục như `projects/fraud-risk/` và `shared/dataset-management/`.
Python không import được tên có dấu `-`, nên không thể viết `import fraud-risk.adapters`.

Ba phương án đã được cân nhắc:

| Phương án | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| A. Đưa thẳng `projects/fraud-risk` vào pythonpath, import `adapters`, `evaluation`... | Khớp layout 100% | Tên chung chung (`adapters`, `features`, `common`) sẽ trùng khi Product 01 có code ở Stage D |
| **B. Giữ thư mục ngoài, thêm package snake_case bên trong** | Import rõ ràng (`fraud_risk.evaluation.split`), không trùng tên | Lệch nhẹ so với "create exactly this" (thêm một cấp thư mục) |
| C. Đổi `-` thành `_` | Đơn giản | Phá layout và tên đã chốt |

## Quyết định

Chọn **B**.

- `projects/fraud-risk/fraud_risk/{adapters,features,eda,evaluation,baselines,scripts}/` chứa code.
- `projects/fraud-risk/configs/` (YAML) và `projects/fraud-risk/tests/` vẫn ở cấp thư mục ngoài vì không phải code import được.
- `shared/dataset-management/dataset_management/` chứa code tooling manifest (T03).
- Quy tắc đặt tên: package = tên thư mục, đổi `-` thành `_`. Với tên quá chung (`shared/common`), chọn tên package có tiền tố khi thực sự cần, và ghi vào ADR mới.
- Không build/cài đặt project như một package: `pyproject.toml` đặt `[tool.uv] package = false`.
  - pytest: `pythonpath` trỏ tới các thư mục cha (`shared/dataset-management`, `projects/fraud-risk`).
  - Makefile: export `PYTHONPATH` tương tự; CLI chạy bằng `python -m fraud_risk.scripts.<tên>`.

## Hệ quả

- Thêm một package mới thì phải thêm thư mục cha của nó vào `pythonpath` (pytest) và `PYTHONPATH` (Makefile). Test `tests/test_layout.py::test_package_importable` sẽ báo lỗi nếu quên.
- IDE cần được trỏ `PYTHONPATH` giống Makefile để tự động gợi ý import.
