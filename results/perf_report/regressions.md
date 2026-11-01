# Regressions: right in B2, wrong in C

Question level (right = fully correct in a majority of the 3 runs). If C were not better than B2 this file would say so; see the summary below.

Summary C vs B2: wins 3, losses 8, ties 31, McNemar exact p = 0.2266; paired bootstrap 95% CI of the difference [-28.6, 0.8] pts (mean -13.5 pts).

## Q17 (syn) - What documents do I need to provide if NovaTel asks me to complete KYC verification again?

**Run 1** - B2 correctness 2, C correctness 0, C route `unstructured`, suspected cause: ranking: gold present but not first; cited distractor ['TRX_007', 'EML_008']

- B2 answer: 'To complete KYC re-verification with NovaTel, you need to provide one government-issued Proof of Identity and one Proof of Address. These can be documents such as Aadhaar, Passport, Voter ID, or Driving Licence. For the fastest route, you can use Aadhaar-based e-KYC via OTP if it is offered and you have consent to do so [E6].\n\nIf you choose to do the verification via the My NovaTel app, you can follow the Video KYC process under the Account > KYC Update section. Alternatively, you can visit any Experience Store with your original ID and address proof [E2][E4].\n\nOutgoing services may be suspended if the re-verification is not completed within the stated window [E2][E4].'
- C answer: 'To complete KYC re-verification if asked by NovaTel, you can either:\n\n- Visit a NovaTel Experience Store with your original ID proof, or\n- Complete Video KYC via the My NovaTel app under Account > KYC Update, if it is enabled in your circle.\n\nFailure to complete this within the notified window may result in service suspension, as per regulatory requirements [E1][E2][E3].'
- C documents in prompt: ['TRX_007', 'EML_008', 'FAQ_C17_034']; added by the layer: ['FAQ_C05_010_chunk_001']

**Run 2** - B2 correctness 2, C correctness 0, C route `unstructured`, suspected cause: ranking: gold present but not first; cited distractor ['TRX_007', 'EML_008']

- B2 answer: 'To complete KYC re-verification with NovaTel, you need to provide one government-issued Proof of Identity and one Proof of Address. These can be documents such as Aadhaar, Passport, Voter ID, or Driving Licence. For the fastest route, you can use Aadhaar-based e-KYC via OTP if it is offered and you have consent to do so [E6].\n\nIf you choose to do the verification via the My NovaTel app, you can follow the Video KYC process under the Account > KYC Update section. Alternatively, you can visit any Experience Store with your original ID and address proof [E2][E4].\n\nOutgoing services may be suspended if the re-verification is not completed within the stated window [E2][E4].'
- C answer: 'To complete KYC re-verification if asked by NovaTel, you can either:\n\n- Visit a NovaTel Experience Store with your original ID proof, or\n- Complete Video KYC via the My NovaTel app under Account > KYC Update, if it is enabled in your circle.\n\nFailure to complete this within the notified window may result in service suspension, as per regulatory requirements [E1][E2][E3].'
- C documents in prompt: ['TRX_007', 'EML_008', 'FAQ_C17_034']; added by the layer: ['FAQ_C05_010_chunk_001']

**Run 3** - B2 correctness 2, C correctness 0, C route `unstructured`, suspected cause: ranking: gold present but not first; cited distractor ['TRX_007', 'EML_008']

- B2 answer: 'To complete KYC re-verification with NovaTel, you need to provide one government-issued Proof of Identity and one Proof of Address. These can be documents such as Aadhaar, Passport, Voter ID, or Driving Licence. For the fastest route, you can use Aadhaar-based e-KYC via OTP if it is offered and you have consent to do so [E6].\n\nIf you choose to do the verification via the My NovaTel app, you can follow the Video KYC process under the Account > KYC Update section. Alternatively, you can visit any Experience Store with your original ID and address proof [E2][E4].\n\nOutgoing services may be suspended if the re-verification is not completed within the stated window [E2][E4].'
- C answer: 'To complete KYC re-verification if asked by NovaTel, you can either:\n\n- Visit a NovaTel Experience Store with your original ID proof, or\n- Complete Video KYC via the My NovaTel app under Account > KYC Update, if it is enabled in your circle.\n\nFailure to complete this within the notified window may result in service suspension, as per regulatory requirements [E1][E2][E3].'
- C documents in prompt: ['TRX_007', 'EML_008', 'FAQ_C17_034']; added by the layer: ['FAQ_C05_010_chunk_001']

## RW_017 (trai) - How do I port my mobile number to another telecom company?

**Run 1** - B2 correctness 2, C correctness 0, C route `unstructured`, suspected cause: graph: gold document retrieved by B2 but displaced here (semantic layer)

- B2 answer: "To port your mobile number to another telecom company, follow these steps:\n\n1. Send an SMS containing the word 'PORT' followed by your 10-digit mobile number to 1900 from the number you wish to port. [E3]\n2. You will receive a Unique Porting Code (UPC). [E3]\n3. Within 15 days, visit any store of the new telecom company (in this case, NovaTel) with the UPC and a valid ID proof to complete the porting request. [E3]\n4. Typically, the porting process will be active within 2 working days if the circles are the same, or 4 working days if they are different. [E3]\n\nAfter completing these steps, the number will be transferred to the new telecom company's network. [E1][E2]"
- C answer: 'ABSTAIN.\n\nThe provided evidence does not contain any information related to the process of porting a mobile number to another telecom company. The evidence focuses on issues related to recharges, app access, and KYC verification, which are not relevant to the question at hand.'
- C documents in prompt: ['TRX_001', 'SOP_C13_APP_ACCESS_ISSUES', 'SOP_C17_KYC_VERIFICATION']; added by the layer: ['TRX_001_chunk_000', 'SOP_C13_APP_ACCESS_ISSUES_chunk_000', 'SOP_C17_KYC_VERIFICATION_chunk_000', 'KB_C06_porting_process_chunk_000']

**Run 2** - B2 correctness 2, C correctness 0, C route `unstructured`, suspected cause: graph: gold document retrieved by B2 but displaced here (semantic layer)

- B2 answer: "To port your mobile number to another telecom company, follow these steps:\n\n1. Send an SMS containing the word 'PORT' followed by your 10-digit mobile number to 1900 from the number you wish to port. [E3]\n2. You will receive a Unique Porting Code (UPC). [E3]\n3. Within 15 days, visit any store of the new telecom company (in this case, NovaTel) with the UPC and a valid ID proof to complete the porting request. [E3]\n4. Typically, the porting process will be active within 2 working days if the circles are the same, or 4 working days if they are different. [E3]\n\nAfter completing these steps, the recipient operator (NovaTel in this case) will inform the Mobile Number Portability Service provider a"
- C answer: 'ABSTAIN.\n\nThe provided evidence does not contain any information related to the process of porting a mobile number to another telecom company. The evidence focuses on issues related to recharges, app access, and KYC verification, which are not relevant to the question at hand.'
- C documents in prompt: ['TRX_001', 'SOP_C13_APP_ACCESS_ISSUES', 'SOP_C17_KYC_VERIFICATION']; added by the layer: ['TRX_001_chunk_000', 'SOP_C13_APP_ACCESS_ISSUES_chunk_000', 'SOP_C17_KYC_VERIFICATION_chunk_000', 'KB_C06_porting_process_chunk_000']

**Run 3** - B2 correctness 2, C correctness 0, C route `unstructured`, suspected cause: graph: gold document retrieved by B2 but displaced here (semantic layer)

- B2 answer: "To port your mobile number to another telecom company, follow these steps:\n\n1. Send an SMS containing the word 'PORT' followed by your 10-digit mobile number to 1900 from the number you wish to port. [E3]\n2. You will receive a Unique Porting Code (UPC). [E3]\n3. Within 15 days, visit any store of the new telecom company (in this case, NovaTel) with the UPC and a valid ID proof to complete the porting request. [E3]\n4. Typically, the porting process will be active within 2 working days if the circles are the same, or 4 working days if they are different. [E3]\n\nAfter completing these steps, the recipient operator (NovaTel in this case) will inform the Mobile Number Portability Service provider a"
- C answer: 'ABSTAIN.\n\nThe provided evidence does not contain any information related to the process of porting a mobile number to another telecom company. The evidence focuses on issues related to recharges, app access, and KYC verification, which are not relevant to the question at hand.'
- C documents in prompt: ['TRX_001', 'SOP_C13_APP_ACCESS_ISSUES', 'SOP_C17_KYC_VERIFICATION']; added by the layer: ['TRX_001_chunk_000', 'SOP_C13_APP_ACCESS_ISSUES_chunk_000', 'SOP_C17_KYC_VERIFICATION_chunk_000', 'KB_C06_porting_process_chunk_000']

## S09 (db) - Show kyc_records with status Pending

**Run 1** - B2 correctness 2, C correctness 1, C route `structured`, suspected cause: model: right evidence in the prompt, answer wrong/partial/uncited

- B2 answer: 'The following `kyc_records` with status `Pending` are shown:\n\n- kyc_id=14001, customer_id=2714, kyc_type=Aadhaar, last_updated=2025-07-22 [E1]\n- kyc_id=14009, customer_id=1429, kyc_type=Aadhaar, last_updated=2026-03-14 [E3]\n- kyc_id=14026, customer_id=2574, kyc_type=Voter ID, last_updated=2025-03-23 [E5]\n- kyc_id=14100, customer_id=2482, kyc_type=Voter ID, last_updated=2025-05-08 [E7]\n- kyc_id=14114, customer_id=2125, kyc_type=Aadhaar, last_updated=2024-09-28 [E8]'
- C answer: 'The following `kyc_records` with status Pending are:\n\n- kyc_id=14001, customer_id=2714, kyc_type=Aadhaar, last_updated=2025-07-22 [E1]\n- kyc_id=14009, customer_id=1429, kyc_type=Aadhaar, last_updated=2026-03-14 [E2]\n- kyc_id=14100, customer_id=2482, kyc_type=Voter ID, last_updated=2025-05-08 [E4]\n- kyc_id=14114, customer_id=2125, kyc_type=Aadhaar, last_updated=2024-09-28 [E5]'
- C documents in prompt: []; added by the layer: []

**Run 2** - B2 correctness 2, C correctness 1, C route `structured`, suspected cause: model: right evidence in the prompt, answer wrong/partial/uncited

- B2 answer: 'The following `kyc_records` with status `Pending` are shown:\n\n- kyc_id=14001, customer_id=2714, kyc_type=Aadhaar, last_updated=2025-07-22 [E1]\n- kyc_id=14009, customer_id=1429, kyc_type=Aadhaar, last_updated=2026-03-14 [E3]\n- kyc_id=14026, customer_id=2574, kyc_type=Voter ID, last_updated=2025-03-23 [E5]\n- kyc_id=14100, customer_id=2482, kyc_type=Voter ID, last_updated=2025-05-08 [E7]\n- kyc_id=14114, customer_id=2125, kyc_type=Aadhaar, last_updated=2024-09-28 [E8]'
- C answer: 'kyc_records with status Pending include the following:\n\n- kyc_id=14001, customer_id=2714, kyc_type=Aadhaar [E1]\n- kyc_id=14009, customer_id=1429, kyc_type=Aadhaar [E2]\n- kyc_id=14100, customer_id=2482, kyc_type=Voter ID [E4]\n- kyc_id=14114, customer_id=2125, kyc_type=Aadhaar [E5]'
- C documents in prompt: []; added by the layer: []

**Run 3** - B2 correctness 2, C correctness 1, C route `structured`, suspected cause: model: right evidence in the prompt, answer wrong/partial/uncited

- B2 answer: 'The following `kyc_records` with status `Pending` are shown:\n\n- kyc_id=14001, customer_id=2714, kyc_type=Aadhaar, last_updated=2025-07-22 [E1]\n- kyc_id=14009, customer_id=1429, kyc_type=Aadhaar, last_updated=2026-03-14 [E3]\n- kyc_id=14026, customer_id=2574, kyc_type=Voter ID, last_updated=2025-03-23 [E5]\n- kyc_id=14100, customer_id=2482, kyc_type=Voter ID, last_updated=2025-05-08 [E7]\n- kyc_id=14114, customer_id=2125, kyc_type=Aadhaar, last_updated=2024-09-28 [E8]'
- C answer: 'kyc_records with status Pending include the following:\n\n- kyc_id=14001, customer_id=2714, kyc_type=Aadhaar [E1]\n- kyc_id=14009, customer_id=1429, kyc_type=Aadhaar [E2]\n- kyc_id=14100, customer_id=2482, kyc_type=Voter ID [E4]\n- kyc_id=14114, customer_id=2125, kyc_type=Aadhaar [E5]'
- C documents in prompt: []; added by the layer: []

## S15 (db) - asdkjaslkdj random gibberish query

**Run 1** - B2 correctness 2, C correctness 0, C route `out_of_scope`, suspected cause: router: route=out_of_scope; needed: 

- B2 answer: 'The provided evidence does not contain any relevant information to answer the question "asdkjaslkdj random gibberish query." The evidence consists of data related to telecom performance, subscriber bases, and internet subscriptions, but none of it pertains to the random query provided. Therefore, I cannot provide an answer based on the given evidence. [E1][E2][E3]'
- C answer: "I don't have information about that in the NovaTel knowledge base."
- C documents in prompt: []; added by the layer: []

**Run 2** - B2 correctness 2, C correctness 0, C route `out_of_scope`, suspected cause: router: route=out_of_scope; needed: 

- B2 answer: 'The provided evidence does not contain any relevant information to answer the question "asdkjaslkdj random gibberish query." The evidence consists of data related to telecom performance, subscriber bases, and internet subscriptions, but none of it pertains to the random query provided. Therefore, I cannot provide an answer based on the given evidence. [E1][E2][E3]'
- C answer: "I don't have information about that in the NovaTel knowledge base."
- C documents in prompt: []; added by the layer: []

**Run 3** - B2 correctness 2, C correctness 0, C route `out_of_scope`, suspected cause: router: route=out_of_scope; needed: 

- B2 answer: 'The provided evidence does not contain any relevant information to answer the question "asdkjaslkdj random gibberish query." The evidence consists of data related to telecom performance, subscriber bases, and internet subscriptions, but none of it pertains to the random query provided. Therefore, I cannot provide an answer based on the given evidence. [E1][E2][E3]'
- C answer: "I don't have information about that in the NovaTel knowledge base."
- C documents in prompt: []; added by the layer: []

## MH02 (multi) - In incident INC-2026-0163, how many postpaid customers were billed twice and how quickly were the duplicate charges reversed, and what configuration change made the billing batch run twice?

**Run 1** - B2 correctness 2, C correctness 0, C route `hybrid`, suspected cause: context: docs_in_prompt=False sql_rows_in_prompt=True

- B2 answer: "In incident INC-2026-0163, approximately 12,000 postpaid customers were billed twice due to a duplicate batch-job execution [E2]. The duplicate charges were auto-reversed within 48 hours of detection [E3]. The configuration change that caused the billing batch run twice was a scheduler configuration change that left the previous month's billing job trigger active alongside the new one [E2]."
- C answer: 'The provided evidence does not contain any information related to incident INC-2026-0163, the postpaid customers billed twice, the reversal time of duplicate charges, or the configuration change that caused the billing batch run twice. Therefore, I cannot provide the requested details based on the given evidence. [E1][E2][E3][E4]'
- C documents in prompt: ['RCA_INC_2026_0179', 'RCA_INC_2026_0184', 'RCA_INC_2026_0142']; added by the layer: ['RCA_INC_2026_0179_chunk_000', 'RCA_INC_2026_0184_chunk_000', 'RCA_INC_2026_0142_chunk_000', 'RCA_INC_2026_0197_chunk_000']

**Run 2** - B2 correctness 2, C correctness 0, C route `hybrid`, suspected cause: context: docs_in_prompt=False sql_rows_in_prompt=True

- B2 answer: "In incident INC-2026-0163, approximately 12,000 postpaid customers were billed twice due to a duplicate batch-job execution [E2]. The duplicate charges were auto-reversed within 48 hours of detection [E3]. The configuration change that caused the billing batch run twice was a scheduler configuration change that left the previous month's billing job trigger active alongside the new one [E2]."
- C answer: 'The provided evidence does not contain any information related to incident INC-2026-0163, the postpaid customers billed twice, the reversal time of duplicate charges, or the configuration change that caused the billing batch run twice. Therefore, I cannot provide the requested details based on the given evidence. [E1][E2][E3][E4]'
- C documents in prompt: ['RCA_INC_2026_0179', 'RCA_INC_2026_0184', 'RCA_INC_2026_0142']; added by the layer: ['RCA_INC_2026_0179_chunk_000', 'RCA_INC_2026_0184_chunk_000', 'RCA_INC_2026_0142_chunk_000', 'RCA_INC_2026_0197_chunk_000']

**Run 3** - B2 correctness 2, C correctness 0, C route `hybrid`, suspected cause: context: docs_in_prompt=False sql_rows_in_prompt=True

- B2 answer: "In incident INC-2026-0163, approximately 12,000 postpaid customers were billed twice due to a duplicate batch-job execution [E2]. The duplicate charges were auto-reversed within 48 hours of detection [E3]. The configuration change that caused the billing batch run twice was a scheduler configuration change that left the previous month's billing job trigger active alongside the new one [E2]."
- C answer: 'The provided evidence does not contain any information related to incident INC-2026-0163, the postpaid customers billed twice, the reversal time of duplicate charges, or the configuration change that caused the billing batch run twice. Therefore, I cannot provide the requested details based on the given evidence. [E1][E2][E3][E4]'
- C documents in prompt: ['RCA_INC_2026_0179', 'RCA_INC_2026_0184', 'RCA_INC_2026_0142']; added by the layer: ['RCA_INC_2026_0179_chunk_000', 'RCA_INC_2026_0184_chunk_000', 'RCA_INC_2026_0142_chunk_000', 'RCA_INC_2026_0197_chunk_000']

## MH03 (multi) - For the Pune FTTH outage INC-2026-0179, what time was service restored after detection at 14:02 IST, and what long-term fix does the RCA prioritise for the trunk route?

**Run 1** - B2 correctness 2, C correctness 0, C route `hybrid`, suspected cause: context: docs_in_prompt=False sql_rows_in_prompt=True

- B2 answer: 'The service was restored at 19:45 IST after the detection at 14:02 IST for the Pune FTTH outage INC-2026-0179 [E2].\n\nThe long-term fix prioritised in the RCA for the trunk route is to prioritise route-diversity build-out for the Pune regional trunk given increased customer density, with a target of 6 months and requiring capital planning [E1].'
- C answer: 'The provided evidence does not contain specific information about the Pune FTTH outage INC-2026-0179, including the time service was restored after detection at 14:02 IST or the long-term fix prioritised in the RCA for the trunk route. Therefore, I cannot provide the requested details based on the given evidence. [E1] discusses a 4G outage in the Mumbai West 4G cluster but does not provide the specific details about the outage INC-2026-0179.'
- C documents in prompt: ['RCA_INC_2026_0142', 'RCA_INC_2026_0184', 'RCA_INC_2026_0197']; added by the layer: ['RCA_INC_2026_0184_chunk_000', 'RCA_INC_2026_0197_chunk_000', 'RCA_INC_2026_0163_chunk_000', 'INC_C07_INC_2026_0190_chunk_000']

**Run 2** - B2 correctness 2, C correctness 0, C route `hybrid`, suspected cause: context: docs_in_prompt=False sql_rows_in_prompt=True

- B2 answer: 'The service was restored at 19:45 IST after the detection at 14:02 IST for the Pune FTTH outage INC-2026-0179 [E2].\n\nThe long-term fix prioritised in the RCA for the trunk route is to prioritise route-diversity build-out for the Pune regional trunk given increased customer density, with a target of 6 months and requiring capital planning [E1].'
- C answer: 'The provided evidence does not contain specific information about the Pune FTTH outage INC-2026-0179, including the time service was restored after detection at 14:02 IST or the long-term fix prioritised in the RCA for the trunk route. Therefore, I cannot provide the requested details based on the given evidence. [E1][E2][E3]'
- C documents in prompt: ['RCA_INC_2026_0142', 'RCA_INC_2026_0184', 'RCA_INC_2026_0197']; added by the layer: ['RCA_INC_2026_0184_chunk_000', 'RCA_INC_2026_0197_chunk_000', 'RCA_INC_2026_0163_chunk_000', 'INC_C07_INC_2026_0190_chunk_000']

**Run 3** - B2 correctness 2, C correctness 0, C route `hybrid`, suspected cause: context: docs_in_prompt=False sql_rows_in_prompt=True

- B2 answer: 'The service was restored at 19:45 IST after the detection at 14:02 IST for the Pune FTTH outage INC-2026-0179 [E2].\n\nThe long-term fix prioritised in the RCA for the trunk route is to prioritise route-diversity build-out for the Pune regional trunk given increased customer density, with a target of 6 months and requiring capital planning [E1].'
- C answer: 'The provided evidence does not contain specific information about the Pune FTTH outage INC-2026-0179, including the time service was restored after detection at 14:02 IST or the long-term fix prioritised in the RCA for the trunk route. Therefore, I cannot provide the requested details based on the given evidence. [E1][E2][E3]'
- C documents in prompt: ['RCA_INC_2026_0142', 'RCA_INC_2026_0184', 'RCA_INC_2026_0197']; added by the layer: ['RCA_INC_2026_0184_chunk_000', 'RCA_INC_2026_0197_chunk_000', 'RCA_INC_2026_0163_chunk_000', 'INC_C07_INC_2026_0190_chunk_000']

## MH04 (multi) - In the My NovaTel app login outage INC-2026-0184, how long were logins blocked and why did the automated testing not catch the cause?

**Run 1** - B2 correctness 2, C correctness 0, C route `structured`, suspected cause: router: route=structured; needed: docs

- B2 answer: "In the My NovaTel App Login Outage INC-2026-0184, logins were blocked for 55 minutes following an authentication service deployment [E1]. The automated testing did not catch the cause because the deployment's automated smoke tests did not include a certificate-validity/environment check [E1]. Specifically, a TLS certificate reference in the new deployment pointed to a staging certificate rather than production [E1].\n\nThe incident was detected via monitoring/alarms or customer reports [E1]. The root cause was identified as a misconfiguration in the TLS certificate reference, which was not caught by the deployment's automated smoke tests [E1]. The contributing factor was that the smoke tests d"
- C answer: "I don't have enough evidence to answer this question. Abstaining."
- C documents in prompt: []; added by the layer: []

**Run 2** - B2 correctness 2, C correctness 0, C route `structured`, suspected cause: router: route=structured; needed: docs

- B2 answer: "In the My NovaTel App Login Outage INC-2026-0184, logins were blocked for 55 minutes following an authentication service deployment [E1]. The automated testing did not catch the cause because the deployment's automated smoke tests did not include a certificate-validity/environment check [E1]. Specifically, a TLS certificate reference in the new deployment pointed to a staging certificate rather than production [E1].\n\nThe incident was detected via monitoring/alarms or customer reports [E1]. The root cause was identified as a misconfiguration in the TLS certificate reference, which was not caught by the deployment's automated smoke tests [E1]. The contributing factor was that the smoke tests d"
- C answer: "I don't have enough evidence to answer this question. Abstaining."
- C documents in prompt: []; added by the layer: []

**Run 3** - B2 correctness 2, C correctness 0, C route `structured`, suspected cause: router: route=structured; needed: docs

- B2 answer: "In the My NovaTel App Login Outage INC-2026-0184, logins were blocked for 55 minutes following an authentication service deployment [E1]. The automated testing did not catch the cause because the deployment's automated smoke tests did not include a certificate-validity/environment check [E1]. Specifically, a TLS certificate reference in the new deployment pointed to a staging certificate rather than production [E1].\n\nThe incident was detected via monitoring/alarms or customer reports [E1]. The root cause was identified as a misconfiguration in the TLS certificate reference, which was not caught by the deployment's automated smoke tests [E1]. The contributing factor was that the smoke tests d"
- C answer: "I don't have enough evidence to answer this question. Abstaining."
- C documents in prompt: []; added by the layer: []

## MH_RB_B02 (cross) - For customer 1056: My last recharge didn't go through - what happens to the money, and what should I do?

**Run 1** - B2 correctness 2, C correctness 1, C route `hybrid`, suspected cause: competing: gold first, but cited ['TRX_001']

- B2 answer: 'For customer 1056, the last recharge of ₹949 did not go through, as indicated by the transaction status being FAILED [E1]. According to the documentation [E2], when a recharge is debited but not credited, the amount is typically auto-reversed to the source account within 24 hours if it is not auto-credited by then. \n\nThe customer should be informed that the amount will be automatically refunded to the original payment source if the issue is not resolved within 24 hours. If the customer is concerned, they can contact customer support for further assistance. The standard procedure for handling such cases is documented in [E6], which outlines the steps to diagnose and resolve the issue, includi'
- C answer: 'For customer 1056, the last recharge transaction (recharge_id=4996) did not go through, as its status is FAILED [E1]. According to the standard procedure outlined in the document [E2], the transaction will typically be auto-reconciled within 60 minutes. However, if the issue persists after 24 hours, a manual reconciliation ticket should be raised to the Payments Ops team. If the gateway confirms the debit but NovaTel has no record within 48 hours, a goodwill account-balance credit will be processed pending final reconciliation, and the transaction will be flagged for audit [E2].\n\nIn the event that the transaction remains unresolved, the customer will be informed that the amount will be autom'
- C documents in prompt: ['SOP_C03_RECHARGE_FAILURE', 'KB_C03_recharge_failures', 'TRX_001']; added by the layer: ['FAQ_C03_006_chunk_000', 'FAQ_C02_003_chunk_000', 'FAQ_C20_039_chunk_001']

**Run 2** - B2 correctness 2, C correctness 1, C route `hybrid`, suspected cause: competing: gold first, but cited ['TRX_001']

- B2 answer: 'For customer 1056, the last recharge of ₹949 did not go through, as indicated by the transaction status being FAILED [E1]. According to the documentation [E2], when a recharge is debited but not credited, the amount is typically auto-reversed to the source account within 24 hours if it is not auto-credited by then. \n\nThe customer should be informed that the amount will be automatically refunded to the original source if the issue is not resolved within 24 hours. If the customer is concerned, they can contact customer support for further assistance. The standard procedure for handling such cases is documented in [E6], which outlines the steps to diagnose and resolve the issue, including raisi'
- C answer: 'For customer 1056, the last recharge transaction (recharge_id=4996) did not go through, as its status is FAILED [E1]. According to the standard procedure outlined in the document [E2], the transaction will typically be auto-reconciled within 60 minutes. However, if the issue persists after 24 hours, a manual reconciliation ticket should be raised to the Payments Ops team. If the gateway confirms the debit but NovaTel has no record within 48 hours, a goodwill account-balance credit will be processed pending final reconciliation, and the transaction will be flagged for audit [E2].\n\nIn the event that the transaction remains unresolved, the customer will be informed that the amount will be autom'
- C documents in prompt: ['SOP_C03_RECHARGE_FAILURE', 'KB_C03_recharge_failures', 'TRX_001']; added by the layer: ['FAQ_C03_006_chunk_000', 'FAQ_C02_003_chunk_000', 'FAQ_C20_039_chunk_001']

**Run 3** - B2 correctness 2, C correctness 1, C route `hybrid`, suspected cause: competing: gold first, but cited ['TRX_001']

- B2 answer: 'For customer 1056, the last recharge of ₹949 did not go through, as indicated by the transaction status being FAILED [E1]. According to the documentation [E2], when a recharge is debited but not credited, the amount is typically auto-reversed to the source account within 24 hours if it is not auto-credited by then. \n\nThe customer should be informed that the amount will be automatically refunded to the original source if the issue is not resolved within 24 hours. If the customer is concerned, they can contact customer support for further assistance. The standard procedure for handling such cases is documented in [E6], which outlines the steps to diagnose and resolve the issue, including raisi'
- C answer: 'For customer 1056, the last recharge transaction (recharge_id=4996) did not go through, as its status is FAILED [E1]. According to the standard procedure outlined in the document [E2], the transaction will typically be auto-reconciled within 60 minutes. However, if the issue persists after 24 hours, a manual reconciliation ticket should be raised to the Payments Ops team. If the gateway confirms the debit but NovaTel has no record within 48 hours, a goodwill account-balance credit will be processed pending final reconciliation, and the transaction will be flagged for audit [E2].\n\nIn the event that the transaction remains unresolved, the customer will be informed that the amount will be autom'
- C documents in prompt: ['SOP_C03_RECHARGE_FAILURE', 'KB_C03_recharge_failures', 'TRX_001']; added by the layer: ['FAQ_C03_006_chunk_000', 'FAQ_C02_003_chunk_000', 'FAQ_C20_039_chunk_001']


# Regressions: right in B, wrong in C

Summary C vs B: wins 10, losses 5, ties 27, McNemar exact p = 0.3018; paired bootstrap 95% CI [-4.8, 28.6] pts (mean +11.9 pts). Questions where C lost: ['Q17', 'RW_017', 'S15', 'MH02', 'MH_RB_B02'].

## Q17 (syn) - What documents do I need to provide if NovaTel asks me to complete KYC verification again?

- Run 1: B correctness 2, C correctness 0, C route `unstructured`, suspected cause: ranking: gold present but not first; cited distractor ['TRX_007', 'EML_008']
- Run 2: B correctness 2, C correctness 0, C route `unstructured`, suspected cause: ranking: gold present but not first; cited distractor ['TRX_007', 'EML_008']
- Run 3: B correctness 2, C correctness 0, C route `unstructured`, suspected cause: ranking: gold present but not first; cited distractor ['TRX_007', 'EML_008']

## RW_017 (trai) - How do I port my mobile number to another telecom company?

- Run 1: B correctness 2, C correctness 0, C route `unstructured`, suspected cause: graph: gold document retrieved by B2 but displaced here (semantic layer)
- Run 2: B correctness 2, C correctness 0, C route `unstructured`, suspected cause: graph: gold document retrieved by B2 but displaced here (semantic layer)
- Run 3: B correctness 2, C correctness 0, C route `unstructured`, suspected cause: graph: gold document retrieved by B2 but displaced here (semantic layer)

## S15 (db) - asdkjaslkdj random gibberish query

- Run 1: B correctness 2, C correctness 0, C route `out_of_scope`, suspected cause: router: route=out_of_scope; needed: 
- Run 2: B correctness 2, C correctness 0, C route `out_of_scope`, suspected cause: router: route=out_of_scope; needed: 
- Run 3: B correctness 2, C correctness 0, C route `out_of_scope`, suspected cause: router: route=out_of_scope; needed: 

## MH02 (multi) - In incident INC-2026-0163, how many postpaid customers were billed twice and how quickly were the duplicate charges reversed, and what configuration change made the billing batch run twice?

- Run 1: B correctness 2, C correctness 0, C route `hybrid`, suspected cause: context: docs_in_prompt=False sql_rows_in_prompt=True
- Run 2: B correctness 2, C correctness 0, C route `hybrid`, suspected cause: context: docs_in_prompt=False sql_rows_in_prompt=True
- Run 3: B correctness 2, C correctness 0, C route `hybrid`, suspected cause: context: docs_in_prompt=False sql_rows_in_prompt=True

## MH_RB_B02 (cross) - For customer 1056: My last recharge didn't go through - what happens to the money, and what should I do?

- Run 1: B correctness 2, C correctness 1, C route `hybrid`, suspected cause: competing: gold first, but cited ['TRX_001']
- Run 2: B correctness 2, C correctness 1, C route `hybrid`, suspected cause: competing: gold first, but cited ['TRX_001']
- Run 3: B correctness 2, C correctness 1, C route `hybrid`, suspected cause: competing: gold first, but cited ['TRX_001']


# Regressions: right in A, wrong in C

Summary C vs A: wins 22, losses 3, ties 17, McNemar exact p = 0.0002; paired bootstrap 95% CI [26.2, 64.3] pts (mean +45.2 pts). Questions where C lost: ['Q08', 'RW_017', 'S15'].

## Q08 (syn) - There is no mobile signal where I am. How can I find out whether NovaTel is having a network outage?

- Run 1: A correctness 2, C correctness 1, C route `unstructured`, suspected cause: ranking: gold present but not first; cited distractor ['FAQ_C08_016']
- Run 2: A correctness 2, C correctness 1, C route `unstructured`, suspected cause: ranking: gold present but not first; cited distractor ['FAQ_C08_016']
- Run 3: A correctness 2, C correctness 1, C route `unstructured`, suspected cause: ranking: gold present but not first; cited distractor ['FAQ_C08_016']

## RW_017 (trai) - How do I port my mobile number to another telecom company?

- Run 1: A correctness 2, C correctness 0, C route `unstructured`, suspected cause: graph: gold document retrieved by B2 but displaced here (semantic layer)
- Run 2: A correctness 2, C correctness 0, C route `unstructured`, suspected cause: graph: gold document retrieved by B2 but displaced here (semantic layer)
- Run 3: A correctness 2, C correctness 0, C route `unstructured`, suspected cause: graph: gold document retrieved by B2 but displaced here (semantic layer)

## S15 (db) - asdkjaslkdj random gibberish query

- Run 1: A correctness 2, C correctness 0, C route `out_of_scope`, suspected cause: router: route=out_of_scope; needed: 
- Run 2: A correctness 2, C correctness 0, C route `out_of_scope`, suspected cause: router: route=out_of_scope; needed: 
- Run 3: A correctness 2, C correctness 0, C route `out_of_scope`, suspected cause: router: route=out_of_scope; needed: 
