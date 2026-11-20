# Tables for run baseline-20261119c

## Log-log slopes (time vs samples, medians)

| operation | slope |
|---|---|
| expression_import_total | 1.08 |
| retrieval_raw_find | 1.04 |
| retrieval_load_rows | 1.27 |
| matrix_build_full | 0.83 |
| matrix_page1_function | 0.81 |
| matrix_page2_function | 0.81 |
| matrix_page1_http | 0.83 |
| matrix_export_function | 0.79 |
| pcoa_parse | 1.01 |
| pcoa_run_on_matrix_total | 1.34 |
| heatmap_cluster_matrix_total | 0.77 |
| hclust_js_items | 1.81 |
| legacy_function_breakdown[counts] | 1.46 |
| legacy_config[counts] | 0.87 |
| legacy_function_breakdown[tpm] | 1.41 |

## Process outcomes

| suite | samples | status | wall s |
|---|---|---|---|
| legacy | 32 | ok | 3.3 |
| legacy | 100 | ok | 6.4 |
| legacy | 250 | ok | 9.5 |
| legacy | 500 | ok | 10.3 |
| legacy | 1000 | ok | 63.9 |
| legacy_tpm | 32 | ok | 3.5 |
| legacy_tpm | 100 | ok | 6.0 |
| legacy_tpm | 250 | ok | 6.1 |
| legacy_tpm | 500 | ok | 15.3 |
| legacy_tpm | 1000 | ok | 76.5 |
| numerical | 32 | ok | 6.0 |
| numerical | 100 | ok | 10.9 |
| numerical | 250 | ok | 25.1 |
| numerical | 500 | ok | 52.6 |
| numerical | 1000 | ok | 153.7 |
| numerical | 32 | ok | 0.3 |
| numerical | 100 | ok | 0.1 |
| numerical | 250 | ok | 0.2 |
| numerical | 500 | ok | 0.3 |
| numerical | 1000 | ok | 1.4 |
| numerical | 2000 | ok | 10.1 |
| orthology | 32 | ok | 518.6 |
| orthology | 100 | ok | 752.6 |
| orthology | 250 | ok | 744.3 |
| orthology | 500 | ok | 576.4 |
| orthology | 1000 | ok | 2507.5 |

## All operations

| workflow | operation | variant | S | n ok/total | median s | IQR s | min–max s | peak RSS MB | statuses |
|---|---|---|---|---|---|---|---|---|---|
| legacy | legacy_config | counts | 32 | 5/5 | 0.1344 | 0.0074 | 0.1324–0.1691 | 319.2 | ok=5 |
| legacy | legacy_config | tpm | 32 | 5/5 | 0.1193 | 0.0036 | 0.1181–0.155 | 341.6 | ok=5 |
| legacy | legacy_config | counts | 100 | 5/5 | 0.3534 | 0.0263 | 0.3255–0.6076 | 668.0 | ok=5 |
| legacy | legacy_config | tpm | 100 | 5/5 | 0.3669 | 0.0097 | 0.347–0.4054 | 790.8 | ok=5 |
| legacy | legacy_config | counts | 250 | 5/5 | 0.7971 | 0.0332 | 0.7683–0.8039 | 1167.2 | ok=5 |
| legacy | legacy_config_two_matrices | counts | 32 | 1/1 | 0.1449 | 0.0 | 0.1449–0.1449 | 367.2 | ok=1 |
| legacy | legacy_config_two_matrices | tpm | 32 | 1/1 | 0.1675 | 0.0 | 0.1675–0.1675 | 393.7 | ok=1 |
| legacy | legacy_config_two_matrices | counts | 100 | 1/1 | 0.3488 | 0.0 | 0.3488–0.3488 | 866.0 | ok=1 |
| legacy | legacy_function_breakdown | counts | 32 | 3/3 | 0.0944 | 0.0043 | 0.0922–0.1007 | 393.2 | ok=3 |
| legacy | legacy_function_breakdown | tpm | 32 | 3/3 | 0.1445 | 0.0024 | 0.1444–0.1491 | 414.0 | ok=3 |
| legacy | legacy_function_breakdown | counts | 100 | 3/3 | 0.2929 | 0.1252 | 0.2593–0.5096 | 910.9 | ok=3 |
| legacy | legacy_function_breakdown | tpm | 100 | 3/3 | 0.4075 | 0.0117 | 0.4007–0.4242 | 877.2 | ok=3 |
| legacy | legacy_function_breakdown | counts | 250 | 3/3 | 0.6546 | 0.0065 | 0.653–0.666 | 1173.6 | ok=3 |
| legacy | legacy_function_breakdown | tpm | 250 | 3/3 | 1.0508 | 0.0231 | 1.0114–1.0575 | 677.9 | ok=3 |
| legacy | legacy_function_breakdown | counts | 500 | 3/3 | 2.3348 | 0.0339 | 2.2878–2.3556 | 616.9 | ok=3 |
| legacy | legacy_function_breakdown | tpm | 500 | 3/3 | 3.4109 | 0.1818 | 3.2767–3.6404 | 909.3 | ok=3 |
| legacy | legacy_function_breakdown | counts | 1000 | 3/3 | 19.4788 | 0.4296 | 19.147–20.0061 | 1003.8 | ok=3 |
| legacy | legacy_function_breakdown | tpm | 1000 | 3/3 | 23.0651 | 0.1028 | 22.9686–23.1743 | 1328.7 | ok=3 |
| legacy | legacy_query_filter | counts | 32 | 5/5 | 0.0252 | 0.0021 | 0.022–0.0931 | 310.7 | ok=5 |
| legacy | legacy_query_filter | tpm | 32 | 5/5 | 0.0497 | 0.0017 | 0.0252–0.0704 | 331.1 | ok=5 |
| legacy | legacy_query_filter | counts | 100 | 5/5 | 0.0503 | 0.0253 | 0.046–0.0963 | 600.8 | ok=5 |
| legacy | legacy_query_filter | tpm | 100 | 5/5 | 0.0752 | 0.0033 | 0.0708–0.1209 | 754.1 | ok=5 |
| legacy | legacy_query_filter | counts | 250 | 5/5 | 0.095 | 0.0076 | 0.091–0.1239 | 1152.1 | ok=5 |
| legacy | legacy_upload | counts | 32 | 5/5 | 0.0482 | 0.0017 | 0.0438–0.1416 | 309.9 | ok=5 |
| legacy | legacy_upload | tpm | 32 | 5/5 | 0.0705 | 0.0213 | 0.0502–0.0986 | 329.8 | ok=5 |
| legacy | legacy_upload | counts | 100 | 5/5 | 0.0979 | 0.022 | 0.0914–0.1949 | 600.5 | ok=5 |
| legacy | legacy_upload | tpm | 100 | 5/5 | 0.1471 | 0.0025 | 0.1461–0.1994 | 773.7 | ok=5 |
| legacy | legacy_upload | counts | 250 | 5/5 | 0.2144 | 0.013 | 0.1977–0.27 | 1154.5 | ok=5 |
| legacy | legacy_upload | tpm | 250 | 0/5 |  |  |  | 498.4 | app_error=5 |
| legacy | legacy_upload | counts | 500 | 0/5 |  |  |  | 486.0 | app_error=5 |
| legacy | legacy_upload | tpm | 500 | 0/5 |  |  |  | 738.6 | app_error=5 |
| legacy | legacy_upload | counts | 1000 | 0/5 |  |  |  | 844.4 | app_error=5 |
| legacy | legacy_upload | tpm | 1000 | 0/5 |  |  |  | 1166.0 | app_error=5 |
| legacy | legacy_upload_second_matrix | counts | 32 | 1/1 | 0.0988 | 0.0 | 0.0988–0.0988 | 321.9 | ok=1 |
| legacy | legacy_upload_second_matrix | tpm | 32 | 1/1 | 0.1444 | 0.0 | 0.1444–0.1444 | 349.1 | ok=1 |
| legacy | legacy_upload_second_matrix | counts | 100 | 1/1 | 0.1993 | 0.0 | 0.1993–0.1993 | 707.7 | ok=1 |
| legacy | legacy_upload_second_matrix | tpm | 100 | 0/1 |  |  |  | 854.7 | app_error=1 |
| legacy | legacy_upload_second_matrix | counts | 250 | 0/1 |  |  |  | 1167.0 | app_error=1 |
| legacy | session_doc_after_query | counts | 32 | 5/5 |  |  |  |  | ok=5 |
| legacy | session_doc_after_query | tpm | 32 | 5/5 |  |  |  |  | ok=5 |
| legacy | session_doc_after_query | counts | 100 | 5/5 |  |  |  |  | ok=5 |
| legacy | session_doc_after_query | tpm | 100 | 5/5 |  |  |  |  | ok=5 |
| legacy | session_doc_after_query | counts | 250 | 5/5 |  |  |  |  | ok=5 |
| legacy | session_doc_after_second_matrix | counts | 32 | 1/1 |  |  |  |  | ok=1 |
| legacy | session_doc_after_second_matrix | tpm | 32 | 1/1 |  |  |  |  | ok=1 |
| legacy | session_doc_after_second_matrix | counts | 100 | 1/1 |  |  |  |  | ok=1 |
| legacy | session_doc_after_upload | counts | 32 | 5/5 |  |  |  |  | ok=5 |
| legacy | session_doc_after_upload | tpm | 32 | 5/5 |  |  |  |  | ok=5 |
| legacy | session_doc_after_upload | counts | 100 | 5/5 |  |  |  |  | ok=5 |
| legacy | session_doc_after_upload | tpm | 100 | 5/5 |  |  |  |  | ok=5 |
| legacy | session_doc_after_upload | counts | 250 | 5/5 |  |  |  |  | ok=5 |
| numerical | hclust_js_items |  | 32 | 3/3 | 0.0016 | 0.0009 | 0.0004–0.0023 | 54.5 | ok=3 |
| numerical | hclust_js_items |  | 100 | 3/3 | 0.0056 | 0.0029 | 0.0022–0.0081 | 65.1 | ok=3 |
| numerical | hclust_js_items |  | 250 | 3/3 | 0.0104 | 0.0141 | 0.0084–0.0366 | 82.5 | ok=3 |
| numerical | hclust_js_items |  | 500 | 3/3 | 0.0597 | 0.009 | 0.058–0.076 | 155.7 | ok=3 |
| numerical | hclust_js_items |  | 1000 | 3/3 | 0.4176 | 0.0187 | 0.4091–0.4466 | 212.5 | ok=3 |
| numerical | hclust_js_items |  | 2000 | 3/3 | 3.3155 | 0.0508 | 3.2576–3.3592 | 424.8 | ok=3 |
| numerical | hclust_js_items |  | 6000 | 0/1 |  |  |  |  | skipped_unsafe=1 |
| numerical | heatmap_cluster_matrix_total |  | 32 | 3/3 | 0.7085 | 0.0191 | 0.6965–0.7347 | 473.1 | ok=3 |
| numerical | heatmap_cluster_matrix_total |  | 100 | 3/3 | 1.1892 | 0.0037 | 1.1883–1.1956 | 529.0 | ok=3 |
| numerical | heatmap_cluster_matrix_total |  | 250 | 3/3 | 2.3521 | 0.0413 | 2.3318–2.4144 | 692.0 | ok=3 |
| numerical | heatmap_cluster_matrix_total |  | 500 | 3/3 | 4.6408 | 0.0484 | 4.615–4.7118 | 943.7 | ok=3 |
| numerical | heatmap_cluster_matrix_total |  | 1000 | 3/3 | 10.1813 | 0.076 | 10.1724–10.3244 | 1129.0 | ok=3 |
| numerical | heatmap_stages |  | 32 | 3/3 | 0.7363 | 0.037 | 0.7246–0.7986 | 483.4 | ok=3 |
| numerical | heatmap_stages |  | 100 | 3/3 | 1.5181 | 0.0701 | 1.5174–1.6576 | 488.8 | ok=3 |
| numerical | heatmap_stages |  | 250 | 3/3 | 3.9801 | 0.111 | 3.9103–4.1322 | 516.5 | ok=3 |
| numerical | heatmap_stages |  | 500 | 3/3 | 8.3492 | 0.268 | 8.3479–8.8839 | 574.6 | ok=3 |
| numerical | heatmap_stages |  | 1000 | 3/3 | 22.7824 | 0.6936 | 22.2242–23.6115 | 519.6 | ok=3 |
| numerical | pcoa_parse |  | 32 | 3/3 | 0.1122 | 0.0055 | 0.1068–0.1178 | 186.6 | ok=3 |
| numerical | pcoa_parse |  | 100 | 3/3 | 0.3293 | 0.0042 | 0.3245–0.3329 | 250.4 | ok=3 |
| numerical | pcoa_parse |  | 250 | 3/3 | 0.8486 | 0.0087 | 0.846–0.8633 | 411.4 | ok=3 |
| numerical | pcoa_parse |  | 500 | 3/3 | 1.7369 | 0.0274 | 1.6913–1.746 | 695.5 | ok=3 |
| numerical | pcoa_parse |  | 1000 | 3/3 | 3.5887 | 0.0385 | 3.5137–3.5908 | 1106.8 | ok=3 |
| numerical | pcoa_parse_6000_features |  | 32 | 0/1 |  |  |  | 156.0 | rejected_by_app=1 |
| numerical | pcoa_parse_6000_features |  | 100 | 0/1 |  |  |  | 233.9 | rejected_by_app=1 |
| numerical | pcoa_parse_6000_features |  | 250 | 0/1 |  |  |  | 384.2 | rejected_by_app=1 |
| numerical | pcoa_parse_6000_features |  | 500 | 0/1 |  |  |  | 638.9 | rejected_by_app=1 |
| numerical | pcoa_parse_6000_features |  | 1000 | 0/1 |  |  |  | 1147.5 | rejected_by_app=1 |
| numerical | pcoa_run_on_matrix_total |  | 32 | 5/5 | 0.0252 | 0.0029 | 0.0222–0.0253 | 183.6 | ok=5 |
| numerical | pcoa_run_on_matrix_total |  | 100 | 5/5 | 0.0257 | 0.0077 | 0.0238–0.0656 | 224.9 | ok=5 |
| numerical | pcoa_run_on_matrix_total |  | 250 | 5/5 | 0.1296 | 0.031 | 0.1021–0.1578 | 376.6 | ok=5 |
| numerical | pcoa_run_on_matrix_total |  | 500 | 5/5 | 0.4285 | 0.1143 | 0.3912–0.5108 | 571.4 | ok=5 |
| numerical | pcoa_run_on_matrix_total |  | 1000 | 5/5 | 2.2585 | 0.1775 | 2.0276–2.5662 | 701.1 | ok=5 |
| numerical | pcoa_stages |  | 32 | 5/5 | 0.0252 | 0.0 | 0.0252–0.0252 | 183.5 | ok=5 |
| numerical | pcoa_stages |  | 100 | 5/5 | 0.0332 | 0.0474 | 0.0251–0.093 | 224.8 | ok=5 |
| numerical | pcoa_stages |  | 250 | 5/5 | 0.1204 | 0.0321 | 0.0998–0.1611 | 376.5 | ok=5 |
| numerical | pcoa_stages |  | 500 | 5/5 | 0.3895 | 0.0221 | 0.35–0.4727 | 624.9 | ok=5 |
| numerical | pcoa_stages |  | 1000 | 5/5 | 2.711 | 6.0951 | 2.4112–9.5886 | 1015.8 | ok=5 |
| orthology | expression_import_total |  | 32 | 3/3 | 6.7565 | 0.0166 | 6.7329–6.7661 | 484.0 | ok=3 |
| orthology | expression_import_total |  | 100 | 3/3 | 21.4016 | 0.1065 | 21.2565–21.4695 | 904.1 | ok=3 |
| orthology | expression_import_total |  | 250 | 3/3 | 54.257 | 1.0465 | 53.6102–55.7031 | 1618.5 | ok=3 |
| orthology | expression_import_total |  | 500 | 1/1 | 116.4046 | 0.0 | 116.4046–116.4046 | 2312.1 | ok=1 |
| orthology | expression_import_total |  | 1000 | 1/1 | 291.7342 | 0.0 | 291.7342–291.7342 | 3684.3 | ok=1 |
| orthology | http_expression_upload |  | 32 | 1/1 | 6.7682 | 0.0 | 6.7682–6.7682 | 459.5 | ok=1 |
| orthology | http_expression_upload |  | 100 | 1/1 | 21.5092 | 0.0 | 21.5092–21.5092 | 825.7 | ok=1 |
| orthology | http_expression_upload |  | 250 | 0/1 |  |  |  | 205.4 | rejected_413=1 |
| orthology | http_expression_upload |  | 500 | 0/1 |  |  |  | 207.9 | rejected_413=1 |
| orthology | http_expression_upload |  | 1000 | 0/1 |  |  |  | 205.3 | rejected_413=1 |
| orthology | matrix_build_full |  | 32 | 5/5 | 8.3484 | 0.2208 | 8.24–8.9066 | 525.2 | ok=5 |
| orthology | matrix_build_full |  | 100 | 5/5 | 11.1858 | 0.0684 | 11.1343–11.2929 | 1237.2 | ok=5 |
| orthology | matrix_build_full |  | 250 | 5/5 | 17.5805 | 0.3971 | 17.4351–19.1497 | 2529.6 | ok=5 |
| orthology | matrix_build_full |  | 500 | 1/1 | 32.9525 | 0.0 | 32.9525–32.9525 | 3889.7 | ok=1 |
| orthology | matrix_build_full |  | 1000 | 1/1 | 194.036 | 0.0 | 194.036–194.036 | 5079.3 | ok=1 |
| orthology | matrix_build_stage_profile |  | 32 | 5/5 | 8.3383 | 0.0399 | 8.2909–8.3685 | 504.3 | ok=5 |
| orthology | matrix_build_stage_profile |  | 100 | 5/5 | 11.2492 | 0.0297 | 11.2171–11.3469 | 1243.3 | ok=5 |
| orthology | matrix_build_stage_profile |  | 250 | 1/1 | 17.8789 | 0.0 | 17.8789–17.8789 | 2584.2 | ok=1 |
| orthology | matrix_build_stage_profile |  | 500 | 1/1 | 33.2133 | 0.0 | 33.2133–33.2133 | 3846.9 | ok=1 |
| orthology | matrix_build_stage_profile |  | 1000 | 1/1 | 188.3402 | 0.0 | 188.3402–188.3402 | 5859.2 | ok=1 |
| orthology | matrix_export_function |  | 32 | 5/5 | 8.4717 | 0.0106 | 8.448–8.5134 | 498.5 | ok=5 |
| orthology | matrix_export_function |  | 100 | 5/5 | 11.6713 | 0.0488 | 11.605–11.7375 | 1212.9 | ok=5 |
| orthology | matrix_export_function |  | 250 | 5/5 | 18.8481 | 0.0492 | 18.8007–19.0861 | 2547.8 | ok=5 |
| orthology | matrix_export_function |  | 500 | 1/1 | 33.4731 | 0.0 | 33.4731–33.4731 | 4067.6 | ok=1 |
| orthology | matrix_export_function |  | 1000 | 1/1 | 168.7677 | 0.0 | 168.7677–168.7677 | 5893.0 | ok=1 |
| orthology | matrix_export_http |  | 32 | 1/1 | 8.5005 | 0.0 | 8.5005–8.5005 | 490.1 | ok=1 |
| orthology | matrix_export_http |  | 100 | 1/1 | 11.6368 | 0.0 | 11.6368–11.6368 | 1157.9 | ok=1 |
| orthology | matrix_export_http |  | 250 | 1/1 | 19.0012 | 0.0 | 19.0012–19.0012 | 2517.5 | ok=1 |
| orthology | matrix_page1_cpm |  | 32 | 5/5 | 8.5881 | 0.2615 | 8.3467–9.4876 | 513.2 | ok=5 |
| orthology | matrix_page1_cpm |  | 100 | 5/5 | 10.8496 | 0.0581 | 10.7857–10.9265 | 1225.9 | ok=5 |
| orthology | matrix_page1_cpm |  | 250 | 1/1 | 17.9895 | 0.0 | 17.9895–17.9895 | 2514.6 | ok=1 |
| orthology | matrix_page1_filter_2_strains |  | 32 | 5/5 | 5.6726 | 0.0277 | 5.6488–5.7386 | 376.0 | ok=5 |
| orthology | matrix_page1_filter_2_strains |  | 100 | 5/5 | 6.3219 | 0.1112 | 6.3057–6.4549 | 740.1 | ok=5 |
| orthology | matrix_page1_filter_2_strains |  | 250 | 1/1 | 7.9537 | 0.0 | 7.9537–7.9537 | 1310.1 | ok=1 |
| orthology | matrix_page1_function |  | 32 | 5/5 | 8.0708 | 0.4639 | 7.9308–9.2635 | 521.6 | ok=5 |
| orthology | matrix_page1_function |  | 100 | 5/5 | 11.2953 | 0.289 | 10.8515–11.4018 | 1252.5 | ok=5 |
| orthology | matrix_page1_function |  | 250 | 3/3 | 17.2463 | 0.0722 | 17.1678–17.3122 | 2580.2 | ok=3 |
| orthology | matrix_page1_function |  | 500 | 3/3 | 34.1937 | 2.8851 | 33.7831–39.5534 | 4096.1 | ok=3 |
| orthology | matrix_page1_function |  | 1000 | 3/3 | 169.034 | 3.2087 | 167.4414–173.8589 | 6025.2 | ok=3 |
| orthology | matrix_page1_http |  | 32 | 3/3 | 8.3094 | 0.0469 | 8.2965–8.3903 | 512.9 | ok=3 |
| orthology | matrix_page1_http |  | 100 | 3/3 | 10.8719 | 0.1189 | 10.8678–11.1055 | 1239.4 | ok=3 |
| orthology | matrix_page1_http |  | 250 | 3/3 | 17.7977 | 0.3736 | 17.1966–17.9438 | 2471.6 | ok=3 |
| orthology | matrix_page1_http |  | 500 | 1/1 | 36.427 | 0.0 | 36.427–36.427 | 3906.3 | ok=1 |
| orthology | matrix_page1_http |  | 1000 | 1/1 | 182.7888 | 0.0 | 182.7888–182.7888 | 5775.9 | ok=1 |
| orthology | matrix_page1_log2cpm |  | 32 | 5/5 | 8.4325 | 0.2134 | 8.3128–8.9187 | 501.9 | ok=5 |
| orthology | matrix_page1_log2cpm |  | 100 | 5/5 | 10.8412 | 0.0611 | 10.7371–10.9006 | 1250.1 | ok=5 |
| orthology | matrix_page1_log2cpm |  | 250 | 1/1 | 17.4156 | 0.0 | 17.4156–17.4156 | 2564.9 | ok=1 |
| orthology | matrix_page1_paralog_max |  | 32 | 5/5 | 8.2459 | 0.0543 | 8.2023–8.2909 | 487.8 | ok=5 |
| orthology | matrix_page1_paralog_max |  | 100 | 5/5 | 11.0056 | 0.0827 | 10.8266–11.0575 | 1229.0 | ok=5 |
| orthology | matrix_page1_paralog_max |  | 250 | 1/1 | 17.6157 | 0.0 | 17.6157–17.6157 | 2477.6 | ok=1 |
| orthology | matrix_page1_replicate_mean |  | 32 | 5/5 | 8.3853 | 0.1147 | 8.2983–8.622 | 484.6 | ok=5 |
| orthology | matrix_page1_replicate_mean |  | 100 | 5/5 | 10.8886 | 0.0523 | 10.8243–10.9564 | 1260.6 | ok=5 |
| orthology | matrix_page1_replicate_mean |  | 250 | 1/1 | 17.3115 | 0.0 | 17.3115–17.3115 | 2454.7 | ok=1 |
| orthology | matrix_page1_search |  | 32 | 5/5 | 2.3329 | 0.0259 | 2.3038–2.3721 | 502.8 | ok=5 |
| orthology | matrix_page1_search |  | 100 | 5/5 | 5.8537 | 0.0186 | 5.8242–5.8927 | 1177.6 | ok=5 |
| orthology | matrix_page1_search |  | 250 | 1/1 | 13.877 | 0.0 | 13.877–13.877 | 2503.0 | ok=1 |
| orthology | matrix_page2_function |  | 32 | 5/5 | 8.001 | 0.281 | 7.8507–8.8 | 523.8 | ok=5 |
| orthology | matrix_page2_function |  | 100 | 5/5 | 11.322 | 0.1645 | 10.7551–11.4076 | 1215.2 | ok=5 |
| orthology | matrix_page2_function |  | 250 | 3/3 | 17.3479 | 0.1642 | 17.231–17.5595 | 2575.2 | ok=3 |
| orthology | matrix_page2_function |  | 500 | 3/3 | 32.6027 | 3.0048 | 30.1886–36.1981 | 4119.9 | ok=3 |
| orthology | matrix_page2_function |  | 1000 | 3/3 | 171.0885 | 6.1826 | 163.6038–175.969 | 5844.4 | ok=3 |
| orthology | matrix_page2_http |  | 32 | 3/3 | 8.2289 | 0.0086 | 8.2242–8.2415 | 510.9 | ok=3 |
| orthology | matrix_page2_http |  | 100 | 3/3 | 10.8719 | 0.1403 | 10.7399–11.0205 | 1209.2 | ok=3 |
| orthology | matrix_page2_http |  | 250 | 3/3 | 17.9995 | 0.1892 | 17.7975–18.1759 | 2445.6 | ok=3 |
| orthology | matrix_page2_http |  | 500 | 1/1 | 30.9195 | 0.0 | 30.9195–30.9195 | 4035.6 | ok=1 |
| orthology | matrix_page2_http |  | 1000 | 1/1 | 171.7823 | 0.0 | 171.7823–171.7823 | 5036.9 | ok=1 |
| orthology | retrieval_explain |  | 32 | 1/1 | 0.1596 | 0.0 | 0.1596–0.1596 | 403.7 | ok=1 |
| orthology | retrieval_explain |  | 100 | 1/1 | 0.4516 | 0.0 | 0.4516–0.4516 | 354.2 | ok=1 |
| orthology | retrieval_explain |  | 250 | 1/1 | 1.1255 | 0.0 | 1.1255–1.1255 | 342.0 | ok=1 |
| orthology | retrieval_explain |  | 500 | 1/1 | 2.4544 | 0.0 | 2.4544–2.4544 | 347.3 | ok=1 |
| orthology | retrieval_explain |  | 1000 | 1/1 | 5.2237 | 0.0 | 5.2237–5.2237 | 470.1 | ok=1 |
| orthology | retrieval_load_rows |  | 32 | 5/5 | 0.847 | 0.003 | 0.8185–0.8489 | 554.3 | ok=5 |
| orthology | retrieval_load_rows |  | 100 | 5/5 | 2.6147 | 0.0121 | 2.573–2.6477 | 1134.1 | ok=5 |
| orthology | retrieval_load_rows |  | 250 | 5/5 | 6.4395 | 0.0448 | 6.3958–6.5442 | 2354.8 | ok=5 |
| orthology | retrieval_load_rows |  | 500 | 3/3 | 17.7609 | 4.3706 | 16.3677–25.1089 | 3801.4 | ok=3 |
| orthology | retrieval_load_rows |  | 1000 | 3/3 | 79.1536 | 0.914 | 77.7679–79.5958 | 5003.5 | ok=3 |
| orthology | retrieval_raw_find |  | 32 | 5/5 | 0.3963 | 0.0223 | 0.3862–0.4317 | 629.8 | ok=5 |
| orthology | retrieval_raw_find |  | 100 | 5/5 | 1.183 | 0.0619 | 1.1537–1.293 | 1207.7 | ok=5 |
| orthology | retrieval_raw_find |  | 250 | 5/5 | 2.9187 | 0.162 | 2.91–3.1867 | 2051.7 | ok=5 |
| orthology | retrieval_raw_find |  | 500 | 3/3 | 6.6444 | 0.2044 | 6.3241–6.7328 | 2849.2 | ok=3 |
| orthology | retrieval_raw_find |  | 1000 | 3/3 | 13.8758 | 0.6983 | 13.3053–14.7018 | 4586.7 | ok=3 |
| orthology | storage_stats |  | 32 | 1/1 |  |  |  |  | ok=1 |
| orthology | storage_stats |  | 100 | 1/1 |  |  |  |  | ok=1 |
| orthology | storage_stats |  | 250 | 1/1 |  |  |  |  | ok=1 |
| orthology | storage_stats |  | 500 | 1/1 |  |  |  |  | ok=1 |
| orthology | storage_stats |  | 1000 | 1/1 |  |  |  |  | ok=1 |
