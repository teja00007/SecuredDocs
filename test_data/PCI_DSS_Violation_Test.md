# ⚠️ SYNTHETIC TEST DOCUMENT — FICTIONAL DATA ONLY
# PCI-DSS Violation Test — Payment Card & Financial Data
# For compliance scanner testing. All card numbers are test/invalid values.

---

# Payment Processing Records — FakeShop Inc. (FICTIONAL)

**Report Date:** March 14, 2026
**Department:** Finance / Billing

---

## Transaction Record #1

**Customer:** John Q. Testperson (fictional)
**Card Type:** Visa
**Card Number:** 4111 1111 1111 1111
**CVV:** 123
**Expiry:** 09/28
**Billing Address:** 742 Evergreen Terrace, Springfield, IL 62701
**Bank Account Number:** 12345678901234
**Routing Number:** 021000021
**Transaction Amount:** $4,750.00
**Authorization Code:** AUTH-2026-001

---

## Transaction Record #2

**Customer:** Mary A. Demopatient (fictional)
**Card Type:** Mastercard
**Card Number:** 5500 0000 0000 0004
**CVV:** 456
**Expiry:** 12/27
**IBAN:** GB29NWBK60161331926819
**Bank Account Number:** 98765432109876
**Transaction Amount:** $2,100.00

---

## Transaction Record #3

**Customer:** Carlos T. Synthdata (fictional)
**Card Type:** American Express
**Card Number:** 3714 496353 98431
**CVV2:** 7893
**Expiry:** 06/29
**Bank Account:** 11223344556677
**Transaction Amount:** $899.99

---

## Unencrypted Card Dump (TEST — Violation Example)

The following card numbers were exported in plaintext for "reporting purposes"
and emailed to the finance team — a direct PCI-DSS violation:

| Customer ID  | Card Number          | CVV | Expiry | Amount    |
|--------------|----------------------|-----|--------|-----------|
| CUST-001     | 4111 1111 1111 1111  | 123 | 09/28  | $4,750.00 |
| CUST-002     | 5500 0000 0000 0004  | 456 | 12/27  | $2,100.00 |
| CUST-003     | 3714 496353 98431    | 789 | 06/29  | $  899.99 |
| CUST-004     | 6011 0009 9013 9424  | 321 | 03/30  | $1,200.00 |
| CUST-005     | 3566 0020 2036 0505  | 654 | 11/28  | $  349.00 |

---

## PCI-DSS Violations Present (Test Reference)

| Violation Type                              | PCI-DSS Requirement |
|---------------------------------------------|---------------------|
| Primary Account Number (PAN) stored in clear | Req. 3.4            |
| CVV/CVV2 stored after authorization          | Req. 3.2            |
| Unencrypted card data in document/email      | Req. 4.2            |
| Bank account + routing number exposed        | Req. 3              |
| IBAN in plaintext                            | Req. 3              |
| Card data in bulk export table               | Req. 3.4, 4.2       |

---

*All card numbers above are test values (Luhn-valid test PANs used by payment processors).*
*No real cardholder data is present. Safe to use in QA/staging environments.*
