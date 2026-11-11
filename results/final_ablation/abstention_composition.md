# Abstention composition (router arms)

`abstained` is the harness flag: the router said out_of_scope (fixed message) or the prompt context was empty. The only should-abstain question among the 42 is S15 (gibberish). 'generator' rows are answers that carry an E14a abstention marker although evidence was in the prompt; they are not counted in the flag and are listed separately. Scoring note (v3 STATUS.md): the router's abstention message is not in E14a's marker list, so S15 scores 0 even when abstaining was right.

## C_V0: 12 abstained records ({'router': 3, 'retrieval': 9}); correct 3, unnecessary 9; questions ['S15', 'MH01', 'MH04', 'MH05']

| id | run | cat | route | router conf. | layer | correct? | scored | why |
|---|---|---|---|---|---|---|---|---|
| S15 | 1 | db | out_of_scope | 0.9927 | router | yes | 0 | route out_of_scope -> fixed abstention message |
| MH01 | 1 | multi | structured | 0.5141 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=None rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH04 | 1 | multi | structured | 0.9928 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=network_alarms rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH05 | 1 | multi | structured | 0.9926 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=fraud_cases rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| S15 | 2 | db | out_of_scope | 0.9927 | router | yes | 0 | route out_of_scope -> fixed abstention message |
| MH01 | 2 | multi | structured | 0.5141 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=None rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH04 | 2 | multi | structured | 0.9928 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=network_alarms rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH05 | 2 | multi | structured | 0.9926 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=fraud_cases rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| S15 | 3 | db | out_of_scope | 0.9927 | router | yes | 0 | route out_of_scope -> fixed abstention message |
| MH01 | 3 | multi | structured | 0.5141 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=None rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH04 | 3 | multi | structured | 0.9928 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=network_alarms rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH05 | 3 | multi | structured | 0.9926 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=fraud_cases rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |

Generator abstention-like answers not flagged (9):

| id | run | cat | route | scored | prompt docs | SQL blocks | answer |
|---|---|---|---|---|---|---|---|
| RW_017 | 1 | trai | unstructured | 0 | ['TRX_001', 'SOP_C13_APP_ACCESS_ISSUES', 'SOP_C17_KYC_VERIFICATION'] | 0 | 'ABSTAIN.\n\nThe provided evidence does not contain any information related to porting a mobile number to another telecom company. The evidence' |
| MH02 | 1 | multi | hybrid | 0 | ['RCA_INC_2026_0179', 'RCA_INC_2026_0184', 'RCA_INC_2026_0142'] | 1 | 'The provided evidence does not contain any information related to incident INC-2026-0163, the number of postpaid customers billed twice, the' |
| MH03 | 1 | multi | hybrid | 0 | ['RCA_INC_2026_0142', 'RCA_INC_2026_0184', 'RCA_INC_2026_0197'] | 0 | 'The provided evidence does not contain specific information about the Pune FTTH outage INC-2026-0179, including the time service was restore' |
| RW_017 | 2 | trai | unstructured | 0 | ['TRX_001', 'SOP_C13_APP_ACCESS_ISSUES', 'SOP_C17_KYC_VERIFICATION'] | 0 | 'ABSTAIN.\n\nThe provided evidence does not contain any information related to porting a mobile number to another telecom company. The evidence' |
| MH02 | 2 | multi | hybrid | 0 | ['RCA_INC_2026_0179', 'RCA_INC_2026_0184', 'RCA_INC_2026_0142'] | 1 | 'The provided evidence does not contain any information related to incident INC-2026-0163, the number of postpaid customers billed twice, the' |
| MH03 | 2 | multi | hybrid | 0 | ['RCA_INC_2026_0142', 'RCA_INC_2026_0184', 'RCA_INC_2026_0197'] | 0 | 'The provided evidence does not contain specific information about the Pune FTTH outage INC-2026-0179, including the time service was restore' |
| RW_017 | 3 | trai | unstructured | 0 | ['TRX_001', 'SOP_C13_APP_ACCESS_ISSUES', 'SOP_C17_KYC_VERIFICATION'] | 0 | 'ABSTAIN.\n\nThe provided evidence does not contain any information related to porting a mobile number to another telecom company. The evidence' |
| MH02 | 3 | multi | hybrid | 0 | ['RCA_INC_2026_0179', 'RCA_INC_2026_0184', 'RCA_INC_2026_0142'] | 1 | 'The provided evidence does not contain any information related to incident INC-2026-0163, the number of postpaid customers billed twice, the' |
| MH03 | 3 | multi | hybrid | 0 | ['RCA_INC_2026_0142', 'RCA_INC_2026_0184', 'RCA_INC_2026_0197'] | 0 | 'The provided evidence does not contain specific information about the Pune FTTH outage INC-2026-0179, including the time service was restore' |

## C_V1: 12 abstained records ({'router': 3, 'retrieval': 9}); correct 3, unnecessary 9; questions ['S15', 'MH01', 'MH04', 'MH05']

| id | run | cat | route | router conf. | layer | correct? | scored | why |
|---|---|---|---|---|---|---|---|---|
| S15 | 1 | db | out_of_scope | 0.9927 | router | yes | 0 | route out_of_scope -> fixed abstention message |
| MH01 | 1 | multi | structured | 0.5141 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=None rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH04 | 1 | multi | structured | 0.9928 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=network_alarms rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH05 | 1 | multi | structured | 0.9926 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=fraud_cases rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| S15 | 2 | db | out_of_scope | 0.9927 | router | yes | 0 | route out_of_scope -> fixed abstention message |
| MH01 | 2 | multi | structured | 0.5141 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=None rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH04 | 2 | multi | structured | 0.9928 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=network_alarms rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH05 | 2 | multi | structured | 0.9926 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=fraud_cases rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| S15 | 3 | db | out_of_scope | 0.9927 | router | yes | 0 | route out_of_scope -> fixed abstention message |
| MH01 | 3 | multi | structured | 0.5141 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=None rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH04 | 3 | multi | structured | 0.9928 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=network_alarms rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH05 | 3 | multi | structured | 0.9926 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=fraud_cases rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |

Generator abstention-like answers not flagged (3):

| id | run | cat | route | scored | prompt docs | SQL blocks | answer |
|---|---|---|---|---|---|---|---|
| MH03 | 1 | multi | hybrid | 0 | ['RCA_INC_2026_0184', 'RCA_INC_2026_0197', 'RCA_INC_2026_0163'] | 0 | 'The provided evidence does not contain information related to the Pune FTTH outage INC-2026-0179, including the time service was restored af' |
| MH03 | 2 | multi | hybrid | 0 | ['RCA_INC_2026_0184', 'RCA_INC_2026_0197', 'RCA_INC_2026_0163'] | 0 | 'The provided evidence does not contain information related to the Pune FTTH outage INC-2026-0179, including the time service was restored af' |
| MH03 | 3 | multi | hybrid | 0 | ['RCA_INC_2026_0184', 'RCA_INC_2026_0197', 'RCA_INC_2026_0163'] | 0 | 'The provided evidence does not contain information related to the Pune FTTH outage INC-2026-0179, including the time service was restored af' |

## C_V1_links: 12 abstained records ({'router': 3, 'retrieval': 9}); correct 3, unnecessary 9; questions ['S15', 'MH01', 'MH04', 'MH05']

| id | run | cat | route | router conf. | layer | correct? | scored | why |
|---|---|---|---|---|---|---|---|---|
| S15 | 1 | db | out_of_scope | 0.9927 | router | yes | 0 | route out_of_scope -> fixed abstention message |
| MH01 | 1 | multi | structured | 0.5141 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=None rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH04 | 1 | multi | structured | 0.9928 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=network_alarms rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH05 | 1 | multi | structured | 0.9926 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=fraud_cases rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| S15 | 2 | db | out_of_scope | 0.9927 | router | yes | 0 | route out_of_scope -> fixed abstention message |
| MH01 | 2 | multi | structured | 0.5141 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=None rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH04 | 2 | multi | structured | 0.9928 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=network_alarms rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH05 | 2 | multi | structured | 0.9926 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=fraud_cases rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| S15 | 3 | db | out_of_scope | 0.9927 | router | yes | 0 | route out_of_scope -> fixed abstention message |
| MH01 | 3 | multi | structured | 0.5141 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=None rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH04 | 3 | multi | structured | 0.9928 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=network_alarms rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |
| MH05 | 3 | multi | structured | 0.9926 | retrieval | no (answerable) | 0 | empty prompt; structured: executed=True route=direct table=fraud_cases rows=0 note=Query could not be confidently resolved to structured data. May require unstruct |

Generator abstention-like answers not flagged (0):

| id | run | cat | route | scored | prompt docs | SQL blocks | answer |
|---|---|---|---|---|---|---|---|
