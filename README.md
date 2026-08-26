# Cashly V3 — ShopBack-style Cashback Platform

V3 adds a real end-user flow and cashback operations:

## Consumer
- Register / login
- Secure session cookie
- Modern cashback homepage
- Shopee tracked-link generation
- unique click_id + sub_id per user
- cashback activity
- wallet
- pending / confirmed cashback
- withdrawal requests
- ledger history

## Admin
- Modern Affiliate Operations Console
- Shopee Affiliate ID status
- QR-session connection controls
- CSV/XLSX affiliate report import
- automatic Sub ID -> click -> user matching
- automatic cashback calculation
- confirmed credit / rejected reversal
- finance summary
- withdrawal review / processing / approval / rejection
- merchant list

## Report importer
The importer automatically looks for common column names equivalent to:
- sub_id
- order_id
- order_amount
- commission_amount
- status

This is intentionally flexible because affiliate report column naming can differ.

## Important
The automatic cashback flow depends on the Shopee affiliate report actually containing your Sub ID value. If Shopee omits Sub ID in a given report, those orders cannot be automatically matched to a user.

## Production before launch
- PostgreSQL
- email verification / password reset
- CSRF protection
- rate limiting
- secure admin authentication instead of URL token
- reconciliation / payout provider
- audited report mapping using a real Shopee export sample
