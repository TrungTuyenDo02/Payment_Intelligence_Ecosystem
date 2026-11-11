# G03 hiệu chỉnh xác suất — `cal-04b3ad5944ce` (thăm dò)

Exploratory (thăm dò): development data only; validation was used before (GBM grid, leakage experiment, history features), so these numbers may be optimistic.

| Khối | Vai trò | Ngày | Dòng | Gian lận | Tỷ lệ |
| --- | --- | --- | --- | --- | --- |
| V1 | calibrate | 101–113 | 38426 | 1523 | 3,96% |
| V2 | select | 114–126 | 41426 | 1741 | 4,20% |
| V3 | evaluate | 127–141 | 38256 | 1347 | 3,52% |

Tỷ lệ gian lận train (cho dịch tiên nghiệm): 0,0338.
PR-AUC validation của mô hình tái tạo: {'gbm': 0.49703448857478155, 'logistic': 0.2453606227593842}.

## Gradient Boosting

| Phương pháp | Khối | Brier | Log loss | Xác suất TB | Tỷ lệ thật | PR-AUC |
| --- | --- | --- | --- | --- | --- | --- |
| gốc | V1 | 0,1097 | 0,3642 | 0,2762 | 0,0396 | 0,514 |
| gốc | V2 | 0,1095 | 0,3632 | 0,2770 | 0,0420 | 0,555 |
| gốc | V3 | 0,1037 | 0,3511 | 0,2610 | 0,0352 | 0,404 |
| dịch tiên nghiệm | V1 | 0,0265 | 0,1067 | 0,0310 | 0,0396 | 0,514 |
| dịch tiên nghiệm | V2 | 0,0259 | 0,1082 | 0,0331 | 0,0420 | 0,555 |
| dịch tiên nghiệm | V3 | 0,0259 | 0,1095 | 0,0270 | 0,0352 | 0,404 |
| sigmoid (Platt) | V1 (trong mẫu) | 0,0261 | 0,1048 | 0,0396 | 0,0396 | 0,514 |
| sigmoid (Platt) | V2 | 0,0253 | 0,1063 | 0,0419 | 0,0420 | 0,555 |
| sigmoid (Platt) | V3 | 0,0256 | 0,1085 | 0,0346 | 0,0352 | 0,404 |

Chọn trên V2 (log loss nhỏ nhất): **sigmoid (Platt)**.

Theo tuần (validation):

| Tuần | Khối | Tỷ lệ thật | TB gốc | Log loss gốc | TB dịch tiên nghiệm | Log loss dịch tiên nghiệm | TB sigmoid (Platt) | Log loss sigmoid (Platt) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W0 | V1 | 0,0385 | 0,2752 | 0,3603 | 0,0322 | 0,0977 | 0,0408 | 0,0965 |
| W1 | V1/V2 | 0,0428 | 0,2796 | 0,3695 | 0,0307 | 0,1187 | 0,0396 | 0,1156 |
| W2 | V2 | 0,0475 | 0,2887 | 0,3837 | 0,0352 | 0,1257 | 0,0448 | 0,1230 |
| W3 | V2/V3 | 0,0313 | 0,2600 | 0,3397 | 0,0285 | 0,0827 | 0,0361 | 0,0827 |
| W4 | V3 | 0,0404 | 0,2650 | 0,3558 | 0,0292 | 0,1212 | 0,0371 | 0,1193 |
| W5 | V3 | 0,0310 | 0,2526 | 0,3415 | 0,0243 | 0,1028 | 0,0314 | 0,1022 |

## Logistic Regression

| Phương pháp | Khối | Brier | Log loss | Xác suất TB | Tỷ lệ thật | PR-AUC |
| --- | --- | --- | --- | --- | --- | --- |
| gốc | V1 | 0,1901 | 0,5681 | 0,4080 | 0,0396 | 0,205 |
| gốc | V2 | 0,1910 | 0,5702 | 0,4119 | 0,0420 | 0,309 |
| gốc | V3 | 0,1816 | 0,5511 | 0,3989 | 0,0352 | 0,215 |
| dịch tiên nghiệm | V1 | 0,0349 | 0,1434 | 0,0335 | 0,0396 | 0,205 |
| dịch tiên nghiệm | V2 | 0,0344 | 0,1408 | 0,0361 | 0,0420 | 0,309 |
| dịch tiên nghiệm | V3 | 0,0307 | 0,1301 | 0,0326 | 0,0352 | 0,215 |
| sigmoid (Platt) | V1 (trong mẫu) | 0,0347 | 0,1426 | 0,0397 | 0,0396 | 0,205 |
| sigmoid (Platt) | V2 | 0,0341 | 0,1396 | 0,0427 | 0,0420 | 0,309 |
| sigmoid (Platt) | V3 | 0,0309 | 0,1302 | 0,0381 | 0,0352 | 0,215 |

Chọn trên V2 (log loss nhỏ nhất): **sigmoid (Platt)**.

Theo tuần (validation):

| Tuần | Khối | Tỷ lệ thật | TB gốc | Log loss gốc | TB dịch tiên nghiệm | Log loss dịch tiên nghiệm | TB sigmoid (Platt) | Log loss sigmoid (Platt) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W0 | V1 | 0,0385 | 0,4067 | 0,5633 | 0,0333 | 0,1373 | 0,0394 | 0,1363 |
| W1 | V1/V2 | 0,0428 | 0,4122 | 0,5775 | 0,0344 | 0,1538 | 0,0410 | 0,1528 |
| W2 | V2 | 0,0475 | 0,4232 | 0,5938 | 0,0374 | 0,1605 | 0,0447 | 0,1588 |
| W3 | V2/V3 | 0,0313 | 0,3950 | 0,5385 | 0,0336 | 0,1082 | 0,0389 | 0,1086 |
| W4 | V3 | 0,0404 | 0,3980 | 0,5458 | 0,0333 | 0,1424 | 0,0388 | 0,1416 |
| W5 | V3 | 0,0310 | 0,3997 | 0,5567 | 0,0315 | 0,1220 | 0,0372 | 0,1227 |

## Cửa sổ cuốn chiếu (độ nhạy)

| Cửa sổ | Hiệu chỉnh / chọn / đánh giá | Mô hình | Chọn | Log loss đánh giá |
| --- | --- | --- | --- | --- |
| R1 | W0/W1/W2 | Gradient Boosting | sigmoid (Platt) | gốc 0,3837, dịch tiên nghiệm 0,1257, sigmoid (Platt) 0,1235 |
| R1 | W0/W1/W2 | Logistic Regression | sigmoid (Platt) | gốc 0,5938, dịch tiên nghiệm 0,1605, sigmoid (Platt) 0,1589 |
| R2 | W1/W2/W3 | Gradient Boosting | sigmoid (Platt) | gốc 0,3397, dịch tiên nghiệm 0,0827, sigmoid (Platt) 0,0834 |
| R2 | W1/W2/W3 | Logistic Regression | sigmoid (Platt) | gốc 0,5385, dịch tiên nghiệm 0,1082, sigmoid (Platt) 0,1093 |
| R3 | W2/W3/W4 | Gradient Boosting | dịch tiên nghiệm | gốc 0,3558, dịch tiên nghiệm 0,1212, sigmoid (Platt) 0,1184 |
| R3 | W2/W3/W4 | Logistic Regression | dịch tiên nghiệm | gốc 0,5458, dịch tiên nghiệm 0,1424, sigmoid (Platt) 0,1416 |
| R4 | W3/W4/W5 | Gradient Boosting | sigmoid (Platt) | gốc 0,3415, dịch tiên nghiệm 0,1028, sigmoid (Platt) 0,1028 |
| R4 | W3/W4/W5 | Logistic Regression | dịch tiên nghiệm | gốc 0,5567, dịch tiên nghiệm 0,1220, sigmoid (Platt) 0,1225 |

## Tự kiểm tra

- Hoán vị nhãn V3: PR-AUC của GBM 0,0355, tỷ lệ gian lận V3 0,0352 (mức ngẫu nhiên).
- Hiệu chỉnh đơn điệu: PR-AUC giống nhau giữa các phương pháp trong cùng khối.
