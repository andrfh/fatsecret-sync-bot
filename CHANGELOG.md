# Changelog

All notable changes to this project are documented in this file.

## 1.0.0 — 2026-09-21

- Added meal recognition from photos, captions, and text descriptions.
- Added Russian and English Telegram interfaces.
- Added FatSecret OAuth 1.0 connection and confirmed diary writes.
- Added verified food and serving matching with server-side nutrition calculations.
- Added a final review step before writing to FatSecret.
- Added durable duplicate-write protection and explicit handling of uncertain POST outcomes.
- Added bounded retries, request timeouts, temporary meal-state expiry, and metadata-only logging.
- Added a daily allowance of four recognitions for regular users and unlimited access for premium users.
- Added in-chat Privacy Policy and Terms notices.

### Known limitation

Public scaling remains blocked until FatSecret provides written confirmation that the project's
minimized FatSecret data may be sent to Gemini for matching.
